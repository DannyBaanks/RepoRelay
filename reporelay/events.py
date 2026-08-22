from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional
import json


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
    conclusion: Optional[WorkflowConclusion]
    status: str
    html_url: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
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
    conclusion: Optional[WorkflowConclusion]
    status: str
    html_url: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    output: Optional[dict[str, Any]]

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
    workflow_job: Optional[WorkflowJob] = None
    check_run: Optional[CheckRun] = None
    pull_request: Optional[PullRequest] = None
    pr_action: Optional[PRAction] = None
    commit: Optional[Commit] = None
    raw_payload: dict[str, Any] = None


def normalize_event(
    delivery_id: str, event_name: str, payload: dict[str, Any]
) -> NormalizedEvent:
    timestamp = datetime.fromisoformat(
        payload.get("repository", {}).get("updated_at", datetime.utcnow().isoformat()).replace("Z", "+00:00")
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