from typing import Any, Optional
from github import Github, GithubIntegration
from github.Repository import Repository as GHRepository
from github.Issue import Issue
from github.PullRequest import PullRequest as GHPullRequest
from github.IssueComment import IssueComment

from .config import get_config


class GitHubWriteClient:
    def __init__(self):
        self.config = get_config()
        self._integration: Optional[GithubIntegration] = None

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

    def create_issue(
        self,
        installation_id: int,
        owner: str,
        name: str,
        title: str,
        body: str,
        labels: list[str],
    ) -> Issue:
        repo = self.get_repository(installation_id, owner, name)
        return repo.create_issue(title=title, body=body, labels=labels)

    def update_issue(
        self,
        installation_id: int,
        owner: str,
        name: str,
        issue_number: int,
        title: Optional[str] = None,
        body: Optional[str] = None,
        labels: Optional[list[str]] = None,
        state: Optional[str] = None,
    ) -> Issue:
        repo = self.get_repository(installation_id, owner, name)
        issue = repo.get_issue(issue_number)
        if title:
            issue.edit(title=title)
        if body:
            issue.edit(body=body)
        if labels is not None:
            issue.edit(labels=labels)
        if state:
            issue.edit(state=state)
        return issue

    def create_issue_comment(
        self,
        installation_id: int,
        owner: str,
        name: str,
        issue_number: int,
        body: str,
    ) -> IssueComment:
        repo = self.get_repository(installation_id, owner, name)
        issue = repo.get_issue(issue_number)
        return issue.create_comment(body)

    def create_pr_comment(
        self,
        installation_id: int,
        owner: str,
        name: str,
        pr_number: int,
        body: str,
    ) -> IssueComment:
        repo = self.get_repository(installation_id, owner, name)
        pr = repo.get_pull(pr_number)
        return pr.create_issue_comment(body)

    def update_pr_comment(
        self,
        installation_id: int,
        owner: str,
        name: str,
        pr_number: int,
        comment_id: int,
        body: str,
    ) -> IssueComment:
        repo = self.get_repository(installation_id, owner, name)
        pr = repo.get_pull(pr_number)
        comment = pr.get_issue_comment(comment_id)
        comment.edit(body=body)
        return comment

    def find_existing_triage_issue(
        self,
        installation_id: int,
        owner: str,
        name: str,
        commit_sha: str,
    ) -> Optional[Issue]:
        repo = self.get_repository(installation_id, owner, name)
        issues = repo.get_issues(
            state="open",
            labels=["reporelay-triage"],
        )
        for issue in issues:
            if commit_sha in issue.body:
                return issue
        return None

    def find_existing_pr_comment(
        self,
        installation_id: int,
        owner: str,
        name: str,
        pr_number: int,
        marker: str = "reporelay-readiness",
    ) -> Optional[IssueComment]:
        repo = self.get_repository(installation_id, owner, name)
        pr = repo.get_pull(pr_number)
        for comment in pr.get_issue_comments():
            if marker in comment.body:
                return comment
        return None