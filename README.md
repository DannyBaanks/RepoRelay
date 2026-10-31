# RepoRelay

**Autonomous GitHub maintenance with a narrow authority boundary.**

RepoRelay receives signed GitHub webhooks, normalizes repository events, gathers bounded evidence, asks a Gemini-powered Google ADK agent for one typed maintenance proposal, validates that proposal against deterministic policy, and can create/update only dedicated triage issues or PR comments.

## What it does

1. Receives `workflow_job`, `check_run`, and `pull_request` webhooks.
2. Atomically claims each GitHub delivery ID in Firestore.
3. Stores a minimal normalized retry context — not the complete webhook body.
4. Investigates with **Gemini 3.5 Flash** through **Google ADK**.
5. Re-validates the proposed action through a deterministic allowlist.
6. Writes only RepoRelay-owned issues/comments through the GitHub App.
7. Persists terminal state, evidence references, action result, and retry count.

## Architecture

```text
GitHub App webhook
      │
      ▼
Cloud Run /events/github   (public endpoint, HMAC verified)
      │
      ├─ SHA-256 payload identity
      ├─ Firestore create-if-absent delivery claim
      └─ normalized minimal retry context
      ▼
Background dispatcher
      │
      ├─ bounded GitHub evidence reads
      ├─ Google ADK → Gemini 3.5 Flash
      ├─ typed ActionProposal
      └─ deterministic PolicyEngine validation
      ▼
GitHub issue / PR comment
      │
      ▼
Firestore terminal state

/admin/*  ── X-RepoRelay-Admin-Token required
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the detailed flow and operational boundaries.

## Authority boundary

RepoRelay **may** read repository metadata/CI evidence and create or update dedicated `reporelay-triage` issues and `reporelay-readiness` comments.

RepoRelay **does not** merge PRs, push code, force-push, change repository settings, publish releases, delete branches/issues, or rotate credentials. The model does not directly hold a GitHub write tool; every proposed write is re-validated before execution.

## Reliability properties

- **Atomic delivery claim:** Firestore `DocumentReference.create()` makes the GitHub delivery ID a create-if-absent idempotency key. Concurrent redeliveries cannot both create the same event record.
- **Minimal durable retry context:** the normalized event plus GitHub App installation ID are persisted; the full webhook payload is intentionally excluded.
- **Real retry:** `POST /admin/retry` atomically claims an eligible failed event and schedules the original normalized event again.
- **Fail-closed admin API:** `/admin/*` returns unavailable unless `ADMIN_TOKEN` is configured and rejects invalid tokens.
- **Terminal failure handling:** unexpected background exceptions are recorded as `failed` instead of leaving events stuck in `investigating`.
- **Action-level dedupe:** issue/comment writers look for RepoRelay-owned markers before creating a new artifact. This is a second defensive layer, not a substitute for the atomic delivery claim.

### Current operational boundary

The demo dispatcher uses FastAPI/Starlette `BackgroundTasks`. This is adequate for the hackathon workflow and keeps webhook acknowledgement fast, but it is **not a durable queue**. A production deployment that needs crash-safe asynchronous execution should move dispatch to Cloud Tasks, Pub/Sub, or an equivalent durable runner. RepoRelay does not claim otherwise.

## Hackathon stack

The official All Things Agentic requirements mandate Gemini 3.5 or newer, a Google agent framework, and Google Cloud infrastructure. RepoRelay uses:

- Gemini: `gemini-3.5-flash`
- Agent framework: Google ADK 2.x (`google-adk[gcp]==2.6.3` in this snapshot)
- Cloud: Cloud Run + Firestore
- GitHub integration: GitHub App / PyGithub
- Runtime: Python 3.12

## Local setup

### Prerequisites

- Python 3.12
- Google Cloud project with Firestore enabled
- GitHub App with webhook secret and private key
- Gemini access through Vertex AI or the Gemini API

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

For local development, load the variables in `.env` through your shell/tooling and run:

```bash
uvicorn reporelay.app:app --reload --port 8080
```

Health check:

```bash
curl http://localhost:8080/health
```

## Cloud Run deployment

The webhook endpoint must be reachable by GitHub, so the service may be deployed with unauthenticated ingress. **That does not make the admin API public:** `/admin/*` separately requires `X-RepoRelay-Admin-Token`.

Prefer Secret Manager for the GitHub private key, webhook secret, and admin token. A minimal deployment shape is:

```bash
gcloud run deploy reporelay \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=YOUR_PROJECT,FIRESTORE_DATABASE=(default),GEMINI_MODEL=gemini-3.5-flash,GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_LOCATION=global"
```

Then bind secrets through Cloud Run / Secret Manager rather than placing them literally in shell history.

## GitHub App

Recommended permissions for the demonstrated v1 workflow:

- Checks: Read
- Actions: Read
- Contents: Read
- Metadata: Read
- Issues: Read & Write
- Pull requests: Read & Write

Subscribe to `check_run`, `workflow_job`, and `pull_request`, and point the webhook to:

```text
https://YOUR-CLOUD-RUN-URL/events/github
```

## Admin retry

```bash
curl -X POST https://YOUR-CLOUD-RUN-URL/admin/retry \
  -H "Content-Type: application/json" \
  -H "X-RepoRelay-Admin-Token: $ADMIN_TOKEN" \
  -d '{"delivery_id":"YOUR_GITHUB_DELIVERY_ID"}'
```

Inspect one event with the same protected header:

```bash
curl https://YOUR-CLOUD-RUN-URL/admin/events/YOUR_GITHUB_DELIVERY_ID \
  -H "X-RepoRelay-Admin-Token: $ADMIN_TOKEN"
```

## Tests

```bash
pytest tests/ -v
ruff check reporelay tests
```

CI also builds the Docker image and checks `/health`. Firestore is initialized lazily, so the health smoke test does not require Google credentials.

## Project structure

```text
reporelay/
├── app.py
├── config.py
├── webhook.py
├── events.py
├── state.py
├── policy.py
├── evidence.py
├── agent.py
├── executor.py
└── tools/
    ├── github_read.py
    └── github_write.py
```

## Evidence / claims boundary

RepoRelay demonstrates an event-driven autonomous maintenance workflow with constrained write authority, persistent state, atomic delivery claiming, and explicit retry handling. It does **not** claim exactly-once execution across every external system, a crash-safe durable queue, or that model-generated diagnoses are always correct.

See [`docs/HACKATHON_PROVENANCE.md`](docs/HACKATHON_PROVENANCE.md) for provenance and compliance evidence.

## 2026-10-31 — newly versioned files

Commit `591a15e` brings in two modules that were previously untracked:

- `reporelay/boundaries_demo.py` — authority-boundary demo.
- `reporelay/demo_walkthrough.py` — demo walkthrough.


## License

MIT
