import os
from typing import Any, Optional
from github import Github, GithubIntegration
from github.Repository import Repository as GHRepository
from github.WorkflowJob import WorkflowJob
from github.CheckRun import CheckRun
from github.PullRequest import PullRequest as GHPullRequest
from github.Commit import Commit as GHCommit

from .config import get_config


class GitHubReadClient:
    def __init__(self):
        self.config = get_config()
        self._integration: Optional[GithubIntegration] = None
        self._installation_client: Optional[Github] = None

    def _get_installation_client(self, installation_id: int) -> Github:
        if not self._integration:
            self._integration = GithubIntegration(
                self.config.github_app_id, self.config.github_app_private_key
            )
        token = self._integration.get_access_token(installation_id).token
        return Github(token)

    def get_repository(self, installation_id: int, owner: str, name: str) -> GHRepository:
        client = self._get_installation_client(installation_id)
        return client.get_repo(f"{owner}/{name}")

    def get_workflow_job(self, installation_id: int, owner: str, name: str, job_id: int) -> WorkflowJob:
        repo = self.get_repository(installation_id, owner, name)
        return repo.get_workflow_job(job_id)

    def get_check_run(self, installation_id: int, owner: str, name: str, check_run_id: int) -> CheckRun:
        repo = self.get_repository(installation_id, owner, name)
        return repo.get_check_run(check_run_id)

    def get_pull_request(self, installation_id: int, owner: str, name: str, pr_number: int) -> GHPullRequest:
        repo = self.get_repository(installation_id, owner, name)
        return repo.get_pull(pr_number)

    def get_commit(self, installation_id: int, owner: str, name: str, sha: str) -> GHCommit:
        repo = self.get_repository(installation_id, owner, name)
        return repo.get_commit(sha)

    def get_workflow_job_logs(
        self, installation_id: int, owner: str, name: str, job_id: int, max_lines: int = 200
    ) -> str:
        repo = self.get_repository(installation_id, owner, name)
        job = repo.get_workflow_job(job_id)
        logs = job.get_logs()
        lines = logs.decode("utf-8", errors="replace").splitlines()
        return "\n".join(lines[-max_lines:])

    def get_check_run_logs(
        self, installation_id: int, owner: str, name: str, check_run_id: int, max_lines: int = 200
    ) -> str:
        repo = self.get_repository(installation_id, owner, name)
        check = repo.get_check_run(check_run_id)
        if check.output and check.output.logs_url:
            import requests
            client = self._get_installation_client(installation_id)
            headers = {"Authorization": f"token {client.get_user().login}"}
            response = requests.get(check.output.logs_url, headers=headers)
            if response.ok:
                lines = response.text.splitlines()
                return "\n".join(lines[-max_lines:])
        return ""

    def get_pull_request_files(
        self, installation_id: int, owner: str, name: str, pr_number: int
    ) -> list[dict[str, Any]]:
        pr = self.get_pull_request(installation_id, owner, name, pr_number)
        files = []
        for f in pr.get_files():
            files.append({
                "filename": f.filename,
                "status": f.status,
                "additions": f.additions,
                "deletions": f.deletions,
                "changes": f.changes,
                "patch": f.patch,
            })
        return files

    def get_pull_request_checks(
        self, installation_id: int, owner: str, name: str, pr_number: int
    ) -> list[CheckRun]:
        repo = self.get_repository(installation_id, owner, name)
        pr = repo.get_pull(pr_number)
        commit = repo.get_commit(pr.head.sha)
        checks = []
        for check in commit.get_check_runs():
            checks.append(check)
        return checks

    def get_workflow_run_jobs(
        self, installation_id: int, owner: str, name: str, run_id: int
    ) -> list[WorkflowJob]:
        repo = self.get_repository(installation_id, owner, name)
        run = repo.get_workflow_run(run_id)
        jobs = []
        for job in run.jobs():
            jobs.append(job)
        return jobs