from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from google.cloud import firestore
from google.cloud.exceptions import Conflict


class EventState(str, Enum):
    RECEIVED = "received"
    INVESTIGATING = "investigating"
    ACTION_PROPOSED = "action_proposed"
    ACTION_EXECUTED = "action_executed"
    FAILED = "failed"
    NEEDS_HUMAN = "needs_human"


class Retryable(str, Enum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EventRecord:
    delivery_id: str
    event_type: str
    repository: str
    state: EventState
    created_at: datetime
    updated_at: datetime
    payload_hash: str
    action_taken: str | None = None
    action_result: dict[str, Any] | None = None
    error: str | None = None
    retryable: Retryable = Retryable.UNKNOWN
    retry_count: int = 0
    github_issue_number: int | None = None
    github_comment_id: int | None = None
    retry_context: dict[str, Any] | None = None


class StateStore:
    def __init__(self, project: str, database: str):
        self.project = project
        self.database = database
        self._client = None
        self._collection = None

    @property
    def client(self):
        # Lazy initialization keeps /health and container startup independent
        # from Google credentials while real event operations still fail closed.
        if self._client is None:
            self._client = firestore.Client(project=self.project, database=self.database)
        return self._client

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.client.collection("reporelay_events")
        return self._collection

    def _doc_ref(self, delivery_id: str):
        return self.collection.document(delivery_id)

    def create_received_once(
        self,
        delivery_id: str,
        event_type: str,
        repository: str,
        payload_hash: str,
    ) -> tuple[EventRecord, bool]:
        """Atomically claim a GitHub delivery ID exactly once.

        Firestore ``create`` fails if the document already exists, eliminating
        the check-then-set race that could process concurrent redeliveries twice.
        """
        now = datetime.now(timezone.utc)
        record = EventRecord(
            delivery_id=delivery_id,
            event_type=event_type,
            repository=repository,
            state=EventState.RECEIVED,
            created_at=now,
            updated_at=now,
            payload_hash=payload_hash,
        )
        doc_ref = self._doc_ref(delivery_id)
        try:
            doc_ref.create(self._to_dict(record))
            return record, True
        except Conflict:
            existing = self.get(delivery_id)
            if existing is None:
                raise RuntimeError("Delivery exists but could not be read")
            return existing, False

    def create_received(
        self, delivery_id: str, event_type: str, repository: str, payload_hash: str
    ) -> EventRecord:
        """Backward-compatible wrapper around the atomic delivery claim."""
        record, _ = self.create_received_once(
            delivery_id, event_type, repository, payload_hash
        )
        return record

    def get(self, delivery_id: str) -> EventRecord | None:
        doc = self._doc_ref(delivery_id).get()
        if not doc.exists:
            return None
        return self._from_dict(doc.to_dict())

    def update_state(self, delivery_id: str, state: EventState, **kwargs) -> EventRecord | None:
        doc_ref = self._doc_ref(delivery_id)
        doc = doc_ref.get()
        if not doc.exists:
            return None
        record = self._from_dict(doc.to_dict())
        updated = EventRecord(
            delivery_id=record.delivery_id,
            event_type=record.event_type,
            repository=record.repository,
            state=state,
            created_at=record.created_at,
            updated_at=datetime.now(timezone.utc),
            payload_hash=record.payload_hash,
            action_taken=kwargs.get("action_taken", record.action_taken),
            action_result=kwargs.get("action_result", record.action_result),
            error=kwargs.get("error", record.error),
            retryable=kwargs.get("retryable", record.retryable),
            retry_count=kwargs.get("retry_count", record.retry_count),
            github_issue_number=kwargs.get("github_issue_number", record.github_issue_number),
            github_comment_id=kwargs.get("github_comment_id", record.github_comment_id),
            retry_context=kwargs.get("retry_context", record.retry_context),
        )
        doc_ref.set(self._to_dict(updated))
        return updated

    def set_retry_context(
        self, delivery_id: str, retry_context: dict[str, Any]
    ) -> EventRecord | None:
        record = self.get(delivery_id)
        if not record:
            return None
        return self.update_state(delivery_id, record.state, retry_context=retry_context)

    def claim_retry(
        self, delivery_id: str, max_retries: int
    ) -> tuple[EventRecord | None, str | None]:
        """Atomically transition a failed event back to RECEIVED for one retry."""
        doc_ref = self._doc_ref(delivery_id)
        transaction = self.client.transaction()

        @firestore.transactional
        def _claim(txn):
            snapshot = doc_ref.get(transaction=txn)
            if not snapshot.exists:
                return None, "not_found"
            record = self._from_dict(snapshot.to_dict())
            if record.state not in (EventState.FAILED, EventState.NEEDS_HUMAN):
                return record, "not_retryable"
            if record.retry_count >= max_retries:
                return record, "max_retries"
            if not record.retry_context:
                return record, "missing_retry_context"
            updated = EventRecord(
                delivery_id=record.delivery_id,
                event_type=record.event_type,
                repository=record.repository,
                state=EventState.RECEIVED,
                created_at=record.created_at,
                updated_at=datetime.now(timezone.utc),
                payload_hash=record.payload_hash,
                action_taken=record.action_taken,
                action_result=record.action_result,
                error=None,
                retryable=Retryable.UNKNOWN,
                retry_count=record.retry_count,
                github_issue_number=record.github_issue_number,
                github_comment_id=record.github_comment_id,
                retry_context=record.retry_context,
            )
            txn.set(doc_ref, self._to_dict(updated))
            return updated, None

        return _claim(transaction)

    def mark_investigating(self, delivery_id: str) -> EventRecord | None:
        return self.update_state(delivery_id, EventState.INVESTIGATING)

    def mark_action_proposed(self, delivery_id: str, action_taken: str) -> EventRecord | None:
        return self.update_state(
            delivery_id, EventState.ACTION_PROPOSED, action_taken=action_taken
        )

    def mark_action_executed(
        self,
        delivery_id: str,
        action_result: dict[str, Any],
        github_issue_number: int | None = None,
        github_comment_id: int | None = None,
    ) -> EventRecord | None:
        return self.update_state(
            delivery_id,
            EventState.ACTION_EXECUTED,
            action_result=action_result,
            github_issue_number=github_issue_number,
            github_comment_id=github_comment_id,
            error=None,
            retryable=Retryable.NO,
        )

    def mark_failed(
        self, delivery_id: str, error: str, retryable: Retryable = Retryable.UNKNOWN
    ) -> EventRecord | None:
        record = self.get(delivery_id)
        if not record:
            return None
        new_retry_count = record.retry_count + 1
        return self.update_state(
            delivery_id,
            EventState.FAILED,
            error=error,
            retryable=retryable,
            retry_count=new_retry_count,
        )

    def mark_needs_human(self, delivery_id: str, error: str) -> EventRecord | None:
        return self.update_state(
            delivery_id, EventState.NEEDS_HUMAN, error=error, retryable=Retryable.UNKNOWN
        )

    def _to_dict(self, record: EventRecord) -> dict[str, Any]:
        return {
            "delivery_id": record.delivery_id,
            "event_type": record.event_type,
            "repository": record.repository,
            "state": record.state.value,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "payload_hash": record.payload_hash,
            "action_taken": record.action_taken,
            "action_result": record.action_result,
            "error": record.error,
            "retryable": record.retryable.value,
            "retry_count": record.retry_count,
            "github_issue_number": record.github_issue_number,
            "github_comment_id": record.github_comment_id,
            "retry_context": record.retry_context,
        }

    def _from_dict(self, data: dict[str, Any]) -> EventRecord:
        return EventRecord(
            delivery_id=data["delivery_id"],
            event_type=data["event_type"],
            repository=data["repository"],
            state=EventState(data["state"]),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            payload_hash=data["payload_hash"],
            action_taken=data.get("action_taken"),
            action_result=data.get("action_result"),
            error=data.get("error"),
            retryable=Retryable(data.get("retryable", "unknown")),
            retry_count=data.get("retry_count", 0),
            github_issue_number=data.get("github_issue_number"),
            github_comment_id=data.get("github_comment_id"),
            retry_context=data.get("retry_context"),
        )
