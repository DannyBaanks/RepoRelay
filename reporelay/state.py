from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import json
from google.cloud import firestore


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
    action_taken: Optional[str] = None
    action_result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    retryable: Retryable = Retryable.UNKNOWN
    retry_count: int = 0
    github_issue_number: Optional[int] = None
    github_comment_id: Optional[int] = None


class StateStore:
    def __init__(self, project: str, database: str):
        self.client = firestore.Client(project=project, database=database)
        self.collection = self.client.collection("reporelay_events")

    def _doc_ref(self, delivery_id: str):
        return self.collection.document(delivery_id)

    def create_received(self, delivery_id: str, event_type: str, repository: str, payload_hash: str) -> EventRecord:
        now = datetime.utcnow()
        record = EventRecord(
            delivery_id=delivery_id,
            event_type=event_type,
            repository=repository,
            state=EventState.RECEIVED,
            created_at=now,
            updated_at=now,
            payload_hash=payload_hash,
        )
        self._doc_ref(delivery_id).set(self._to_dict(record))
        return record

    def get(self, delivery_id: str) -> Optional[EventRecord]:
        doc = self._doc_ref(delivery_id).get()
        if not doc.exists:
            return None
        return self._from_dict(doc.to_dict())

    def update_state(self, delivery_id: str, state: EventState, **kwargs) -> Optional[EventRecord]:
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
            updated_at=datetime.utcnow(),
            payload_hash=record.payload_hash,
            action_taken=kwargs.get("action_taken", record.action_taken),
            action_result=kwargs.get("action_result", record.action_result),
            error=kwargs.get("error", record.error),
            retryable=kwargs.get("retryable", record.retryable),
            retry_count=kwargs.get("retry_count", record.retry_count),
            github_issue_number=kwargs.get("github_issue_number", record.github_issue_number),
            github_comment_id=kwargs.get("github_comment_id", record.github_comment_id),
        )
        doc_ref.set(self._to_dict(updated))
        return updated

    def mark_investigating(self, delivery_id: str) -> Optional[EventRecord]:
        return self.update_state(delivery_id, EventState.INVESTIGATING)

    def mark_action_proposed(self, delivery_id: str, action_taken: str) -> Optional[EventRecord]:
        return self.update_state(delivery_id, EventState.ACTION_PROPOSED, action_taken=action_taken)

    def mark_action_executed(
        self,
        delivery_id: str,
        action_result: dict[str, Any],
        github_issue_number: Optional[int] = None,
        github_comment_id: Optional[int] = None,
    ) -> Optional[EventRecord]:
        return self.update_state(
            delivery_id,
            EventState.ACTION_EXECUTED,
            action_result=action_result,
            github_issue_number=github_issue_number,
            github_comment_id=github_comment_id,
        )

    def mark_failed(
        self, delivery_id: str, error: str, retryable: Retryable = Retryable.UNKNOWN
    ) -> Optional[EventRecord]:
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

    def mark_needs_human(self, delivery_id: str, error: str) -> Optional[EventRecord]:
        return self.update_state(delivery_id, EventState.NEEDS_HUMAN, error=error)

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
        )