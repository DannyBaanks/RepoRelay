# RepoRelay Architecture

## Goal

RepoRelay turns signed GitHub repository events into one narrow, policy-checked maintenance action: a RepoRelay triage issue or PR-readiness comment.

## Flow

```text
GitHub App
  │ signed webhook
  ▼
/events/github (Cloud Run)
  ├─ HMAC SHA-256 verification
  ├─ atomic Firestore delivery claim
  ├─ repository allowlist
  ├─ event normalization
  └─ minimal retry context
  ▼
Background dispatcher
  ├─ CI/PR evidence collector
  ├─ Google ADK InMemoryRunner
  └─ Gemini 3.5 Flash
  ▼
ActionProposal
  ▼
PolicyEngine (deterministic)
  ▼
ActionExecutor
  ├─ create/update RepoRelay issue
  └─ create/update RepoRelay PR comment
  ▼
Firestore terminal state
```

## Public vs protected HTTP surface

`POST /events/github` is designed for public Cloud Run ingress because GitHub must reach it. Authenticity is established with the GitHub webhook HMAC signature.

`GET /health` is public and does not initialize Firestore.

`POST /admin/retry` and `GET /admin/events/{delivery_id}` require `X-RepoRelay-Admin-Token`. If `ADMIN_TOKEN` is missing, the admin API is disabled rather than silently public.

## Idempotency

The GitHub `X-GitHub-Delivery` value is the Firestore document ID. RepoRelay claims it with `DocumentReference.create()`, which fails when the document already exists. This removes the previous check-then-set race where two concurrent deliveries could both pass an existence check.

This is an atomic **ingress delivery claim**. It is not a theorem of exactly-once behavior across GitHub, Gemini, Firestore, and every network boundary.

## Retry

On an accepted event RepoRelay stores only:

- the normalized event fields required by the handlers,
- the GitHub App installation ID.

It intentionally does not persist the full raw webhook solely for retry.

`/admin/retry` uses a Firestore transaction to claim an eligible failed event, reconstructs the normalized event, and schedules the same dispatcher again. Concurrent retry requests cannot both claim the same failed state.

## Agent runtime

The agent is a Google ADK `Agent` backed by `Gemini(model="gemini-3.5-flash")` and executed through `InMemoryRunner.run_async`. The model returns a typed JSON proposal. It does not directly call GitHub write tools.

The deterministic `PolicyEngine` re-validates every proposed write before `ActionExecutor` can issue it.

## State machine

```text
received
   ↓
investigating
   ↓
action_proposed
   ├─→ action_executed
   ├─→ failed
   └─→ needs_human

failed / needs_human
   └─ protected atomic retry claim → received
```

Unexpected background exceptions are converted to `failed`, preventing abandoned `investigating` records.

## Background execution boundary

The current hackathon implementation uses FastAPI `BackgroundTasks`. It is intentionally documented as a demo/runtime boundary: it keeps webhook acknowledgement fast but is not a durable external queue. For crash-safe production execution, dispatch should move to Cloud Tasks, Pub/Sub, or another durable workflow service.

## Google Cloud

- **Cloud Run:** container runtime and public webhook ingress
- **Firestore:** event state, atomic delivery claims, retry context
- **Vertex AI / Gemini API:** Gemini model access through Google ADK

The `/health` path remains usable without Firestore credentials because the Firestore client is created lazily on the first state operation.
