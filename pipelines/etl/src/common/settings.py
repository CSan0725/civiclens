"""Runtime configuration, loaded from the environment or a local `.env`.

Variable names are shared with the repo-root `.env.example` so one set of
secrets serves dbmate, the Next.js app, and this pipeline.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from common.useragent import USER_AGENT


class Settings(BaseSettings):
    """Environment-backed settings for every ETL job."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- database -----------------------------------------------------------
    database_url: str = Field(
        default="postgres://postgres:postgres@localhost:5432/civiclens",
        description="Direct (unpooled) Postgres URL. Bulk loads must bypass PgBouncer.",
    )

    # --- upstream API keys --------------------------------------------------
    congress_gov_api_key: str = ""
    govinfo_api_key: str = ""
    fec_api_key: str = ""

    # --- object storage (Cloudflare R2) -------------------------------------
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "civiclens-snapshots"
    r2_endpoint: str = ""

    # --- run behaviour ------------------------------------------------------
    etl_request_delay: float = Field(
        default=0.2,
        ge=0.0,
        description="Politeness delay between upstream requests, in seconds.",
    )
    etl_log_level: str = "INFO"
    etl_max_retries: int = Field(default=5, ge=0)

    senate_user_agent: str = Field(
        default=USER_AGENT,
        description=(
            "User-Agent for senate.gov only. Its Akamai WAF returns 403 to this "
            "honest default from some networks; see docs/P1-source-verification.md "
            "before overriding."
        ),
    )
    etl_backfill_from_congress: int = Field(
        default=101,
        ge=1,
        description=(
            "Earliest Congress to backfill. 101 = 1989-1991, covering the confirmed "
            "start years: senate.gov XML from 1989, clerk.house.gov XML from 1990."
        ),
    )

    def sqlalchemy_url(self) -> str:
        """`database_url` normalised to the psycopg3 dialect SQLAlchemy expects.

        Providers hand out `postgres://` or `postgresql://`; SQLAlchemy needs an
        explicit `postgresql+psycopg://` to pick psycopg3 over psycopg2.
        """
        url = self.database_url
        for prefix in ("postgresql+psycopg://", "postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
