# RepoRelay — Hackathon Provenance

## Event

- **Hackathon:** All Things Agentic Hackathon
- **Category target:** Taskmaster
- **Deadline:** August 31, 2026 at 5:00 PM Pacific Time
- **Repository:** `DannyBaanks/RepoRelay`

## Creation evidence

Repository history observed for this project begins on August 22, 2026, during the submission period. This document records the project history and current stack; it is not a substitute for the official rules or for Devpost's eligibility determination.

No private ISyCo implementation is required by RepoRelay and no private local filesystem path is part of the public provenance record.

## Submission stack

| Component | Version / identity | Purpose |
|---|---|---|
| Gemini | `gemini-3.5-flash` | Agent reasoning model |
| Google ADK | `google-adk[gcp]==2.6.3` | Agent definition and execution |
| Cloud Run | Google Cloud | Hosted webhook/runtime |
| Firestore | Google Cloud | Event state, atomic delivery claim, retry context |
| FastAPI | ADK-compatible current range | HTTP webhook/admin surface |
| PyGithub | `2.4.0` | GitHub App API access |
| Python | 3.12 | Runtime |

The official hackathon rules require Gemini 3.5 or newer, at least one Google agent framework, and at least one Google Cloud infrastructure service. RepoRelay's intended deployed stack satisfies those three technical categories when deployed as documented.

## What was built for this project

- GitHub webhook signature verification and normalization
- Firestore event state machine
- atomic GitHub delivery claiming
- bounded evidence collection
- Google ADK agent integration
- deterministic policy allowlist
- GitHub issue/comment executor
- protected admin inspection/retry path
- Cloud Run container/deployment path
- tests and documentation

## AI coding assistance disclosure

AI coding assistants were used for scaffolding, code generation, review, tests, and documentation. Generated material was incorporated into the repository as project work during the hackathon period. The public repository history remains the primary auditable timeline.

## Verification commands

```bash
git log --oneline --all
git status --short
pytest tests/ -v
ruff check reporelay tests
docker build -t reporelay:local .
```

For submission evidence, also capture the running Cloud Run service and relevant Google Cloud console/log view in the demo video as required by the event rules.

## Explicit boundaries

This provenance file does not claim:

- that every third-party service call is exactly-once,
- that FastAPI BackgroundTasks form a durable queue,
- that Gemini diagnoses are objectively correct,
- or that a local/test configuration proves a successful Cloud deployment.

Those claims require their own evidence.

*Updated: August 22, 2026*
