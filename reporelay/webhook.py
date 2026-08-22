import hashlib
import hmac
import json

from fastapi import Header, HTTPException, Request

from .config import get_config
from .events import normalize_event
from .state import EventState, StateStore


async def verify_signature(request: Request, x_hub_signature_256: str | None = Header(None)) -> bytes:
    config = get_config()
    if not config.github_webhook_secret:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    body = await request.body()
    expected = "sha256=" + hmac.new(
        config.github_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()

    if not x_hub_signature_256 or not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    return body


async def process_webhook(
    request: Request,
    x_github_delivery: str = Header(...),
    x_github_event: str = Header(...),
    x_hub_signature_256: str | None = Header(None),
) -> dict:
    config = get_config()
    state_store = StateStore(config.google_cloud_project, config.firestore_database)

    body = await verify_signature(request, x_hub_signature_256)
    payload = json.loads(body)

    existing = state_store.get(x_github_delivery)
    if existing:
        if existing.state in (EventState.ACTION_EXECUTED, EventState.NEEDS_HUMAN):
            return {"status": "duplicate", "state": existing.state.value}
        if existing.state == EventState.INVESTIGATING:
            return {"status": "in_progress"}

    payload_hash = hashlib.sha256(body).hexdigest()
    repo_full_name = payload["repository"]["full_name"]

    if config.allowed_repositories and repo_full_name not in config.allowed_repositories:
        state_store.create_received(
            x_github_delivery, x_github_event, repo_full_name, payload_hash
        )
        state_store.mark_needs_human(x_github_delivery, f"Repository not allowed: {repo_full_name}")
        return {"status": "rejected", "reason": "repository_not_allowed"}

    try:
        normalized = normalize_event(x_github_delivery, x_github_event, payload)
    except ValueError as e:
        state_store.create_received(
            x_github_delivery, x_github_event, repo_full_name, payload_hash
        )
        state_store.mark_needs_human(x_github_delivery, f"Unsupported event: {e}")
        return {"status": "rejected", "reason": str(e)}

    record = state_store.create_received(
        x_github_delivery, x_github_event, repo_full_name, payload_hash
    )

    return {
        "status": "accepted",
        "delivery_id": x_github_delivery,
        "event_type": normalized.event_type.value,
        "repository": repo_full_name,
    }