import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Config:
    github_app_id: str
    github_app_private_key: str
    github_webhook_secret: str
    google_cloud_project: str
    firestore_database: str
    gemini_model: str
    allowed_repositories: list[str]
    admin_token: str = ""
    max_log_lines: int = 200
    max_retries: int = 3
    retry_base_delay_seconds: float = 1.0

    @classmethod
    def from_env(cls) -> "Config":
        allowed_repos_raw = os.getenv("ALLOWED_REPOSITORIES", "")
        allowed_repos = [r.strip() for r in allowed_repos_raw.split(",") if r.strip()]
        return cls(
            github_app_id=os.getenv("GITHUB_APP_ID", ""),
            github_app_private_key=os.getenv("GITHUB_APP_PRIVATE_KEY", ""),
            github_webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET", ""),
            google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
            firestore_database=os.getenv("FIRESTORE_DATABASE", "(default)"),
            gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
            allowed_repositories=allowed_repos,
            admin_token=os.getenv("ADMIN_TOKEN", ""),
            max_log_lines=int(os.getenv("MAX_LOG_LINES", "200")),
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            retry_base_delay_seconds=float(os.getenv("RETRY_BASE_DELAY_SECONDS", "1.0")),
        )


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config.from_env()
