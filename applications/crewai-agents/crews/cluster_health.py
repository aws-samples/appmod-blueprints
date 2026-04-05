"""Cluster Health Analysis crew — analyzes K8s cluster state and produces a report."""
import os
from crewai import Agent, Crew, Task, Process, LLM


def build_crew() -> Crew:
    llm = LLM(
        model=os.environ.get(
            "LLM_MODEL", "bedrock/us.anthropic.claude-sonnet-4-20250514-v1:0"
        ),
        temperature=0.7,
    )

    analyst = Agent(
        role="Kubernetes Cluster Analyst",
        goal="Analyze Kubernetes cluster configuration and identify potential issues",
        backstory="You are an expert Kubernetes administrator who specializes in "
        "cluster health analysis. You examine resource usage, pod states, and "
        "configuration patterns to identify issues before they become incidents.",
        llm=llm,
        verbose=True,
    )

    security_reviewer = Agent(
        role="Kubernetes Security Reviewer",
        goal="Review cluster security configuration and identify vulnerabilities",
        backstory="You are a security engineer specializing in Kubernetes security. "
        "You check for common misconfigurations, missing network policies, "
        "overly permissive RBAC, and container security issues.",
        llm=llm,
        verbose=True,
    )

    report_writer = Agent(
        role="Technical Report Writer",
        goal="Create a clear, actionable report from the analysis findings",
        backstory="You are a technical writer who excels at turning complex "
        "infrastructure analysis into clear, prioritized action items.",
        llm=llm,
        verbose=True,
    )

    analysis_task = Task(
        description="Analyze the following Kubernetes cluster state and identify "
        "the top 3 issues that need attention:\n\n{cluster_info}\n\n"
        "For each issue, explain the impact and root cause.",
        expected_output="A structured list of 3 issues with impact and root cause",
        agent=analyst,
    )

    security_task = Task(
        description="Review the security posture of this cluster:\n\n{cluster_info}\n\n"
        "Focus on: network policies, pod security, RBAC, and resource isolation.",
        expected_output="A security assessment with severity ratings",
        agent=security_reviewer,
    )

    report_task = Task(
        description="Using the cluster analysis and security review, create a "
        "concise health report with:\n"
        "1. Executive summary (2-3 sentences)\n"
        "2. Top issues ranked by priority\n"
        "3. Recommended actions with effort estimates\n\n"
        "Format as markdown.",
        expected_output="A markdown-formatted cluster health report",
        agent=report_writer,
    )

    return Crew(
        agents=[analyst, security_reviewer, report_writer],
        tasks=[analysis_task, security_task, report_task],
        process=Process.sequential,
        verbose=True,
    )
