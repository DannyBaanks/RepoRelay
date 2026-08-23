import json
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .agent import RepoRelayAgent
from .config import get_config
from .events import EventType, NormalizedEvent, normalize_event
from .evidence import EvidenceGatherer
from .executor import ActionExecutor
from .policy import PolicyEngine
from .state import EventState, Retryable, StateStore
from .tools.github_read import GitHubReadClient
from .tools.github_write import GitHubWriteClient
from .webhook import process_webhook

config = get_config()
state_store = StateStore(config.google_cloud_project, config.firestore_database)
read_client = GitHubReadClient()
write_client = GitHubWriteClient()
policy_engine = PolicyEngine(state_store)
evidence_gatherer = EvidenceGatherer(read_client)
agent = RepoRelayAgent(policy_engine)
executor = ActionExecutor(write_client, policy_engine)


def get_installation_id(payload: dict) -> int:
    return payload.get("installation", {}).get("id", 0)


async def handle_ci_event(
    delivery_id: str,
    event: NormalizedEvent,
    installation_id: int,
    owner: str,
    repo: str,
):
    state_store.mark_investigating(delivery_id)

    evidence = evidence_gatherer.gather_ci_evidence(installation_id, owner, repo, event)
    proposal = agent.investigate_ci_failure(event, evidence, installation_id, owner, repo)

    if proposal.action == "error":
        state_store.mark_failed(delivery_id, proposal.reason or "Agent error", Retryable.NO)
        return

    state_store.mark_action_proposed(delivery_id, "create_issue")

    result = executor.execute(proposal, installation_id, owner, repo, event)

    if result.success:
        state_store.mark_action_executed(
            delivery_id,
            {"action": result.action_type, "details": result.details},
            github_issue_number=result.github_issue_number,
        )
    else:
        retryable = Retryable.YES if "network" in (result.error or "").lower() else Retryable.NO
        state_store.mark_failed(delivery_id, result.error or "Execution failed", retryable)


async def handle_pr_event(
    delivery_id: str,
    event: NormalizedEvent,
    installation_id: int,
    owner: str,
    repo: str,
):
    state_store.mark_investigating(delivery_id)

    evidence = evidence_gatherer.gather_pr_evidence(installation_id, owner, repo, event)
    if not evidence:
        state_store.mark_needs_human(delivery_id, "No PR evidence gathered")
        return

    proposal = agent.investigate_pr_readiness(event, evidence, installation_id, owner, repo)

    if proposal.action == "error":
        state_store.mark_failed(delivery_id, proposal.reason or "Agent error", Retryable.NO)
        return

    state_store.mark_action_proposed(delivery_id, "create_pr_comment")

    result = executor.execute(proposal, installation_id, owner, repo, event)

    if result.success:
        state_store.mark_action_executed(
            delivery_id,
            {"action": result.action_type, "details": result.details},
            github_comment_id=result.github_comment_id,
        )
    else:
        retryable = Retryable.YES if "network" in (result.error or "").lower() else Retryable.NO
        state_store.mark_failed(delivery_id, result.error or "Execution failed", retryable)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="RepoRelay", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "reporelay"}


@app.post("/events/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    result = await process_webhook(request)
    
    if result.get("status") != "accepted":
        return JSONResponse(content=result, status_code=200)

    delivery_id = result["delivery_id"]
    event_type = result["event_type"]
    repository = result["repository"]
    owner, repo = repository.split("/", 1)

    body = await request.body()
    payload = json.loads(body)
    installation_id = get_installation_id(payload)

    if not installation_id:
        state_store.mark_failed(delivery_id, "Missing installation ID", Retryable.NO)
        return JSONResponse(content={"status": "error", "reason": "no_installation"}, status_code=200)

    try:
        normalized = normalize_event(delivery_id, event_type, payload)
    except ValueError as e:
        state_store.mark_needs_human(delivery_id, str(e))
        return JSONResponse(content={"status": "error", "reason": str(e)}, status_code=200)

    if normalized.event_type in (EventType.WORKFLOW_JOB, EventType.CHECK_RUN):
        background_tasks.add_task(handle_ci_event, delivery_id, normalized, installation_id, owner, repo)
    elif normalized.event_type == EventType.PULL_REQUEST:
        background_tasks.add_task(handle_pr_event, delivery_id, normalized, installation_id, owner, repo)
    else:
        state_store.mark_needs_human(delivery_id, f"Event type not handled: {event_type}")

    return JSONResponse(content={"status": "processing", "delivery_id": delivery_id})


class RetryRequest(BaseModel):
    delivery_id: str


@app.post("/admin/retry")
async def retry_event(req: RetryRequest):
    record = state_store.get(req.delivery_id)
    if not record:
        return JSONResponse(content={"error": "Not found"}, status_code=404)
    
    if record.state not in (EventState.FAILED, EventState.NEEDS_HUMAN):
        return JSONResponse(content={"error": "Not retryable"}, status_code=400)
    
    if record.retry_count >= config.max_retries:
        return JSONResponse(content={"error": "Max retries exceeded"}, status_code=400)

    state_store.update_state(req.delivery_id, EventState.RECEIVED, error=None)
    
    return {"status": "queued_for_retry", "delivery_id": req.delivery_id}


@app.get("/admin/events/{delivery_id}")
async def get_event(delivery_id: str):
    record = state_store.get(delivery_id)
    if not record:
        return JSONResponse(content={"error": "Not found"}, status_code=404)
    return {
        "delivery_id": record.delivery_id,
        "event_type": record.event_type,
        "repository": record.repository,
        "state": record.state.value,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "action_taken": record.action_taken,
        "action_result": record.action_result,
        "error": record.error,
        "retryable": record.retryable.value,
        "retry_count": record.retry_count,
        "github_issue_number": record.github_issue_number,
        "github_comment_id": record.github_comment_id,
    }