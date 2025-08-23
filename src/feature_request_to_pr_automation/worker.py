import os
import time
import json
import re
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client, Client
from github import Github
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr

from feature_request_to_pr_automation.crew import FeatureRequestToPrAutomationCrew


# Load .env from project root if present
load_dotenv()


def _get_env(name: str, required: bool = True, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _dbg_enabled() -> bool:
    try:
        return int(os.getenv("SMTP_DEBUG", "0")) > 0
    except Exception:
        return False


def _dbg(msg: str) -> None:
    if _dbg_enabled():
        print(f"[debug] {msg}")


def _extract_pr_url(text: str) -> Optional[str]:
    if not text:
        return None
    # Prefer lines like "PR created: <url>"
    m = re.search(r"PR\s+created:\s*(https?://[^\s]+)", text, flags=re.IGNORECASE)
    if m:
        return m.group(1)
    # Fallback: any GitHub PR URL
    m = re.search(r"https?://github\.com/[^\s]+/pull/\d+", text)
    return m.group(0) if m else None


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _normalize_row(data) -> Optional[dict]:
    if not data:
        return None
    if isinstance(data, list):
        if not data:
            return None
        data = data[0]
    if not isinstance(data, dict):
        return None
    if data.get("id") is None:
        return None
    return data


def _claim_next(client: Client, worker_id: str) -> Optional[dict]:
    _dbg("RPC claim_next_feature_request()")
    res = client.rpc("claim_next_feature_request", {"p_worker_id": worker_id}).execute()
    row = _normalize_row(res.data)
    _dbg(f"RPC returned: {'row found' if row else 'no row'}")
    return row


def _update_row(client: Client, row_id: str, values: dict) -> None:
    _dbg(f"Updating row {row_id} with {list(values.keys())}")
    client.table("feature_requests").update(values).eq("id", row_id).execute()


def _build_inputs(row: dict) -> dict:
    message: str = (row.get("message") or "").strip()
    name: str = (row.get("name") or "").strip()
    email: str = (row.get("email") or "").strip()

    title = (message[:72] + "…") if len(message) > 72 else (message or "User feedback")
    repo_url = _get_env("GITHUB_REPO_URL", required=False) or ""

    return {
        "feature_title": title,
        "feature_description": message or f"Feedback from {name or 'anonymous'} <{email or 'unknown'}>",
        "user_requirements": "",
        "priority": "medium",
        "additional_context": f"Submitted by: {name} <{email}>",
        "github_repo_url": repo_url,
    }


def _github_client() -> Github:
    token = _get_env("GITHUB_TOKEN", required=False)
    _dbg(f"GitHub client created; token={'set' if token else 'unset'}")
    return Github(login_or_token=token) if token else Github()


def _parse_pr_url(pr_url: str) -> Optional[tuple[str, str, int]]:
    # https://github.com/{owner}/{repo}/pull/{number}
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url)
    if not m:
        return None
    owner, repo, num = m.group(1), m.group(2), int(m.group(3))
    return owner, repo, num


def _check_pr_merged(gh: Github, pr_url: str) -> tuple[bool, Optional[str]]:
    parsed = _parse_pr_url(pr_url)
    if not parsed:
        print(f"[merge-check] Could not parse PR URL: {pr_url}")
        return False, None
    owner, repo, num = parsed
    try:
        _dbg(f"Checking PR merged status for {owner}/{repo}#{num}")
        r = gh.get_repo(f"{owner}/{repo}")
        pr = r.get_pull(num)
        if pr.merged:
            merged_at = pr.merged_at.isoformat() if pr.merged_at else _now_iso()
            print(f"[merge-check] PR merged: {pr_url} at {merged_at}")
            return True, merged_at
        print(f"[merge-check] PR not merged yet: {pr_url}")
        return False, None
    except Exception as e:
        print(f"[merge-check] Error checking PR {pr_url}: {e}")
        return False, None


def _get_pr_details(gh: Github, pr_url: str) -> dict:
    details = {"title": None, "body": None, "files": [], "additions": None, "deletions": None}
    parsed = _parse_pr_url(pr_url)
    if not parsed:
        return details
    try:
        owner, repo, num = parsed
        r = gh.get_repo(f"{owner}/{repo}")
        pr = r.get_pull(num)
        details["title"] = pr.title or None
        details["body"] = (pr.body or "").strip() or None
        details["additions"] = pr.additions
        details["deletions"] = pr.deletions
        files = []
        try:
            for f in pr.get_files()[:5]:
                files.append(f.filename)
        except Exception:
            pass
        details["files"] = files
    except Exception:
        pass
    return details


def _build_email_body(row: dict, pr_url: str) -> tuple[str, str]:
    gh = _github_client()
    pr = _get_pr_details(gh, pr_url)
    name = row.get("name") or "there"
    message = (row.get("message") or "").strip()

    # Plain-English summary and subject
    fallback_summary = (message[:80] + "…") if len(message) > 80 else (message or "Your request was implemented")
    summary = pr.get("title") or fallback_summary
    subject = f"hireCrew Feature Request: {summary}"

    # Build a concise body with PR details
    lines = [
        f"Hi {name},",
        "",
        "Your requested change has been merged and is live.",
        "",
        f"Summary: {summary}",
        "",
    ]

    if message:
        lines.append(f"Request: {message}")
    if pr_url:
        lines.append(f"Pull Request: {pr_url}")

    files = pr.get("files") or []
    additions = pr.get("additions")
    deletions = pr.get("deletions")

    if files or (additions is not None) or (deletions is not None):
        lines.append("")
        lines.append("What changed:")
        if files:
            for f in files:
                lines.append(f"- {f}")
        if (additions is not None) or (deletions is not None):
            lines.append(f"- Diff stats: +{additions or 0} / -{deletions or 0}")

    pr_body = (pr.get("body") or "").strip()
    if pr_body:
        first_para = pr_body.splitlines()
        excerpt = []
        for ln in first_para:
            if ln.strip() == "" and excerpt:
                break
            excerpt.append(ln)
        excerpt_text = "\n".join(excerpt).strip()
        if excerpt_text:
            lines.append("")
            lines.append("Details:")
            lines.append(excerpt_text)

    lines.append("")
    lines.append("Thank you for helping improve hireCrew!")

    body = "\n".join(lines)
    return subject, body


def _send_email(to_email: str, subject: str, body: str) -> bool:
    host = _get_env("SMTP_HOST", required=False)
    user = _get_env("SMTP_USER", required=False)
    password = _get_env("SMTP_PASS", required=False)
    from_addr = _get_env("SMTP_FROM", required=False) or (user or "")
    port = int(os.getenv("SMTP_PORT", "587"))
    debug = int(os.getenv("SMTP_DEBUG", "0"))

    if not host or not from_addr:
        print("[email] SMTP not configured; skipping send")
        return False

    _dbg(f"SMTP config host={host} port={port} from={from_addr} to={to_email} user={'set' if user else 'unset'} mode={'SSL' if port==465 else 'STARTTLS/PLAIN'}")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("hireCrew", from_addr))
    msg["To"] = to_email

    try:
        if port == 465:
            _dbg("Opening SMTP_SSL connection")
            with smtplib.SMTP_SSL(host, port, timeout=20) as server:
                if debug:
                    server.set_debuglevel(1)
                if user and password:
                    _dbg("Logging in (SSL)")
                    server.login(user, password)
                _dbg("Sending email (SSL)")
                server.sendmail(from_addr, [to_email], msg.as_string())
        else:
            _dbg("Opening SMTP connection")
            with smtplib.SMTP(host, port, timeout=20) as server:
                if debug:
                    server.set_debuglevel(1)
                try:
                    _dbg("EHLO")
                    server.ehlo()
                except Exception as e:
                    _dbg(f"EHLO failed: {e}")
                try:
                    _dbg("STARTTLS")
                    server.starttls()
                    try:
                        _dbg("EHLO after STARTTLS")
                        server.ehlo()
                    except Exception as e:
                        _dbg(f"EHLO-after-STARTTLS failed: {e}")
                except Exception as e:
                    _dbg(f"STARTTLS skipped/failed: {e}")
                if user and password:
                    _dbg("Logging in")
                    server.login(user, password)
                _dbg("Sending email")
                server.sendmail(from_addr, [to_email], msg.as_string())
        print(f"[email] Sent to {to_email}")
        return True
    except Exception as e:
        print(f"[email] Failed to send to {to_email}: {e}")
        return False


def _check_and_notify_merges(client: Client) -> None:
    # Fetch recent done requests; filter in Python for simplicity
    _dbg("Fetching recent 'done' requests for merge check")
    res = (
        client
        .table("feature_requests")
        .select("*")
        .eq("status", "done")
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    all_rows = res.data or []
    _dbg(f"Fetched {len(all_rows)} rows")
    rows = [
        r for r in all_rows
        if r.get("pr_url") and not bool(r.get("pr_merged"))
    ]
    _dbg(f"Filtered to {len(rows)} rows with pr_url and not merged")
    if not rows:
        return

    gh = _github_client()

    for row in rows:
        pr_url = row.get("pr_url")
        if not pr_url:
            continue

        merged, merged_at = _check_pr_merged(gh, pr_url)
        if not merged:
            continue

        updates = {
            "pr_merged": True,
            "merged_at": merged_at or _now_iso(),
        }

        # Email if opted-in and not yet emailed
        should_email = bool(row.get("should_email_user"))
        already_emailed = bool(row.get("user_emailed"))
        email = (row.get("email") or "").strip()
        _dbg(
            f"Notify? should_email={should_email} already_emailed={already_emailed} email_present={'yes' if email else 'no'}"
        )
        if should_email and not already_emailed and email:
            subject, body = _build_email_body(row, pr_url)
            sent = _send_email(email, subject, body)
            if sent:
                updates["user_emailed"] = True

        _update_row(client, row["id"], updates)
        print(f"[merge-check] Updated row {row['id']} with merged info and notifications")


def _send_pending_notifications(client: Client) -> None:
    # Send emails for already-merged rows where user asked to be notified but hasn't been emailed
    _dbg("Checking pending notifications for merged rows")
    res = (
        client
        .table("feature_requests")
        .select("*")
        .eq("pr_merged", True)
        .eq("should_email_user", True)
        .eq("user_emailed", False)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    rows = res.data or []
    _dbg(f"Pending notifications: {len(rows)} rows")
    if not rows:
        return

    gh = _github_client()

    for row in rows:
        email = (row.get("email") or "").strip()
        pr_url = row.get("pr_url")
        if not email or not pr_url:
            continue
        subject, body = _build_email_body(row, pr_url)
        sent = _send_email(email, subject, body)
        if sent:
            _update_row(client, row["id"], {"user_emailed": True})
            print(f"[email] Marked row {row['id']} as emailed")


def process_one(client: Client, worker_id: str, poll_delay_seconds: int = 5) -> None:
    row = _claim_next(client, worker_id)
    if not row:
        _dbg("No pending job; running merge-check")
        # Even if no new job, still check merges to notify users
        _check_and_notify_merges(client)
        # Also attempt notifications for already-merged rows
        _send_pending_notifications(client)
        time.sleep(poll_delay_seconds)
        return

    row_id = row["id"]
    _dbg(f"Claimed job {row_id}")
    try:
        crew = FeatureRequestToPrAutomationCrew().crew()
        inputs = _build_inputs(row)
        _dbg("Running crew kickoff")
        result = crew.kickoff(inputs=inputs)
        # Convert result to string/json for storage
        try:
            result_str = str(result)
        except Exception:
            result_str = json.dumps(result, default=str)

        pr_url = _extract_pr_url(result_str) or None
        _dbg(f"Extracted PR URL: {pr_url}")

        _update_row(
            client,
            row_id,
            {
                "status": "done",
                "agent_run_at": _now_iso(),
                "pr_url": pr_url,
                "agent_output": {"inputs": inputs, "result": result_str},
                "error": None,
            },
        )
        print(f"Processed {row_id}; PR: {pr_url or 'n/a'}")

        # After processing a job, also check merges for notifications
        _check_and_notify_merges(client)
        _send_pending_notifications(client)
    except Exception as e:
        print(f"Error processing {row_id}: {e}")
        _update_row(
            client,
            row_id,
            {
                "status": "failed",
                "agent_run_at": _now_iso(),
                "error": str(e),
                "retry_count": (row.get("retry_count") or 0) + 1,
            },
        )


def run_worker() -> None:
    supabase_url = _get_env("SUPABASE_URL")
    supabase_key = _get_env("SUPABASE_SERVICE_ROLE_KEY")
    client: Client = create_client(supabase_url, supabase_key)

    worker_id = os.getenv("WORKER_ID") or os.getenv("HOSTNAME") or f"local-{os.getpid()}"
    poll_seconds = int(os.getenv("POLL_DELAY_SECONDS", "5"))

    print("CrewAI worker started. Polling Supabase for pending feature requests…")
    _dbg(f"Worker ID: {worker_id}; Poll every {poll_seconds}s")
    while True:
        process_one(client, worker_id, poll_delay_seconds=poll_seconds)


if __name__ == "__main__":
    run_worker()

