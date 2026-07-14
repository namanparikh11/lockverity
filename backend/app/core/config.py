"""Application configuration.

All runtime configuration is read from environment variables. No secrets
are committed to source control. Production configuration is validated
strictly; development configuration has safe defaults.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app._version import __version__

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    """Typed application configuration.

    Values are loaded from environment variables (prefix ``LOCKVERITY_``)
    and from a local ``.env`` file when one is present.
    """

    model_config = SettingsConfigDict(
        env_prefix="LOCKVERITY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Core runtime ---
    environment: Environment = Field(default="development")
    api_prefix: str = Field(default="/api/v1")
    cors_origins: list[str] = Field(default_factory=list)
    database_url: str = Field(default="sqlite:///./lockverity.sqlite")

    # --- Workspace ---
    workspace_root: str = Field(default="./var/workspace")

    # --- Archive safety limits (bytes) ---
    archive_max_compressed_bytes: int = Field(default=100 * 1024 * 1024)
    archive_max_uncompressed_bytes: int = Field(default=1024 * 1024 * 1024)
    archive_max_file_count: int = Field(default=100_000)
    archive_max_file_bytes: int = Field(default=256 * 1024 * 1024)
    archive_max_depth: int = Field(default=64)
    archive_suspicious_ratio: int = Field(default=200)

    # --- External provider safety (shared) ---
    provider_timeout_seconds: float = Field(default=15.0)
    provider_max_response_bytes: int = Field(default=10 * 1024 * 1024)
    provider_retry_limit: int = Field(default=2)

    # --- GitHub intake ---
    github_api_url: str = Field(default="https://api.github.com")
    github_token: str | None = Field(default=None)
    github_timeout_seconds: float = Field(default=15.0)
    github_max_response_bytes: int = Field(default=10 * 1024 * 1024)
    github_max_download_bytes: int = Field(default=200 * 1024 * 1024)
    github_retry_limit: int = Field(default=2)
    github_user_agent: str = Field(default="lockverity/0.2 (core-intake)")

    # --- Scan worker / executor ---
    scan_worker_concurrency: int = Field(default=2, ge=1, le=32)
    scan_heartbeat_seconds: int = Field(default=15, ge=1, le=600)
    scan_heartbeat_timeout_seconds: int = Field(default=120, ge=10, le=3600)
    scan_default_failure_summary_max_length: int = Field(default=500, ge=64, le=2048)
    scan_concurrency_per_repository: int = Field(default=1, ge=1, le=8)

    # --- Provider cache ---
    provider_cache_max_payload_bytes: int = Field(default=1024 * 1024, ge=4096)
    provider_cache_default_ttl_seconds: int = Field(default=3600, ge=60, le=7 * 24 * 3600)

    # --- Pagination ---
    pagination_default_page_size: int = Field(default=25, ge=1)
    pagination_max_page_size: int = Field(default=200, ge=1)

    # --- Application identity ---
    app_name: str = Field(default="Lockverity")
    # The version is read from the package's single source of truth
    # (``app._version``) so the API responses, the startup log, and
    # the export metadata never drift apart. See ``app/_version.py``
    # for the rationale.
    app_version: str = Field(default_factory=lambda: __version__)
    app_tagline: str = Field(
        default="Evidence-first software supply-chain assurance",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Allow comma-separated CORS origins in env.

        ``LOCKVERITY_CORS_ORIGINS="https://a.example,https://b.example"``
        is easier to maintain in deployment than a JSON list.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_in_production(cls, value: list[str], info) -> list[str]:
        env = info.data.get("environment", "development")
        if env == "production" and any(origin.strip() == "*" for origin in value):
            raise ValueError("Wildcard CORS origin '*' is not permitted in production.")
        return value

    @field_validator("pagination_max_page_size")
    @classmethod
    def _pagination_max_sane(cls, value: int) -> int:
        if value > 1000:
            raise ValueError("pagination_max_page_size must be <= 1000 to bound DB load.")
        return value

    @field_validator("archive_suspicious_ratio")
    @classmethod
    def _ratio_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("archive_suspicious_ratio must be a positive integer.")
        return value

    @field_validator("github_token")
    @classmethod
    def _token_must_not_look_like_url(cls, value: str | None) -> str | None:
        # Defence in depth: reject values that would obviously break
        # the transport layer (whitespace, control chars, surrounding
        # quotes that are sometimes pasted from shells).
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            return None
        stripped = value.strip()
        if any(ch in stripped for ch in ("\n", "\r", "\t", "\x00", " ")):
            raise ValueError("github_token must not contain whitespace or control characters.")
        if len(stripped) > 256:
            raise ValueError("github_token is unreasonably long.")
        return stripped

    @field_validator("github_api_url")
    @classmethod
    def _github_api_url_must_be_https(cls, value: str) -> str:
        if not isinstance(value, str) or not value.startswith("https://"):
            raise ValueError("github_api_url must be an https:// URL.")
        return value.rstrip("/")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached :class:`Settings` instance.

    Caching means tests must call :func:`get_settings.cache_clear` after
    mutating the environment if they need to re-evaluate configuration.
    """
    return Settings()
