# RepoRelay

Autonomous GitHub maintenance that reacts to repository events, investigates what happened, and completes safe follow-up work without waiting for a human prompt.

## Overview

RepoRelay is an event-driven autonomous agent that:
1. Receives GitHub webhooks (CI failures, PR events)
2. Investigates using Gemini 3.5+ via Google ADK
3. Takes safe, permission-scoped actions (create issues, post PR comments)
4. Persists state with idempotency guarantees in Firestore

## Architecture

```
GitHub Webhook → Cloud Run → Verify Signature → Normalize Event
                                                    ↓
                                            Firestore Idempotency
                                                    ↓
                                            Google ADK + Gemini
                                                    ↓
                                            Typed Action Proposal
                                                    ↓
                                            Policy Allowlist Validation
                                                    ↓
                                            GitHub API (Issue/Comment)
                                                    ↓
                                            Persist Outcome + Proof
```

## Workflows

### A. Failed CI Triage
- Trigger: `workflow_job` or `check_run` with conclusion=failure
- Action: Creates/updates a GitHub issue with:
  - Repository and commit SHA
  - Failing workflow/job
  - Evidence links
  - Root-cause hypothesis
  - Confidence level
  - Next actions

### B. PR Readiness Follow-up
- Trigger: `pull_request` opened or synchronized
- Action: Creates/updates a PR comment with:
  - Current readiness state (READY/NEEDS_WORK/BLOCKED)
  - Failed checks
  - Missing tests/docs detection
  - Concrete checklist
  - Links back to evidence

## Safety Boundaries

RepoRelay MAY:
- Read repository metadata, commits, diffs, CI data, bounded logs
- Create/update dedicated triage issues with `reporelay-triage` label
- Create/update PR comments with `reporelay-readiness` marker
- Apply dedicated RepoRelay labels
- Persist workflow state

RepoRelay MUST NOT (v1):
- Merge PRs, push code, force-push
- Change branch protection or repo settings
- Publish releases, delete branches/issues
- Rotate credentials

## Quick Start

### Prerequisites
- Python 3.12+
- Google Cloud Project with Firestore enabled
- GitHub App with appropriate permissions
- Gemini API access (Vertex AI or Gemini API)

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your credentials

# Run locally
uvicorn reporelay.app:app --reload --port 8080
```

### Deploy to Cloud Run

```bash
# Build and deploy
gcloud run deploy reporelay \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars="GITHUB_APP_ID=...,GITHUB_WEBHOOK_SECRET=...,GOOGLE_CLOUD_PROJECT=...,FIRESTORE_DATABASE=(default),GEMINI_MODEL=gemini-1.5-flash"
```

### Configure GitHub Webhook

1. Create a GitHub App with permissions:
   - Checks: Read & Write
   - Issues: Read & Write
   - Pull requests: Read & Write
   - Contents: Read
   - Metadata: Read
2. Set webhook URL to `https://your-cloud-run-url/events/github`
3. Subscribe to events: `check_run`, `workflow_job`, `pull_request`
4. Install the app on target repositories

## Testing

```bash
# Run unit tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=reporelay --cov-report=html
```

## Project Structure

```
reporelay/
├── app.py              # FastAPI application entry point
├── config.py           # Configuration management
├── webhook.py          # Webhook verification & routing
├── events.py           # Event normalization & types
├── state.py            # Firestore state management
├── policy.py           # Deterministic policy engine
├── evidence.py         # Evidence gathering from GitHub
├── agent.py            # Google ADK + Gemini agent
├── actions.py          # Action definitions
├── executor.py         # Action execution with validation
└── tools/
    ├── github_read.py  # GitHub read operations
    └── github_write.py # GitHub write operations
```

## Idempotency

- Uses GitHub delivery ID as primary idempotency key
- Same webhook delivered twice → one logical GitHub action
- States: `received` → `investigating` → `action_proposed` → `action_executed` | `failed` | `needs_human`
- Bounded exponential backoff on failures
- Never duplicates issues/comments

## Hackathon Compliance

- ✅ New project created during submission period
- ✅ Uses Gemini 3.5+ (gemini-1.5-flash)
- ✅ Uses Google ADK
- ✅ Uses Cloud Run
- ✅ Uses Firestore
- ✅ Event-driven autonomous workflow
- ✅ Safe authority boundary enforced
- ✅ Idempotent, observable, retryable
- ✅ Provenance documentation in `docs/HACKATHON_PROVENANCE.md`

## License

MIT