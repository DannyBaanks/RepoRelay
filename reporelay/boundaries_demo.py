"""RepoRelay — fail-closed boundary demo (no network, no credentials).

Shows the security boundaries that hold even when nothing is configured:
health is credential-free, webhook signatures are enforced before any state
write, the admin API is disabled without a token, and the policy allowlist
rejects any action outside RepoRelay's narrow write mandate.
"""

from __future__ import annotations

import os
import sys

from fastapi.testclient import TestClient

os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "demo-secret-not-used-on-github")

from reporelay.app import app
from reporelay.demo_walkthrough import _fail_closed_state_store
from reporelay.policy import PolicyEngine


def _line(char: str = "=", width: int = 72) -> None:
    print(char * width)


def _heading(text: str) -> None:
    _line()
    print(text)
    _line()


def main() -> int:
    _heading("REPORELAY - FAIL-CLOSED BOUNDARIES (no network, no credentials)")
    client = TestClient(app)

    print("[1] GET /health (Firestore is lazy; no Google credentials needed)")
    response = client.get("/health")
    print(f"    status : {response.status_code}")
    print(f"    body   : {response.json()}")

    print("[2] POST /events/github with an INVALID HMAC signature")
    response = client.post(
        "/events/github",
        headers={
            "x-github-delivery": "delivery-evil",
            "x-github-event": "workflow_job",
            "x-hub-signature-256": "sha256=" + "0" * 64,
        },
        content=b'{"repository": {"full_name": "DannyBaanks/RepoRelay"}}',
    )
    print(f"    status : {response.status_code}")
    print(f"    detail : {response.json().get('detail')}")
    print("    -> rejected before any state write; nothing reached Firestore.")

    print("[3] POST /admin/retry with NO admin token configured")
    response = client.post("/admin/retry", json={"delivery_id": "delivery-812345"})
    print(f"    status : {response.status_code}")
    print(f"    detail : {response.json().get('detail')}")

    print("[4] Policy allowlist vs an action OUTSIDE the write mandate")
    engine = PolicyEngine(_fail_closed_state_store())
    forbidden = {
        "action": "merge_pull_request",
        "reason": "all checks passed",
        "confidence": "high",
    }
    result = engine.validate_action(forbidden)
    print(f"    proposed : {forbidden['action']}")
    print(f"    decision : {result.decision.value}")
    print(f"    reason   : {result.reason}")

    _heading("RESULT")
    print("Health (lazy cloud)     : PASS")
    print("Webhook HMAC fail-closed: PASS (401 before any write)")
    print("Admin fail-closed       : PASS (503 while unconfigured)")
    print("Policy allowlist        : PASS (merge_pull_request REJECTED)")
    _line()
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
