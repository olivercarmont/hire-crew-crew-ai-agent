#!/usr/bin/env python
import sys
from feature_request_to_pr_automation.crew import FeatureRequestToPrAutomationCrew

# This main file is intended to be a way for your to run your
# crew locally, so refrain from adding unnecessary logic into this file.
# Replace with inputs you want to test with, it will automatically
# interpolate any tasks and agents information

def run():
    """
    Run the crew.
    """
    import os
    inputs = {
        'feature_title': 'Update navbar CTA label',
        'feature_description': "Change the navbar button text from 'Get Started' to 'Sign up now' on the top of the landing page.",
        'user_requirements': 'Text change only; keep styling and behavior the same.',
        'priority': 'medium',
        'additional_context': 'Next.js app with a Navbar component; likely a button near Sign In.',
        'github_repo_url': os.getenv('GITHUB_REPO_URL', 'sample_value')
    }
    FeatureRequestToPrAutomationCrew().crew().kickoff(inputs=inputs)


def train():
    """
    Train the crew for a given number of iterations.
    """
    import os
    inputs = {
        'feature_title': 'Update navbar CTA label',
        'feature_description': "Change the navbar button text from 'Get Started' to 'Sign up now' on the top of the landing page.",
        'user_requirements': 'Text change only; keep styling and behavior the same.',
        'priority': 'medium',
        'additional_context': 'Next.js app with a Navbar component; likely a button near Sign In.',
        'github_repo_url': os.getenv('GITHUB_REPO_URL', 'sample_value')
    }
    try:
        FeatureRequestToPrAutomationCrew().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        FeatureRequestToPrAutomationCrew().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    """
    import os
    inputs = {
        'feature_title': 'Update navbar CTA label',
        'feature_description': "Change the navbar button text from 'Get Started' to 'Sign up now' on the top of the landing page.",
        'user_requirements': 'Text change only; keep styling and behavior the same.',
        'priority': 'medium',
        'additional_context': 'Next.js app with a Navbar component; likely a button near Sign In.',
        'github_repo_url': os.getenv('GITHUB_REPO_URL', 'sample_value')
    }
    try:
        FeatureRequestToPrAutomationCrew().crew().test(n_iterations=int(sys.argv[1]), openai_model_name=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: main.py <command> [<args>]")
        sys.exit(1)

    command = sys.argv[1]
    if command == "run":
        run()
    elif command == "train":
        train()
    elif command == "replay":
        replay()
    elif command == "test":
        test()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
