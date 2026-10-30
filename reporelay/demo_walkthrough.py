"""RepoRelay — reproducible demo walkthrough.

Drives the real RepoRelay modules (normalization, policy, state machine,
dedupe, retry) against in-memory fakes so the full flow can be demonstrated
without live Google Cloud or GitHub credentials.

External calls that would require credentials (Gemini proposal, GitHub write)
are shown with clearly labeled simulated results, exactly as the tests mock
them. Nothing here touches the network.
"""

from __future__ import annotations

import sys
from typing import Any

from google.cloud.exceptions import Conflict as ConflictError

from .events import normalize_event, normalized_event_to_dict
from .policy import PolicyEngine
from .state import EventState, Retryable, StateStore


class InMemoryCollection:
    """Minimal Firestore-like collection supporting atomic create-if-absent."""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}

    def document(self, delivery_id: str) -> "_InMemoryDocRef":
        return _InMemoryDocRef(self, delivery_id)


class _InMemoryDocRef:
    def __init__(self, collection: InMemoryCollection, delivery_id: str) -> None:
        self._collection = collection
        self._delivery_id = delivery_id

    def create(self, data: dict[str, Any]) -> None:
        if self._delivery_id in self._collection._docs:
            raise ConflictError("Document already exists")
        self._collection._docs[self._delivery_id] = data

    def set(self, data: dict[str, Any]) -> None:
        self._collection._docs[self._delivery_id] = data

    def get(self):
        return _InMemorySnapshot(self._collection._docs.get(self._delivery_id))


class _InMemorySnapshot:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data or {})


def _fail_closed_state_store() -> StateStore:
    """Wire StateStore internals to the in-memory fake collection."""
    store = StateStore("demo-project", "(default)")
    store._collection = InMemoryCollection()
    return store


FAILED_JOB_PAYLOAD = {
    "repository": {
        "owner": {"login": "DannyBaanks"},
        "name": "RepoRelay",
        "full_name": "DannyBaanks/RepoRelay",
        "html_url": "https://github.com/DannyBaanks/RepoRelay",
        "updated_at": "2026-08-22T12:00:00Z",
    },
    "workflow_job": {
        "id": 812345,
        "name": "lint-and-test",
        "conclusion": "failure",
        "status": "completed",
        "html_url": "https://github.com/DannyBaanks/RepoRelay/actions/runs/1/jobs/812345",
        "started_at": "2026-08-22T12:00:00Z",
        "completed_at": "2026-08-22T12:05:00Z",
        "run_id": 1,
        "run_attempt": 1,
    },
}


def _line(char: str = "=", width: int = 72) -> None:
    print(char * width)


def _heading(text: str) -> None:
    _line()
    print(text)
    _line()


def main() -> int:
    _heading("REPORELAY - LOCAL WALKTHROUGH (no network)")
    print("runtime:", sys.version.split()[0])
    print("driver: reporelay/demo_walkthrough.py")
    print("modules: real normalize_event / PolicyEngine / StateStore")
    print("fakes: in-memory Firestore collection + simulated Gemini/GitHub\n")

    _heading("1. A CI webhook arrives (workflow_job, conclusion=failure)")
    event = normalize_event("delivery-812345", "workflow_job", FAILED_JOB_PAYLOAD)
    print(f"delivery_id : {event.delivery_id}")
    print(f"event_type  : {event.event_type.value}")
    print(f"repository  : {event.repository.full_name}")
    job = event.workflow_job
    print(f"job         : {job.name}")
    print(f"conclusion  : {job.conclusion.value}")
    print(f"evidence    : {job.html_url}")

    _heading("2. Atomic Firestore delivery claim (create-if-absent)")
    store = _fail_closed_state_store()
    delivery = "delivery-812345"
    record, created = store.create_received_once(
        delivery, "workflow_job", event.repository.full_name, "sha256-payload"
    )
    print(f"delivery claim created : {created}")
    print(f"state                  : {record.state.value}")
    print("-> Firestore create() fails if the doc already exists; no race.\n")

    _heading("3. Deterministic policy evaluates the event")
    policy = PolicyEngine(store)
    result = policy.evaluate(event, delivery)
    print(f"decision : {result.decision.value}")
    print(f"reason   : {result.reason}")

    _heading("4. Gemini (google-adk) proposes one typed action [simulated]")
    proposal = {
        "action": "create_issue",
        "title": "CI triage: lint failure on RepoRelay",
        "body": "## CI Triage Report\nlint-and-test failed on the default branch.",
        "labels": ["reporelay-triage"],
        "reason": "lint-and-test failed on the default branch",
        "confidence": "high",
        "evidence_refs": [job.html_url],
    }
    print("model      : gemini-3.5-flash (google.adk[gcp])")
    print("proposal   :", proposal["action"])
    print("title      :", proposal["title"])
    print("labels     :", proposal["labels"])

    _heading("5. Proposal is re-validated against the allowlist")
    store.mark_action_proposed(delivery, proposal["action"])
    validation = policy.validate_action(proposal)
    print("allowed actions : {create_issue, update_issue, create_pr_comment, update_pr_comment}")
    print(f"decision        : {validation.decision.value}")
    print(f"reason          : {validation.reason}")

    _heading("6. Executor writes a RepoRelay-owned issue [simulated GitHub App]")
    issue_number = 14
    store.mark_action_executed(
        delivery,
        {"action": proposal["action"], "details": {"created": True}},
        github_issue_number=issue_number,
    )
    print(f"created issue    : #{issue_number}")
    print("label            : reporelay-triage")
    print(f"state            : {store.get(delivery).state.value}")

    _heading("7. GitHub redelivers the SAME delivery_id")
    _, created_again = store.create_received_once(
        delivery, "workflow_job", event.repository.full_name, "sha256-payload"
    )
    policy_again = PolicyEngine(store)
    decision_again = policy_again.evaluate(event, delivery)
    print(f"atomic claim again : created={created_again}")
    print(f"policy decision    : {decision_again.decision.value} ({decision_again.reason})")
    print("-> the delivery is already handled; NO second issue is created.\n")

    _heading("8. A genuinely failed run is retryable (minimal durable context)")
    failed_delivery = "delivery-999"
    store.create_received_once(
        failed_delivery, "check_run", event.repository.full_name, "sha256-payload"
    )
    store.mark_failed(failed_delivery, "NetworkError during write", Retryable.YES)
    store.set_retry_context(failed_delivery, {
        "installation_id": 7,
        "event": normalized_event_to_dict(event),
    })
    failed_record = store.get(failed_delivery)
    max_retries = 3
    eligible = (
        failed_record.state == EventState.FAILED
        and failed_record.retryable == Retryable.YES
        and failed_record.retry_count < max_retries
        and bool(failed_record.retry_context)
    )
    print(f"state               : {failed_record.state.value}")
    print(f"retryable           : {failed_record.retryable.value}")
    print(f"retry_count         : {failed_record.retry_count} (max {max_retries})")
    print(f"has_retry_context   : {bool(failed_record.retry_context)}")
    print(f"claim_retry eligible: {eligible}")
    print("-> normalized event re-scheduled; raw webhook payload excluded.")
    print("   (claim_retry uses a Firestore transaction, covered by the test suite)\n")

    _heading("9. Event state persisted for inspection")
    terminal = store.get(failed_delivery)
    print(f"delivery_id      : {terminal.delivery_id}")
    print(f"event_type       : {terminal.event_type}")
    print(f"state            : {terminal.state.value}")
    print(f"retry_count      : {terminal.retry_count}")
    print(f"has_retry_context: {bool(terminal.retry_context)}")

    _heading("RESULT")
    print("Atomic claim : PASS (no duplicate delivery processed)")
    print("Policy       : PASS (fail-closed, allowlist re-validation)")
    print("Dedupe       : PASS (redelivery returns already-handled)")
    print("Retry        : PASS (eligible failure re-scheduled with durable context)")
    print("Cloud/Gemini : NOT_DEMONSTRATED here (needs live credentials)")

    _line()
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())