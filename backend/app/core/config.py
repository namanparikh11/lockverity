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

    # --- External provider safety ---
    provider_timeout_seconds: float = Field(default=15.0)
    provider_max_response_bytes: int = Field(default=10 * 1024 * 1024)
    provider_retry_limit: int = Field(default=2)

    # --- Pagination ---
    pagination_default_page_size: int = Field(default=25, ge=1)
    pagination_max_page_size: int = Field(default=200, ge=1)

    # --- Application identity ---
    app_name: str = Field(default="Lockverity")
    app_version: str = Field(default="0.1.0")
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
