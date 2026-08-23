import secrets
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .agent import RepoRelayAgent
from .config import get_config
from .events import EventType, NormalizedEvent, normalized_event_from_dict
from .evidence import EvidenceGatherer
from .executor import ActionExecutor
from .policy import PolicyEngine
from .state import Retryable, StateStore
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


def require_admin_token(x_reporelay_admin_token: str | None = Header(None)) -> None:
    """Fail closed: admin API is disabled unless ADMIN_TOKEN is configured."""
    if not config.admin_token:
        raise HTTPException(status_code=503, detail="Admin API is disabled")
    if not x_reporelay_admin_token or not secrets.compare_digest(
        x_reporelay_admin_token, config.admin_token
    ):
        raise HTTPException(status_code=401, detail="Invalid admin token")


async def handle_ci_event(
    delivery_id: str,
    event: NormalizedEvent,
    installation_id: int,
    owner: str,
    repo: str,
):
    state_store.mark_investigating(delivery_id)
    evidence = evidence_gatherer.gather_ci_evidence(installation_id, owner, repo, event)
    proposal = await agent.investigate_ci_failure(
        event, evidence, installation_id, owner, repo
    )
    if proposal.action == "error":
        state_store.mark_failed(
            delivery_id, proposal.reason or "Agent error", Retryable.YES
        )
        return
    state_store.mark_action_proposed(delivery_id, proposal.action)
    result = executor.execute(proposal, installation_id, owner, repo, event)
    if result.success:
        state_store.mark_action_executed(
            delivery_id,
            {"action": result.action_type, "details": result.details},
            github_issue_number=result.github_issue_number,
        )
    else:
        retryable = (
            Retryable.YES if "network" in (result.error or "").lower() else Retryable.NO
        )
        state_store.mark_failed(
            delivery_id, result.error or "Execution failed", retryable
        )


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
    proposal = await agent.investigate_pr_readiness(
        event, evidence, installation_id, owner, repo
    )
    if proposal.action == "error":
        state_store.mark_failed(
            delivery_id, proposal.reason or "Agent error", Retryable.YES
        )
        return
    state_store.mark_action_proposed(delivery_id, proposal.action)
    result = executor.execute(proposal, installation_id, owner, repo, event)
    if result.success:
        state_store.mark_action_executed(
            delivery_id,
            {"action": result.action_type, "details": result.details},
            github_comment_id=result.github_comment_id,
        )
    else:
        retryable = (
            Retryable.YES if "network" in (result.error or "").lower() else Retryable.NO
        )
        state_store.mark_failed(
            delivery_id, result.error or "Execution failed", retryable
        )


async def dispatch_event(
    delivery_id: str, event: NormalizedEvent, installation_id: int
) -> None:
    """Dispatch one normalized event and guarantee a terminal failure on exceptions."""
    owner = event.repository.owner
    repo = event.repository.name
    try:
        if event.event_type in (EventType.WORKFLOW_JOB, EventType.CHECK_RUN):
            await handle_ci_event(delivery_id, event, installation_id, owner, repo)
        elif event.event_type == EventType.PULL_REQUEST:
            await handle_pr_event(delivery_id, event, installation_id, owner, repo)
        else:
            state_store.mark_needs_human(
                delivery_id, f"Event type not handled: {event.event_type.value}"
            )
    except Exception as exc:
        state_store.mark_failed(
            delivery_id,
            f"Background processing failed: {type(exc).__name__}: {exc}",
            Retryable.YES,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    yield


app = FastAPI(title="RepoRelay", lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "reporelay",
        "model": config.gemini_model,
    }


@app.post("/events/github")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    result = await process_webhook(request)
    if result.get("status") != "accepted":
        return JSONResponse(content=result, status_code=200)

    delivery_id = result["delivery_id"]
    normalized = result["normalized_event"]
    installation_id = result["installation_id"]
    background_tasks.add_task(
        dispatch_event, delivery_id, normalized, installation_id
    )
    return JSONResponse(content={"status": "processing", "delivery_id": delivery_id})


class RetryRequest(BaseModel):
    delivery_id: str


@app.post("/admin/retry")
async def retry_event(
    req: RetryRequest,
    background_tasks: BackgroundTasks,
    x_reporelay_admin_token: str | None = Header(None),
):
    require_admin_token(x_reporelay_admin_token)
    record, reason = state_store.claim_retry(req.delivery_id, config.max_retries)
    if reason == "not_found":
        return JSONResponse(content={"error": "Not found"}, status_code=404)
    if reason == "max_retries":
        return JSONResponse(content={"error": "Max retries exceeded"}, status_code=409)
    if reason == "missing_retry_context":
        return JSONResponse(
            content={"error": "No durable retry context stored"}, status_code=409
        )
    if reason:
        return JSONResponse(content={"error": "Not retryable"}, status_code=409)
    if not record or not record.retry_context:
        return JSONResponse(content={"error": "Retry claim failed"}, status_code=409)

    try:
        event = normalized_event_from_dict(record.retry_context["event"])
        installation_id = int(record.retry_context["installation_id"])
    except (KeyError, TypeError, ValueError) as exc:
        state_store.mark_needs_human(
            req.delivery_id, f"Invalid retry context: {type(exc).__name__}: {exc}"
        )
        return JSONResponse(content={"error": "Invalid retry context"}, status_code=409)

    background_tasks.add_task(
        dispatch_event, req.delivery_id, event, installation_id
    )
    return {"status": "queued_for_retry", "delivery_id": req.delivery_id}


@app.get("/admin/events/{delivery_id}")
async def get_event(
    delivery_id: str,
    x_reporelay_admin_token: str | None = Header(None),
):
    require_admin_token(x_reporelay_admin_token)
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
        "has_retry_context": bool(record.retry_context),
    }
