import json
from dataclasses import dataclass

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm

from .config import get_config
from .events import NormalizedEvent
from .evidence import CIEvidence, PREvidence
from .policy import PolicyEngine


@dataclass(frozen=True)
class ActionProposal:
    action: str
    title: str | None = None
    body: str | None = None
    labels: list[str] | None = None
    reason: str | None = None
    confidence: str | None = None
    evidence_refs: list[str] | None = None
    marker: str | None = None


class RepoRelayAgent:
    def __init__(self, policy_engine: PolicyEngine):
        self.policy_engine = policy_engine
        self.config = get_config()
        self._agent: Agent | None = None

    def _get_agent(self) -> Agent:
        if self._agent is None:
            self._agent = Agent(
                name="reporelay",
                model=LiteLlm(model=self.config.gemini_model),
                instruction=self._get_instruction(),
                tools=[],
            )
        return self._agent

    def _get_instruction(self) -> str:
        return """You are RepoRelay, an autonomous GitHub maintenance agent.

Your job is to investigate repository events and propose exactly ONE safe maintenance action.

ALLOWED ACTIONS:
1. create_issue - Create a triage issue for failed CI
   Required fields: action="create_issue", title, body, labels=["reporelay-triage"], reason, confidence, evidence_refs
2. create_pr_comment - Post a PR readiness comment
   Required fields: action="create_pr_comment", body, reason, marker="reporelay-readiness"

CONSTRAINTS:
- You NEVER merge, push, delete, or modify repository settings
- You ONLY create/update issues and comments with the reporelay label/marker
- Output MUST be valid JSON matching the action schema
- Confidence must be: high, medium, or low
- Evidence refs must be URLs to GitHub (checks, logs, files, commits)
- If uncertain, choose low confidence and explain why"""

    def investigate_ci_failure(
        self, event: NormalizedEvent, evidence: CIEvidence, installation_id: int, owner: str, repo: str
    ) -> ActionProposal:
        prompt = self._build_ci_prompt(event, evidence)
        response = self._get_agent().run(prompt)
        return self._parse_proposal(response)

    def investigate_pr_readiness(
        self, event: NormalizedEvent, evidence: PREvidence, installation_id: int, owner: str, repo: str
    ) -> ActionProposal:
        prompt = self._build_pr_prompt(event, evidence)
        response = self._get_agent().run(prompt)
        return self._parse_proposal(response)

    def _build_ci_prompt(self, event: NormalizedEvent, evidence: CIEvidence) -> str:
        commit_sha = event.commit.sha if event.commit else "unknown"
        commit_url = event.commit.html_url if event.commit else ""
        
        prompt = f"""Investigate this CI failure and propose a triage issue.

REPOSITORY: {event.repository.full_name}
COMMIT: {commit_sha} ({commit_url})
EVENT: {event.event_type.value}
JOB/CHECK: {evidence.job_name}
CONCLUSION: {evidence.conclusion}
EVIDENCE URL: {evidence.html_url}

LOG EXCERPT (last 200 lines):
```
{evidence.log_excerpt or "No logs available"}
```

FAILED STEP: {evidence.failed_step or "Unknown"}
ERROR MESSAGE: {evidence.error_message or "Unknown"}

Classify the likely failure category:
- test_failure: Unit/integration tests failed
- lint_failure: Linting/formatting checks failed
- build_failure: Compilation/build errors
- dependency_failure: Missing/broken dependencies
- flaky_test: Intermittent failure
- infrastructure_failure: CI platform issues
- unknown: Cannot determine

Output JSON ONLY with this exact schema:
{{
  "action": "create_issue",
  "title": "CI triage: <category> on <short-sha>",
  "body": "## CI Triage Report\\n\\n**Repository:** {event.repository.full_name}\\n**Commit:** {commit_sha}\\n**Workflow/Job:** {evidence.job_name}\\n**Conclusion:** {evidence.conclusion}\\n**Evidence:** {evidence.html_url}\\n\\n### Root Cause Hypothesis\\n<your hypothesis>\\n\\n### Confidence\\n<high|medium|low> - <explanation>\\n\\n### Next Actions\\n1. <action>\\n2. <action>\\n\\n### Evidence\\n- {evidence.html_url}\\n- {commit_url}",
  "labels": ["reporelay-triage"],
  "reason": "<one-line reason>",
  "confidence": "<high|medium|low>",
  "evidence_refs": ["{evidence.html_url}", "{commit_url}"]
}}"""
        return prompt

    def _build_pr_prompt(self, event: NormalizedEvent, evidence: PREvidence) -> str:
        failed_check_md = "\n".join([f"- {c['name']}: {c['conclusion']} ({c['html_url']})" for c in evidence.failed_checks])
        all_check_md = "\n".join([f"- {c['name']}: {c['conclusion']} ({c['html_url']})" for c in evidence.checks])
        changed_files_md = "\n".join([f"- {f['filename']} ({f['status']}, +{f['additions']}/-{f['deletions']})" for f in evidence.changed_files[:20]])

        prompt = f"""Analyze this PR and create a readiness comment.

REPOSITORY: {event.repository.full_name}
PR: #{evidence.pr_number} - {evidence.pr_title}
URL: {evidence.pr_url}
HEAD: {evidence.head_sha[:8]} ({evidence.head_ref})
BASE: {evidence.base_sha[:8]} ({evidence.base_ref})
DRAFT: {evidence.draft}

CHANGED FILES:
{changed_files_md}

ALL CHECKS:
{all_check_md}

FAILED CHECKS:
{failed_check_md or "None"}

MISSING TESTS DETECTED: {evidence.missing_tests}
MISSING DOCS DETECTED: {evidence.missing_docs}

Determine readiness state: READY | NEEDS_WORK | BLOCKED

Output JSON ONLY with this exact schema:
{{
  "action": "create_pr_comment",
  "body": "## RepoRelay PR Readiness Report\\n\\n**State:** <READY|NEEDS_WORK|BLOCKED>\\n\\n### Checks\\n{all_check_md or 'No checks found'}\\n\\n### Failed Checks\\n{failed_check_md or 'None'}\\n\\n### Changed Files\\n{changed_files_md}\\n\\n### Issues Detected\\n{'❌ Missing tests for new/modified code' if evidence.missing_tests else ''}\\n{'❌ Missing documentation updates' if evidence.missing_docs else ''}\\n\\n### Checklist\\n- [ ] All checks passing\\n- [ ] Tests added for new code\\n- [ ] Documentation updated\\n- [ ] No merge conflicts\\n\\n### Evidence\\n- PR: {evidence.pr_url}\\n- Head commit: https://github.com/{event.repository.full_name}/commit/{evidence.head_sha}",
  "reason": "<one-line reason>",
  "marker": "reporelay-readiness"
}}"""
        return prompt

    def _parse_proposal(self, response: str) -> ActionProposal:
        try:
            data = json.loads(response.strip())
            return ActionProposal(**data)
        except (json.JSONDecodeError, TypeError) as e:
            return ActionProposal(
                action="error",
                reason=f"Failed to parse agent response: {e}",
                confidence="low",
            )