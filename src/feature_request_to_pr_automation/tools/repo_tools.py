import os
from typing import List, Optional, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from github import Github, GithubException


class RepoReaderInput(BaseModel):
    """Input schema for RepoReaderTool."""
    owner_repo: str = Field(..., description="Repository in owner/repo format.")
    file_extensions: List[str] = Field(
        default_factory=lambda: [
            ".py",
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".json",
            ".md",
            ".yaml",
            ".yml",
            ".toml",
        ],
        description="File extensions to include when reading the repository.",
    )
    max_files: int = Field(50, description="Maximum number of files to fetch contents for.")
    max_bytes_per_file: int = Field(100_000, description="Maximum bytes per file to include.")


class RepoReaderTool(BaseTool):
    name: str = "Read repository structure and sample contents"
    description: str = (
        "Fetch the repository tree and return a concise summary with file list and sample contents."
    )
    args_schema: Type[BaseModel] = RepoReaderInput

    def _run(self, owner_repo: str, file_extensions: List[str], max_files: int, max_bytes_per_file: int) -> str:
        token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_PAT")
        gh = Github(login_or_token=token) if token else Github()
        try:
            repo = gh.get_repo(owner_repo)
            default_branch = repo.default_branch or "main"
            ref = repo.get_git_ref(f"heads/{default_branch}")
            commit = repo.get_git_commit(ref.object.sha)
            tree = repo.get_git_tree(commit.sha, recursive=True)
        except GithubException as e:
            return f"Failed to read repository {owner_repo}: {e}"

        all_paths = [entry.path for entry in tree.tree if entry.type == "blob"]
        filtered_paths = [p for p in all_paths if any(p.endswith(ext) for ext in file_extensions)]
        filtered_paths = filtered_paths[: max_files]

        summary_lines: List[str] = []
        summary_lines.append(f"Repository: {owner_repo}")
        summary_lines.append(f"Default branch: {default_branch}")
        summary_lines.append("\nFiles (truncated):")
        for p in filtered_paths:
            summary_lines.append(f"- {p}")

        summary_lines.append("\nSample contents (truncated):")
        for p in filtered_paths:
            try:
                file = repo.get_contents(p, ref=default_branch)
                content_bytes = file.decoded_content or b""
                snippet = content_bytes[: max_bytes_per_file].decode("utf-8", errors="ignore")
                summary_lines.append(f"\n--- BEGIN {p} ---\n{snippet}\n--- END {p} ---")
            except Exception as e:
                summary_lines.append(f"\n--- BEGIN {p} ---\n[Error reading file: {e}]\n--- END {p} ---")

        return "\n".join(summary_lines)


class FileChange(BaseModel):
    path: str = Field(..., description="File path to create or update.")
    content: str = Field(..., description="Full file content to write.")
    message: str = Field(..., description="Commit message for this file change.")


class SurgicalReplacement(BaseModel):
    path: str = Field(..., description="File path to modify.")
    find_text: str = Field(..., description="Exact text to find.")
    replace_text: str = Field(..., description="Replacement text.")
    count: Optional[int] = Field(
        None,
        description="Max occurrences to replace. None replaces all occurrences.",
    )


class CreatePullRequestInput(BaseModel):
    owner_repo: str = Field(..., description="Repository in owner/repo format.")
    title: str = Field(..., description="Pull request title.")
    body: str = Field(..., description="Pull request body/description.")
    branch_name: Optional[str] = Field(None, description="Name of the feature branch to create.")
    base_branch: Optional[str] = Field(None, description="Base branch to target, defaults to repo default.")
    changes: Optional[List[FileChange]] = Field(
        None, description="List of file changes to commit on the branch."
    )
    replacements: Optional[List[SurgicalReplacement]] = Field(
        None,
        description="List of surgical find/replace edits to apply to files (preferred for minimal diffs).",
    )


class CreatePullRequestTool(BaseTool):
    name: str = "Create pull request with file changes"
    description: str = (
        "Create a branch, commit provided file changes, and open a pull request on the repository."
    )
    args_schema: Type[BaseModel] = CreatePullRequestInput

    def _run(
        self,
        owner_repo: str,
        title: str,
        body: str,
        changes: Optional[List[dict]] = None,
        replacements: Optional[List[dict]] = None,
        branch_name: Optional[str] = None,
        base_branch: Optional[str] = None,
    ) -> str:
        token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or os.getenv("GITHUB_PAT")
        if not token:
            return "Missing GitHub token. Set GITHUB_TOKEN in your environment."

        gh = Github(login_or_token=token)
        try:
            repo = gh.get_repo(owner_repo)
            base = base_branch or repo.default_branch or "main"

            base_ref = repo.get_git_ref(f"heads/{base}")
            base_sha = base_ref.object.sha

            branch = branch_name or f"auto/pr-{abs(hash(title)) % 10_000_000}"
            ref_name = f"refs/heads/{branch}"
            try:
                repo.get_git_ref(f"heads/{branch}")
            except GithubException:
                repo.create_git_ref(ref=ref_name, sha=base_sha)

            # Prefer surgical replacements for minimal diffs
            if replacements:
                for rep in replacements:
                    # Accept dicts or SurgicalReplacement objects
                    if isinstance(rep, dict):
                        path = rep.get("path")
                        find_text = rep.get("find_text")
                        replace_text = rep.get("replace_text")
                        count = rep.get("count")
                    else:
                        path = getattr(rep, "path", None)
                        find_text = getattr(rep, "find_text", None)
                        replace_text = getattr(rep, "replace_text", None)
                        count = getattr(rep, "count", None)

                    if not path or find_text is None or replace_text is None:
                        return "Invalid replacement item: require 'path', 'find_text', 'replace_text'"

                    # Read existing file from base branch first (or from working branch if exists)
                    try:
                        try:
                            existing = repo.get_contents(path, ref=branch)
                        except GithubException:
                            existing = repo.get_contents(path, ref=base)
                        original = (existing.decoded_content or b"").decode("utf-8", errors="ignore")
                    except GithubException:
                        return f"Target file not found for replacement: {path}"

                    # Apply replacement
                    if count is None:
                        updated = original.replace(find_text, replace_text)
                    else:
                        updated = original
                        remaining = count
                        start = 0
                        while remaining and (idx := updated.find(find_text, start)) != -1:
                            updated = updated[:idx] + replace_text + updated[idx + len(find_text) :]
                            start = idx + len(replace_text)
                            remaining -= 1

                    if updated == original:
                        # No-op replacement, continue but informative result
                        continue

                    commit_message = f"{title} (surgical edit)"
                    repo.update_file(
                        path=path,
                        message=commit_message,
                        content=updated,
                        sha=existing.sha,
                        branch=branch,
                    )
            elif changes:
                # Create or update files using full content (fallback)
                for change in changes:
                    # Accept either dicts or FileChange-like objects
                    if isinstance(change, dict):
                        path = change.get("path") or change.get("file_path")
                        content = change.get("content", "")
                        message = change.get("message") or title
                    else:
                        path = getattr(change, "path", None)
                        content = getattr(change, "content", "")
                        message = getattr(change, "message", title)

                    if not path:
                        return "Invalid change item: missing 'path'"

                    try:
                        existing = repo.get_contents(path, ref=branch)
                        repo.update_file(
                            path=path,
                            message=message,
                            content=content,
                            sha=existing.sha,
                            branch=branch,
                        )
                    except GithubException:
                        repo.create_file(
                            path=path,
                            message=message,
                            content=content,
                            branch=branch,
                        )

            pr = repo.create_pull(title=title, body=body, head=branch, base=base)
            return f"PR created: {pr.html_url}"
        except GithubException as e:
            return f"Failed to create PR: {e}"


