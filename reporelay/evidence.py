from dataclasses import dataclass
from typing import Any, Optional
from .tools.github_read import GitHubReadClient
from .events import NormalizedEvent, WorkflowJob, CheckRun, PullRequest


@dataclass(frozen=True)
class CIEvidence:
    workflow_name: Optional[str] = None
    job_name: Optional[str] = None
    conclusion: Optional[str] = None
    html_url: Optional[str] = None
    log_excerpt: Optional[str] = None
    failed_step: Optional[str] = None
    error_message: Optional[str] = None


@dataclass(frozen=True)
class PREvidence:
    pr_number: int
    pr_title: str
    pr_url: str
    head_sha: str
    base_sha: str
    head_ref: str
    base_ref: str
    draft: bool
    changed_files: list[dict[str, Any]]
    checks: list[dict[str, Any]]
    failed_checks: list[dict[str, Any]]
    missing_tests: bool = False
    missing_docs: bool = False


class EvidenceGatherer:
    def __init__(self, read_client: GitHubReadClient):
        self.read_client = read_client

    def gather_ci_evidence(
        self, installation_id: int, owner: str, repo: str, event: NormalizedEvent
    ) -> CIEvidence:
        if event.workflow_job:
            return self._gather_from_workflow_job(installation_id, owner, repo, event.workflow_job)
        elif event.check_run:
            return self._gather_from_check_run(installation_id, owner, repo, event.check_run)
        return CIEvidence()

    def _gather_from_workflow_job(
        self, installation_id: int, owner: str, repo: str, job: WorkflowJob
    ) -> CIEvidence:
        log_excerpt = ""
        failed_step = None
        error_message = None

        if job.conclusion and job.conclusion.value == "failure":
            try:
                log_excerpt = self.read_client.get_workflow_job_logs(
                    installation_id, owner, repo, job.id, max_lines=200
                )
                failed_step, error_message = self._extract_failure(log_excerpt)
            except Exception:
                pass

        return CIEvidence(
            job_name=job.name,
            conclusion=job.conclusion.value if job.conclusion else None,
            html_url=job.html_url,
            log_excerpt=log_excerpt,
            failed_step=failed_step,
            error_message=error_message,
        )

    def _gather_from_check_run(
        self, installation_id: int, owner: str, repo: str, check: CheckRun
    ) -> CIEvidence:
        log_excerpt = ""
        failed_step = None
        error_message = None

        if check.conclusion and check.conclusion.value == "failure":
            try:
                log_excerpt = self.read_client.get_check_run_logs(
                    installation_id, owner, repo, check.id, max_lines=200
                )
                if not log_excerpt and check.output:
                    log_excerpt = check.output.get("summary", "") + "\n" + check.output.get("text", "")
                failed_step, error_message = self._extract_failure(log_excerpt)
            except Exception:
                pass

        return CIEvidence(
            job_name=check.name,
            conclusion=check.conclusion.value if check.conclusion else None,
            html_url=check.html_url,
            log_excerpt=log_excerpt,
            failed_step=failed_step,
            error_message=error_message,
        )

    def _extract_failure(self, log: str) -> tuple[Optional[str], Optional[str]]:
        lines = log.splitlines()
        for i, line in enumerate(lines):
            lower = line.lower()
            if any(kw in lower for kw in ["error:", "failed:", "failure:", "exception", "traceback"]):
                context = "\n".join(lines[max(0, i - 2):min(len(lines), i + 5)])
                return line[:200], context[:500]
        return None, None

    def gather_pr_evidence(
        self, installation_id: int, owner: str, repo: str, event: NormalizedEvent
    ) -> Optional[PREvidence]:
        if not event.pull_request:
            return None

        pr = event.pull_request
        files = self.read_client.get_pull_request_files(installation_id, owner, repo, pr.number)
        checks = self.read_client.get_pull_request_checks(installation_id, owner, repo, pr.number)

        check_dicts = []
        failed_checks = []
        for check in checks:
            cd = {
                "name": check.name,
                "conclusion": check.conclusion.value if check.conclusion else check.status,
                "html_url": check.html_url,
            }
            check_dicts.append(cd)
            if check.conclusion and check.conclusion.value == "failure":
                failed_checks.append(cd)

        missing_tests = self._detect_missing_tests(files)
        missing_docs = self._detect_missing_docs(files)

        return PREvidence(
            pr_number=pr.number,
            pr_title=pr.title,
            pr_url=pr.html_url,
            head_sha=pr.head_sha,
            base_sha=pr.base_sha,
            head_ref=pr.head_ref,
            base_ref=pr.base_ref,
            draft=pr.draft,
            changed_files=files,
            checks=check_dicts,
            failed_checks=failed_checks,
            missing_tests=missing_tests,
            missing_docs=missing_docs,
        )

    def _detect_missing_tests(self, files: list[dict[str, Any]]) -> bool:
        test_patterns = ["test_", "_test.py", "spec.", "Spec.", "__test__"]
        source_files = [f for f in files if not any(p in f["filename"] for p in test_patterns)]
        test_files = [f for f in files if any(p in f["filename"] for p in test_patterns)]
        if source_files and not test_files:
            return True
        for sf in source_files:
            if sf["status"] in ("added", "modified") and sf["additions"] > 50:
                related_test = any(sf["filename"].replace(".py", "_test.py") in tf["filename"] for tf in test_files)
                if not related_test:
                    return True
        return False

    def _detect_missing_docs(self, files: list[dict[str, Any]]) -> bool:
        doc_patterns = [".md", ".rst", "README", "CHANGELOG", "docs/"]
        source_files = [f for f in files if f["filename"].endswith((".py", ".js", ".ts", ".go", ".rs"))]
        doc_files = [f for f in files if any(p in f["filename"] for p in doc_patterns)]
        if source_files and not doc_files:
            return True
        return False