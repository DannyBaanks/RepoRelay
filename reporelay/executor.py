from dataclasses import dataclass
from typing import Any, Optional
from .tools.github_write import GitHubWriteClient
from .events import NormalizedEvent
from .agent import ActionProposal
from .policy import PolicyEngine, PolicyResult, PolicyDecision


@dataclass(frozen=True)
class ActionResult:
    success: bool
    action_type: str
    github_issue_number: Optional[int] = None
    github_comment_id: Optional[int] = None
    error: Optional[str] = None
    details: Optional[dict[str, Any]] = None


class ActionExecutor:
    def __init__(self, write_client: GitHubWriteClient, policy_engine: PolicyEngine):
        self.write_client = write_client
        self.policy_engine = policy_engine

    def execute(
        self,
        proposal: ActionProposal,
        installation_id: int,
        owner: str,
        repo: str,
        event: NormalizedEvent,
    ) -> ActionResult:
        validation = self.policy_engine.validate_action(proposal.__dict__)
        if validation.decision != PolicyDecision.PROCEED:
            return ActionResult(
                success=False,
                action_type=proposal.action,
                error=f"Policy rejected: {validation.reason}",
            )

        try:
            if proposal.action == "create_issue":
                return self._create_issue(proposal, installation_id, owner, repo, event)
            elif proposal.action == "create_pr_comment":
                return self._create_pr_comment(proposal, installation_id, owner, repo, event)
            elif proposal.action == "update_issue":
                return self._update_issue(proposal, installation_id, owner, repo, event)
            elif proposal.action == "update_pr_comment":
                return self._update_pr_comment(proposal, installation_id, owner, repo, event)
            else:
                return ActionResult(
                    success=False,
                    action_type=proposal.action,
                    error=f"Unknown action: {proposal.action}",
                )
        except Exception as e:
            return ActionResult(
                success=False,
                action_type=proposal.action,
                error=str(e),
            )

    def _create_issue(
        self,
        proposal: ActionProposal,
        installation_id: int,
        owner: str,
        repo: str,
        event: NormalizedEvent,
    ) -> ActionResult:
        existing = self.write_client.find_existing_triage_issue(
            installation_id, owner, repo, event.commit.sha if event.commit else ""
        )
        if existing:
            updated = self.write_client.update_issue(
                installation_id, owner, repo, existing.number,
                title=proposal.title,
                body=proposal.body,
                labels=proposal.labels,
            )
            return ActionResult(
                success=True,
                action_type="update_issue",
                github_issue_number=updated.number,
                details={"updated": True},
            )

        issue = self.write_client.create_issue(
            installation_id, owner, repo,
            title=proposal.title or "CI Triage",
            body=proposal.body or "",
            labels=proposal.labels or ["reporelay-triage"],
        )
        return ActionResult(
            success=True,
            action_type="create_issue",
            github_issue_number=issue.number,
            details={"created": True},
        )

    def _create_pr_comment(
        self,
        proposal: ActionProposal,
        installation_id: int,
        owner: str,
        repo: str,
        event: NormalizedEvent,
    ) -> ActionResult:
        if not event.pull_request:
            return ActionResult(
                success=False,
                action_type="create_pr_comment",
                error="No pull request in event",
            )

        existing = self.write_client.find_existing_pr_comment(
            installation_id, owner, repo, event.pull_request.number,
            marker=proposal.marker or "reporelay-readiness"
        )
        if existing:
            updated = self.write_client.update_pr_comment(
                installation_id, owner, repo, event.pull_request.number,
                existing.id, proposal.body or ""
            )
            return ActionResult(
                success=True,
                action_type="update_pr_comment",
                github_comment_id=updated.id,
                details={"updated": True},
            )

        comment = self.write_client.create_pr_comment(
            installation_id, owner, repo, event.pull_request.number,
            proposal.body or ""
        )
        return ActionResult(
            success=True,
            action_type="create_pr_comment",
            github_comment_id=comment.id,
            details={"created": True},
        )

    def _update_issue(
        self,
        proposal: ActionProposal,
        installation_id: int,
        owner: str,
        repo: str,
        event: NormalizedEvent,
    ) -> ActionResult:
        if not proposal.title and not proposal.body and not proposal.labels:
            return ActionResult(
                success=False,
                action_type="update_issue",
                error="No fields to update",
            )
        issue_num = proposal.__dict__.get("issue_number")
        if not issue_num:
            return ActionResult(
                success=False,
                action_type="update_issue",
                error="Missing issue_number",
            )
        updated = self.write_client.update_issue(
            installation_id, owner, repo, issue_num,
            title=proposal.title,
            body=proposal.body,
            labels=proposal.labels,
        )
        return ActionResult(
            success=True,
            action_type="update_issue",
            github_issue_number=updated.number,
        )

    def _update_pr_comment(
        self,
        proposal: ActionProposal,
        installation_id: int,
        owner: str,
        repo: str,
        event: NormalizedEvent,
    ) -> ActionResult:
        comment_id = proposal.__dict__.get("comment_id")
        pr_number = event.pull_request.number if event.pull_request else None
        if not comment_id or not pr_number:
            return ActionResult(
                success=False,
                action_type="update_pr_comment",
                error="Missing comment_id or pr_number",
            )
        updated = self.write_client.update_pr_comment(
            installation_id, owner, repo, pr_number,
            comment_id, proposal.body or ""
        )
        return ActionResult(
            success=True,
            action_type="update_pr_comment",
            github_comment_id=updated.id,
        )