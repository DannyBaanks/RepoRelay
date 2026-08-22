import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import Mock, patch


@pytest.fixture(autouse=True)
def mock_google_cloud():
    with patch("google.cloud.firestore.Client") as mock:
        yield mock


@pytest.fixture(autouse=True)
def mock_github():
    with patch("github.Github") as mock_github, \
         patch("github.GithubIntegration") as mock_integration:
        yield mock_github, mock_integration


@pytest.fixture
def sample_workflow_job_payload():
    return {
        "repository": {
            "owner": {"login": "testowner"},
            "name": "testrepo",
            "full_name": "testowner/testrepo",
            "html_url": "https://github.com/testowner/testrepo",
            "updated_at": "2026-08-22T12:00:00Z",
        },
        "workflow_job": {
            "id": 12345,
            "name": "test-job",
            "conclusion": "failure",
            "status": "completed",
            "html_url": "https://github.com/testowner/testrepo/actions/runs/1/jobs/12345",
            "started_at": "2026-08-22T12:00:00Z",
            "completed_at": "2026-08-22T12:05:00Z",
            "run_id": 1,
            "run_attempt": 1,
        },
    }


@pytest.fixture
def sample_pr_payload():
    return {
        "action": "opened",
        "repository": {
            "owner": {"login": "testowner"},
            "name": "testrepo",
            "full_name": "testowner/testrepo",
            "html_url": "https://github.com/testowner/testrepo",
            "updated_at": "2026-08-22T12:00:00Z",
        },
        "pull_request": {
            "number": 42,
            "title": "Add feature",
            "state": "open",
            "html_url": "https://github.com/testowner/testrepo/pull/42",
            "head": {"sha": "abc123", "ref": "feature-branch"},
            "base": {"sha": "def456", "ref": "main"},
            "user": {"login": "contributor"},
            "draft": False,
            "created_at": "2026-08-22T10:00:00Z",
            "updated_at": "2026-08-22T12:00:00Z",
        },
    }