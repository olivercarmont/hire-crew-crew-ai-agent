import os
from crewai import LLM
from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task
from feature_request_to_pr_automation.tools import RepoReaderTool, CreatePullRequestTool


@CrewBase
class FeatureRequestToPrAutomationCrew:
    """FeatureRequestToPrAutomation crew"""

    
    @agent
    def feature_request_processor(self) -> Agent:
        
        return Agent(
            config=self.agents_config["feature_request_processor"],
            tools=[

            ],
            reasoning=False,
            inject_date=True,
            llm=LLM(
                model="claude-3-7-sonnet-20250219",
                temperature=0.7,
            ),
        )
    
    @agent
    def github_repository_analyst(self) -> Agent:
        tools_for_analyst = [RepoReaderTool()]

        return Agent(
            config=self.agents_config["github_repository_analyst"],
            tools=tools_for_analyst,
            reasoning=False,
            inject_date=True,
            llm=LLM(
                model="claude-3-7-sonnet-20250219",
                temperature=0.7,
            ),
        )
    
    @agent
    def code_implementation_specialist(self) -> Agent:
        
        return Agent(
            config=self.agents_config["code_implementation_specialist"],
            tools=[

            ],
            reasoning=False,
            inject_date=True,
            llm=LLM(
                model="claude-3-7-sonnet-20250219",
                temperature=0.7,
            ),
        )
    
    @agent
    def github_pull_request_manager(self) -> Agent:
        return Agent(
            config=self.agents_config["github_pull_request_manager"],
            tools=[CreatePullRequestTool()],
            reasoning=False,
            inject_date=True,
            llm=LLM(
                model="claude-3-7-sonnet-20250219",
                temperature=0.7,
            ),
        )
    

    
    @task
    def process_feature_request(self) -> Task:
        return Task(
            config=self.tasks_config["process_feature_request"],
        )
    
    @task
    def analyze_repository_structure(self) -> Task:
        return Task(
            config=self.tasks_config["analyze_repository_structure"],
        )
    
    @task
    def implement_feature_code(self) -> Task:
        return Task(
            config=self.tasks_config["implement_feature_code"],
        )
    
    @task
    def create_and_submit_pull_request(self) -> Task:
        return Task(
            config=self.tasks_config["create_and_submit_pull_request"],
        )
    

    @crew
    def crew(self) -> Crew:
        """Creates the FeatureRequestToPrAutomation crew"""
        return Crew(
            agents=self.agents,  # Automatically created by the @agent decorator
            tasks=self.tasks,  # Automatically created by the @task decorator
            process=Process.sequential,
            verbose=True,
        )
