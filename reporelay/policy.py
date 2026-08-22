from dataclasses import dataclass
from enum import Enum
from typing import Optional
from .events import NormalizedEvent, EventType, WorkflowConclusion, PRAction
from .state import EventState, StateStore
from .config import get_config


class PolicyDecision(str, Enum):
    PROCEED = "proceed"
    NOOP = "noop"
    FAIL_CLOSED = "fail_closed"
    REJECT = "reject"


@dataclass(frozen=True)
class PolicyResult:
    decision: PolicyDecision
    reason: str
    retryable: bool = False


class PolicyEngine:
    def __init__(self, state_store: StateStore):
        self.state_store = state_store
        self.config = get_config()

    def evaluate(self, event: NormalizedEvent, delivery_id: str) -> PolicyResult:
        existing = self.state_store.get(delivery_id)
        if existing:
            if existing.state in (EventState.ACTION_EXECUTED, EventState.NEEDS_HUMAN):
                return PolicyResult(PolicyDecision.NOOP, "Already handled", retryable=False)
            if existing.state == EventState.INVESTIGATING:
                return PolicyResult(PolicyDecision.NOOP, "Already investigating", retryable=False)

        if event.event_type in (EventType.WORKFLOW_JOB, EventType.CHECK_RUN):
            return self._evaluate_ci_event(event)
        elif event.event_type == EventType.PULL_REQUEST:
            return self._evaluate_pr_event(event)
        elif event.event_type == EventType.PUSH:
            return PolicyResult(PolicyDecision.NOOP, "Push events not handled in v1", retryable=False)

        return PolicyResult(PolicyDecision.FAIL_CLOSED, f"Unsupported event type: {event.event_type}", retryable=False)

    def _evaluate_ci_event(self, event: NormalizedEvent) -> PolicyResult:
        if event.workflow_job:
            if event.workflow_job.conclusion == WorkflowConclusion.SUCCESS:
                return PolicyResult(PolicyDecision.NOOP, "Workflow job succeeded", retryable=False)
            if event.workflow_job.conclusion in (WorkflowConclusion.CANCELLED, WorkflowConclusion.SKIPPED):
                return PolicyResult(PolicyDecision.NOOP, f"Workflow job {event.workflow_job.conclusion.value}", retryable=False)
            if event.workflow_job.conclusion == WorkflowConclusion.FAILURE:
                return PolicyResult(PolicyDecision.PROCEED, "Workflow job failed, triage needed", retryable=False)

        if event.check_run:
            if event.check_run.conclusion == WorkflowConclusion.SUCCESS:
                return PolicyResult(PolicyDecision.NOOP, "Check run succeeded", retryable=False)
            if event.check_run.conclusion in (WorkflowConclusion.CANCELLED, WorkflowConclusion.SKIPPED):
                return PolicyResult(PolicyDecision.NOOP, f"Check run {event.check_run.conclusion.value}", retryable=False)
            if event.check_run.conclusion == WorkflowConclusion.FAILURE:
                return PolicyResult(PolicyDecision.PROCEED, "Check run failed, triage needed", retryable=False)

        return PolicyResult(PolicyDecision.NOOP, "CI event not actionable", retryable=False)

    def _evaluate_pr_event(self, event: NormalizedEvent) -> PolicyResult:
        if not event.pull_request:
            return PolicyResult(PolicyDecision.NOOP, "No PR data", retryable=False)

        if event.pr_action in (PRAction.CLOSED,):
            return PolicyResult(PolicyDecision.NOOP, "PR closed", retryable=False)

        if event.pull_request.draft:
            return PolicyResult(PolicyDecision.NOOP, "Draft PR", retryable=False)

        if event.pr_action in (PRAction.OPENED, PRAction.SYNCHRONIZE, PRAction.REOPENED):
            return PolicyResult(PolicyDecision.PROCEED, "PR readiness check needed", retryable=False)

        return PolicyResult(PolicyDecision.NOOP, f"PR action {event.pr_action.value} not handled", retryable=False)

    def validate_action(self, action: dict) -> PolicyResult:
        action_type = action.get("action")
        allowed_actions = {"create_issue", "update_issue", "create_pr_comment", "update_pr_comment"}

        if action_type not in allowed_actions:
            return PolicyResult(PolicyDecision.REJECT, f"Action not allowed: {action_type}", retryable=False)

        if action_type == "create_issue":
            required = {"title", "body", "labels", "reason", "confidence", "evidence_refs"}
            missing = required - set(action.keys())
            if missing:
                return PolicyResult(PolicyDecision.REJECT, f"Missing required fields: {missing}", retryable=False)
            if "reporelay-triage" not in action.get("labels", []):
                return PolicyResult(PolicyDecision.REJECT, "Missing required label: reporelay-triage", retryable=False)

        if action_type == "create_pr_comment":
            required = {"body", "reason", "marker"}
            missing = required - set(action.keys())
            if missing:
                return PolicyResult(PolicyDecision.REJECT, f"Missing required fields: {missing}", retryable=False)
            if "reporelay-readiness" not in action.get("marker", ""):
                return PolicyResult(PolicyDecision.REJECT, "Missing required marker", retryable=False)

        return PolicyResult(PolicyDecision.PROCEED, "Action validated")