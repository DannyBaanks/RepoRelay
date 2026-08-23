from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    WORKFLOW_JOB = "workflow_job"
    CHECK_RUN = "check_run"
    PULL_REQUEST = "pull_request"
    PUSH = "push"


class WorkflowConclusion(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    ACTION_REQUIRED = "action_required"


class PRAction(str, Enum):
    OPENED = "opened"
    SYNCHRONIZE = "synchronize"
    REOPENED = "reopened"
    CLOSED = "closed"


@dataclass(frozen=True)
class Repository:
    owner: str
    name: str
    full_name: str
    html_url: str

    @classmethod
    def from_github(cls, data: dict[str, Any]) -> "Repository":
        return cls(
            owner=data["owner"]["login"],
            name=data["name"],
            full_name=data["full_name"],
            html_url=data["html_url"],
        )


@dataclass(frozen=True)
class Commit:
    sha: str
    message: str
    author_login: str
    authored_at: datetime
    html_url: str

    @classmethod
    def from_github(cls, data: dict[str, Any]) -> "Commit":
        return cls(
            sha=data["sha"],
            message=data["commit"]["message"],
            author_login=data["author"]["login"] if data.get("author") else "unknown",
            authored_at=datetime.fromisoformat(
                data["commit"]["author"]["date"].replace("Z", "+00:00")
            ),
            html_url=data["html_url"],
        )


@dataclass(frozen=True)
class WorkflowJob:
    id: int
    name: str
    conclusion: WorkflowConclusion | None
    status: str
    html_url: str
    started_at: datetime | None
    completed_at: datetime | None
    run_id: int
    run_attempt: int

    @classmethod
    def from_github(cls, data: dict[str, Any]) -> "WorkflowJob":
        conclusion = data.get("conclusion")
        return cls(
            id=data["id"],
            name=data["name"],
            conclusion=WorkflowConclusion(conclusion) if conclusion else None,
            status=data["status"],
            html_url=data["html_url"],
            started_at=datetime.fromisoformat(data["started_at"].replace("Z", "+00:00"))
            if data.get("started_at")
            else None,
            completed_at=datetime.fromisoformat(data["completed_at"].replace("Z", "+00:00"))
            if data.get("completed_at")
            else None,
            run_id=data["run_id"],
            run_attempt=data["run_attempt"],
        )


@dataclass(frozen=True)
class CheckRun:
    id: int
    name: str
    conclusion: WorkflowConclusion | None
    status: str
    html_url: str
    started_at: datetime | None
    completed_at: datetime | None
    output: dict[str, Any] | None

    @classmethod
    def from_github(cls, data: dict[str, Any]) -> "CheckRun":
        conclusion = data.get("conclusion")
        return cls(
            id=data["id"],
            name=data["name"],
            conclusion=WorkflowConclusion(conclusion) if conclusion else None,
            status=data["status"],
            html_url=data["html_url"],
            started_at=datetime.fromisoformat(data["started_at"].replace("Z", "+00:00"))
            if data.get("started_at")
            else None,
            completed_at=datetime.fromisoformat(data["completed_at"].replace("Z", "+00:00"))
            if data.get("completed_at")
            else None,
            output=data.get("output"),
        )


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    state: str
    html_url: str
    head_sha: str
    base_sha: str
    head_ref: str
    base_ref: str
    user_login: str
    draft: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_github(cls, data: dict[str, Any]) -> "PullRequest":
        return cls(
            number=data["number"],
            title=data["title"],
            state=data["state"],
            html_url=data["html_url"],
            head_sha=data["head"]["sha"],
            base_sha=data["base"]["sha"],
            head_ref=data["head"]["ref"],
            base_ref=data["base"]["ref"],
            user_login=data["user"]["login"],
            draft=data.get("draft", False),
            created_at=datetime.fromisoformat(
                data["created_at"].replace("Z", "+00:00")
            ),
            updated_at=datetime.fromisoformat(
                data["updated_at"].replace("Z", "+00:00")
            ),
        )


@dataclass(frozen=True)
class NormalizedEvent:
    delivery_id: str
    event_type: EventType
    repository: Repository
    timestamp: datetime
    workflow_job: WorkflowJob | None = None
    check_run: CheckRun | None = None
    pull_request: PullRequest | None = None
    pr_action: PRAction | None = None
    commit: Commit | None = None
    raw_payload: dict[str, Any] = None


def normalize_event(
    delivery_id: str, event_name: str, payload: dict[str, Any]
) -> NormalizedEvent:
    timestamp = datetime.fromisoformat(
        payload.get("repository", {}).get("updated_at", datetime.now(timezone.utc).isoformat()).replace("Z", "+00:00")
    )
    repository = Repository.from_github(payload["repository"])

    if event_name == "workflow_job":
        job = WorkflowJob.from_github(payload["workflow_job"])
        return NormalizedEvent(
            delivery_id=delivery_id,
            event_type=EventType.WORKFLOW_JOB,
            repository=repository,
            timestamp=timestamp,
            workflow_job=job,
            raw_payload=payload,
        )

    if event_name == "check_run":
        check = CheckRun.from_github(payload["check_run"])
        return NormalizedEvent(
            delivery_id=delivery_id,
            event_type=EventType.CHECK_RUN,
            repository=repository,
            timestamp=timestamp,
            check_run=check,
            raw_payload=payload,
        )

    if event_name == "pull_request":
        pr = PullRequest.from_github(payload["pull_request"])
        action = PRAction(payload["action"])
        return NormalizedEvent(
            delivery_id=delivery_id,
            event_type=EventType.PULL_REQUEST,
            repository=repository,
            timestamp=timestamp,
            pull_request=pr,
            pr_action=action,
            raw_payload=payload,
        )

    if event_name == "push":
        commit_data = payload.get("head_commit") or payload.get("commits", [{}])[0]
        commit = Commit.from_github(commit_data) if commit_data.get("sha") else None
        return NormalizedEvent(
            delivery_id=delivery_id,
            event_type=EventType.PUSH,
            repository=repository,
            timestamp=timestamp,
            commit=commit,
            raw_payload=payload,
        )

    raise ValueError(f"Unsupported event type: {event_name}")

def _dt_to_wire(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt_from_wire(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def normalized_event_to_dict(event: NormalizedEvent) -> dict[str, Any]:
    """Serialize only the normalized fields required for deterministic retry.

    The original webhook payload is intentionally excluded to minimize retained
    GitHub data and Firestore document size.
    """
    data: dict[str, Any] = {
        "delivery_id": event.delivery_id,
        "event_type": event.event_type.value,
        "repository": {
            "owner": event.repository.owner,
            "name": event.repository.name,
            "full_name": event.repository.full_name,
            "html_url": event.repository.html_url,
        },
        "timestamp": event.timestamp.isoformat(),
        "pr_action": event.pr_action.value if event.pr_action else None,
    }
    if event.workflow_job:
        job = event.workflow_job
        data["workflow_job"] = {
            "id": job.id,
            "name": job.name,
            "conclusion": job.conclusion.value if job.conclusion else None,
            "status": job.status,
            "html_url": job.html_url,
            "started_at": _dt_to_wire(job.started_at),
            "completed_at": _dt_to_wire(job.completed_at),
            "run_id": job.run_id,
            "run_attempt": job.run_attempt,
        }
    if event.check_run:
        check = event.check_run
        data["check_run"] = {
            "id": check.id,
            "name": check.name,
            "conclusion": check.conclusion.value if check.conclusion else None,
            "status": check.status,
            "html_url": check.html_url,
            "started_at": _dt_to_wire(check.started_at),
            "completed_at": _dt_to_wire(check.completed_at),
            "output": check.output,
        }
    if event.pull_request:
        pr = event.pull_request
        data["pull_request"] = {
            "number": pr.number,
            "title": pr.title,
            "state": pr.state,
            "html_url": pr.html_url,
            "head_sha": pr.head_sha,
            "base_sha": pr.base_sha,
            "head_ref": pr.head_ref,
            "base_ref": pr.base_ref,
            "user_login": pr.user_login,
            "draft": pr.draft,
            "created_at": pr.created_at.isoformat(),
            "updated_at": pr.updated_at.isoformat(),
        }
    if event.commit:
        commit = event.commit
        data["commit"] = {
            "sha": commit.sha,
            "message": commit.message,
            "author_login": commit.author_login,
            "authored_at": commit.authored_at.isoformat(),
            "html_url": commit.html_url,
        }
    return data


def normalized_event_from_dict(data: dict[str, Any]) -> NormalizedEvent:
    """Rehydrate a normalized event stored by ``normalized_event_to_dict``."""
    repo = Repository(**data["repository"])
    workflow_job = None
    if data.get("workflow_job"):
        item = data["workflow_job"]
        workflow_job = WorkflowJob(
            id=item["id"],
            name=item["name"],
            conclusion=WorkflowConclusion(item["conclusion"]) if item.get("conclusion") else None,
            status=item["status"],
            html_url=item["html_url"],
            started_at=_dt_from_wire(item.get("started_at")),
            completed_at=_dt_from_wire(item.get("completed_at")),
            run_id=item["run_id"],
            run_attempt=item["run_attempt"],
        )
    check_run = None
    if data.get("check_run"):
        item = data["check_run"]
        check_run = CheckRun(
            id=item["id"],
            name=item["name"],
            conclusion=WorkflowConclusion(item["conclusion"]) if item.get("conclusion") else None,
            status=item["status"],
            html_url=item["html_url"],
            started_at=_dt_from_wire(item.get("started_at")),
            completed_at=_dt_from_wire(item.get("completed_at")),
            output=item.get("output"),
        )
    pull_request = None
    if data.get("pull_request"):
        item = data["pull_request"]
        pull_request = PullRequest(
            number=item["number"],
            title=item["title"],
            state=item["state"],
            html_url=item["html_url"],
            head_sha=item["head_sha"],
            base_sha=item["base_sha"],
            head_ref=item["head_ref"],
            base_ref=item["base_ref"],
            user_login=item["user_login"],
            draft=item["draft"],
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
        )
    commit = None
    if data.get("commit"):
        item = data["commit"]
        commit = Commit(
            sha=item["sha"],
            message=item["message"],
            author_login=item["author_login"],
            authored_at=datetime.fromisoformat(item["authored_at"]),
            html_url=item["html_url"],
        )
    return NormalizedEvent(
        delivery_id=data["delivery_id"],
        event_type=EventType(data["event_type"]),
        repository=repo,
        timestamp=datetime.fromisoformat(data["timestamp"]),
        workflow_job=workflow_job,
        check_run=check_run,
        pull_request=pull_request,
        pr_action=PRAction(data["pr_action"]) if data.get("pr_action") else None,
        commit=commit,
        raw_payload=None,
    )
