import pytest
import hashlib
import hmac
import json
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime

from reporelay.config import Config
from reporelay.events import (
    normalize_event,
    EventType,
    WorkflowConclusion,
    PRAction,
    Repository,
    Commit,
    WorkflowJob,
    CheckRun,
    PullRequest,
    NormalizedEvent,
)
from reporelay.state import StateStore, EventRecord, EventState, Retryable
from reporelay.policy import PolicyEngine, PolicyResult, PolicyDecision
from reporelay.evidence import CIEvidence, PREvidence
from reporelay.agent import ActionProposal
from reporelay.executor import ActionExecutor, ActionResult


class TestEventNormalization:
    def test_normalize_workflow_job_failure(self):
        payload = {
            "repository": {
                "owner": {"login": "testowner"},
                "name": "testrepo",
                "full_name": "testowner/testrepo",
                "html_url": "https://github.com/testowner/testrepo",
                "updated_at": "2026-08-22T12:00:00Z",
            },
            "workflow_job": {
                "id": 12345,
                "name": "test-job",
                "conclusion": "failure",
                "status": "completed",
                "html_url": "https://github.com/testowner/testrepo/actions/runs/1/jobs/12345",
                "started_at": "2026-08-22T12:00:00Z",
                "completed_at": "2026-08-22T12:05:00Z",
                "run_id": 1,
                "run_attempt": 1,
            },
        }
        event = normalize_event("delivery-123", "workflow_job", payload)
        assert event.event_type == EventType.WORKFLOW_JOB
        assert event.workflow_job is not None
        assert event.workflow_job.conclusion == WorkflowConclusion.FAILURE
        assert event.repository.full_name == "testowner/testrepo"

    def test_normalize_check_run_failure(self):
        payload = {
            "repository": {
                "owner": {"login": "testowner"},
                "name": "testrepo",
                "full_name": "testowner/testrepo",
                "html_url": "https://github.com/testowner/testrepo",
                "updated_at": "2026-08-22T12:00:00Z",
            },
            "check_run": {
                "id": 67890,
                "name": "lint",
                "conclusion": "failure",
                "status": "completed",
                "html_url": "https://github.com/testowner/testrepo/check-runs/67890",
                "started_at": "2026-08-22T12:00:00Z",
                "completed_at": "2026-08-22T12:02:00Z",
                "output": {"summary": "Lint failed", "text": "Error on line 10"},
            },
        }
        event = normalize_event("delivery-456", "check_run", payload)
        assert event.event_type == EventType.CHECK_RUN
        assert event.check_run is not None
        assert event.check_run.conclusion == WorkflowConclusion.FAILURE

    def test_normalize_pull_request_opened(self):
        payload = {
            "action": "opened",
            "repository": {
                "owner": {"login": "testowner"},
                "name": "testrepo",
                "full_name": "testowner/testrepo",
                "html_url": "https://github.com/testowner/testrepo",
                "updated_at": "2026-08-22T12:00:00Z",
            },
            "pull_request": {
                "number": 42,
                "title": "Add feature",
                "state": "open",
                "html_url": "https://github.com/testowner/testrepo/pull/42",
                "head": {"sha": "abc123", "ref": "feature-branch"},
                "base": {"sha": "def456", "ref": "main"},
                "user": {"login": "contributor"},
                "draft": False,
                "created_at": "2026-08-22T10:00:00Z",
                "updated_at": "2026-08-22T12:00:00Z",
            },
        }
        event = normalize_event("delivery-789", "pull_request", payload)
        assert event.event_type == EventType.PULL_REQUEST
        assert event.pull_request is not None
        assert event.pr_action == PRAction.OPENED
        assert event.pull_request.number == 42

    def test_normalize_unsupported_event_raises(self):
        payload = {"repository": {"full_name": "testowner/testrepo"}}
        with pytest.raises(ValueError):
            normalize_event("delivery-999", "unsupported_event", payload)


class TestPolicyEngine:
    @pytest.fixture
    def mock_state_store(self):
        return Mock(spec=StateStore)

    @pytest.fixture
    def policy_engine(self, mock_state_store):
        with patch("reporelay.policy.get_config") as mock_config:
            mock_config.return_value = Config(
                github_app_id="1",
                github_app_private_key="key",
                github_webhook_secret="secret",
                google_cloud_project="proj",
                firestore_database="(default)",
                gemini_model="gemini-1.5-flash",
                allowed_repositories=[],
            )
            return PolicyEngine(mock_state_store)

    def test_duplicate_delivery_noop(self, policy_engine, mock_state_store):
        mock_state_store.get.return_value = EventRecord(
            delivery_id="delivery-123",
            event_type="workflow_job",
            repository="testowner/testrepo",
            state=EventState.ACTION_EXECUTED,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            payload_hash="hash",
        )
        event = Mock()
        event.event_type = EventType.WORKFLOW_JOB
        result = policy_engine.evaluate(event, "delivery-123")
        assert result.decision == PolicyDecision.NOOP

    def test_failed_workflow_job_proceed(self, policy_engine, mock_state_store):
        mock_state_store.get.return_value = None
        event = Mock()
        event.event_type = EventType.WORKFLOW_JOB
        event.workflow_job = Mock()
        event.workflow_job.conclusion = WorkflowConclusion.FAILURE
        result = policy_engine.evaluate(event, "delivery-new")
        assert result.decision == PolicyDecision.PROCEED

    def test_successful_workflow_job_noop(self, policy_engine, mock_state_store):
        mock_state_store.get.return_value = None
        event = Mock()
        event.event_type = EventType.WORKFLOW_JOB
        event.workflow_job = Mock()
        event.workflow_job.conclusion = WorkflowConclusion.SUCCESS
        result = policy_engine.evaluate(event, "delivery-new")
        assert result.decision == PolicyDecision.NOOP

    def test_pr_opened_proceed(self, policy_engine, mock_state_store):
        mock_state_store.get.return_value = None
        event = Mock()
        event.event_type = EventType.PULL_REQUEST
        event.pr_action = PRAction.OPENED
        event.pull_request = Mock()
        event.pull_request.draft = False
        result = policy_engine.evaluate(event, "delivery-new")
        assert result.decision == PolicyDecision.PROCEED

    def test_draft_pr_noop(self, policy_engine, mock_state_store):
        mock_state_store.get.return_value = None
        event = Mock()
        event.event_type = EventType.PULL_REQUEST
        event.pr_action = PRAction.OPENED
        event.pull_request = Mock()
        event.pull_request.draft = True
        result = policy_engine.evaluate(event, "delivery-new")
        assert result.decision == PolicyDecision.NOOP

    def test_validate_create_issue_action(self, policy_engine):
        action = {
            "action": "create_issue",
            "title": "Test",
            "body": "Body",
            "labels": ["reporelay-triage"],
            "reason": "Reason",
            "confidence": "high",
            "evidence_refs": [],
        }
        result = policy_engine.validate_action(action)
        assert result.decision == PolicyDecision.PROCEED

    def test_validate_create_issue_missing_label_reject(self, policy_engine):
        action = {
            "action": "create_issue",
            "title": "Test",
            "body": "Body",
            "labels": ["other-label"],
            "reason": "Reason",
            "confidence": "high",
            "evidence_refs": [],
        }
        result = policy_engine.validate_action(action)
        assert result.decision == PolicyDecision.REJECT

    def test_validate_unknown_action_reject(self, policy_engine):
        action = {"action": "merge_pr"}
        result = policy_engine.validate_action(action)
        assert result.decision == PolicyDecision.REJECT


class TestActionProposal:
    def test_parse_valid_create_issue(self):
        json_str = json.dumps({
            "action": "create_issue",
            "title": "CI triage: test_failure on abc123",
            "body": "## CI Triage Report\n...",
            "labels": ["reporelay-triage"],
            "reason": "Test failed",
            "confidence": "high",
            "evidence_refs": ["https://github.com/.../checks/123"],
        })
        proposal = ActionProposal(**json.loads(json_str))
        assert proposal.action == "create_issue"
        assert proposal.confidence == "high"

    def test_parse_valid_create_pr_comment(self):
        json_str = json.dumps({
            "action": "create_pr_comment",
            "body": "## PR Readiness\n...",
            "reason": "PR needs work",
            "marker": "reporelay-readiness",
        })
        proposal = ActionProposal(**json.loads(json_str))
        assert proposal.action == "create_pr_comment"
        assert proposal.marker == "reporelay-readiness"


class TestWebhookSignature:
    def test_verify_valid_signature(self):
        secret = "test-secret"
        body = b'{"test": "payload"}'
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert hmac.compare_digest(expected, expected)

    def test_verify_invalid_signature(self):
        secret = "test-secret"
        body = b'{"test": "payload"}'
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        invalid = "sha256=" + "a" * 64
        assert not hmac.compare_digest(expected, invalid)


class TestIdempotency:
    @pytest.fixture
    def mock_firestore_client(self):
        with patch("reporelay.state.firestore.Client") as mock:
            yield mock

    def test_duplicate_delivery_prevents_double_action(self, mock_firestore_client):
        mock_doc = Mock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "delivery_id": "delivery-123",
            "event_type": "workflow_job",
            "repository": "testowner/testrepo",
            "state": "action_executed",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "payload_hash": "hash",
            "action_taken": "create_issue",
            "action_result": {"action": "create_issue", "details": {"created": True}},
            "error": None,
            "retryable": "no",
            "retry_count": 0,
            "github_issue_number": 1,
            "github_comment_id": None,
        }
        mock_firestore_client.return_value.collection.return_value.document.return_value.get.return_value = mock_doc

        store = StateStore("proj", "(default)")
        record = store.get("delivery-123")
        assert record is not None
        assert record.state == EventState.ACTION_EXECUTED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])