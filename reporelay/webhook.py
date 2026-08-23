import hashlib
import hmac
import json

from fastapi import Header, HTTPException, Request

from .config import get_config
from .events import normalize_event, normalized_event_to_dict
from .state import EventState, StateStore


async def verify_signature(
    request: Request, x_hub_signature_256: str | None = Header(None)
) -> bytes:
    config = get_config()
    if not config.github_webhook_secret:
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    body = await request.body()
    expected = "sha256=" + hmac.new(
        config.github_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()

    if not x_hub_signature_256 or not hmac.compare_digest(
        expected, x_hub_signature_256
    ):
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
    payload_hash = hashlib.sha256(body).hexdigest()
    repo_full_name = payload["repository"]["full_name"]

    record, created = state_store.create_received_once(
        x_github_delivery, x_github_event, repo_full_name, payload_hash
    )
    if not created:
        if record.state == EventState.INVESTIGATING:
            return {"status": "in_progress", "state": record.state.value}
        return {"status": "duplicate", "state": record.state.value}

    if config.allowed_repositories and repo_full_name not in config.allowed_repositories:
        state_store.mark_needs_human(
            x_github_delivery, f"Repository not allowed: {repo_full_name}"
        )
        return {"status": "rejected", "reason": "repository_not_allowed"}

    try:
        normalized = normalize_event(x_github_delivery, x_github_event, payload)
    except (KeyError, TypeError, ValueError) as exc:
        state_store.mark_needs_human(
            x_github_delivery, f"Unsupported or malformed event: {exc}"
        )
        return {"status": "rejected", "reason": "unsupported_or_malformed_event"}

    installation_id = payload.get("installation", {}).get("id", 0)
    if not installation_id:
        state_store.mark_needs_human(x_github_delivery, "Missing GitHub App installation ID")
        return {"status": "rejected", "reason": "no_installation"}

    state_store.set_retry_context(
        x_github_delivery,
        {
            "installation_id": installation_id,
            "event": normalized_event_to_dict(normalized),
        },
    )

    return {
        "status": "accepted",
        "delivery_id": x_github_delivery,
        "event_type": normalized.event_type.value,
        "repository": repo_full_name,
        "installation_id": installation_id,
        "normalized_event": normalized,
    }
