from datetime import datetime
from unittest.mock import Mock, patch

from google.cloud.exceptions import Conflict

from reporelay.config import Config
from reporelay.events import (
    EventType,
    normalize_event,
    normalized_event_from_dict,
    normalized_event_to_dict,
)
from reporelay.state import EventState, StateStore


def test_config_defaults_to_hackathon_eligible_gemini(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    cfg = Config.from_env()
    assert cfg.gemini_model == "gemini-3.5-flash"
    assert cfg.admin_token == ""


def test_normalized_event_retry_roundtrip_excludes_raw_payload(sample_pr_payload):
    original = normalize_event("delivery-1", "pull_request", sample_pr_payload)
    wire = normalized_event_to_dict(original)
    assert "raw_payload" not in wire
    restored = normalized_event_from_dict(wire)
    assert restored.delivery_id == original.delivery_id
    assert restored.event_type == EventType.PULL_REQUEST
    assert restored.repository == original.repository
    assert restored.pull_request == original.pull_request
    assert restored.raw_payload is None


def test_create_received_once_uses_firestore_create():
    store = StateStore("proj", "(default)")
    doc = Mock()
    store._collection = Mock()
    store._collection.document.return_value = doc
    _, created = store.create_received_once(
        "delivery-atomic", "check_run", "o/r", "payload-hash"
    )
    assert created is True
    doc.create.assert_called_once()
    doc.set.assert_not_called()


def test_duplicate_atomic_claim_returns_existing():
    store = StateStore("proj", "(default)")
    doc = Mock()
    doc.create.side_effect = Conflict("exists")
    store._collection = Mock()
    store._collection.document.return_value = doc
    existing = Mock()
    existing.exists = True
    existing.to_dict.return_value = {
        "delivery_id": "delivery-atomic",
        "event_type": "check_run",
        "repository": "o/r",
        "state": "action_executed",
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
        "payload_hash": "payload-hash",
        "retryable": "no",
        "retry_count": 0,
    }
    doc.get.return_value = existing
    record, created = store.create_received_once(
        "delivery-atomic", "check_run", "o/r", "payload-hash"
    )
    assert created is False
    assert record.state == EventState.ACTION_EXECUTED


def test_state_store_is_lazy_about_firestore_credentials():
    with patch("reporelay.state.firestore.Client") as client:
        store = StateStore("proj", "(default)")
        client.assert_not_called()
        _ = store.client
        client.assert_called_once_with(project="proj", database="(default)")
