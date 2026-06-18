"""Configuration management for hpo-link.

Settings load from environment variables with the ``HPO_LINK_`` prefix (nested
models use ``__``, e.g. ``HPO_LINK_DATA__DB_FILENAME=hpo.sqlite``) and an
optional ``.env`` file.

hpo-link has no live API: the local HPO index, built from the hp.json + HPOA
releases served on the OBO PURLs, is the only data source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from hpo_link import __version__

# Project root: <repo>/hpo_link/config.py -> <repo>
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"


class HPODataConfig(BaseModel):
    """Local data store: HPO hp.json + HPOA releases -> built SQLite index."""

    data_dir: Path = Field(
        default=_DEFAULT_DATA_DIR,
        description="Directory holding the built SQLite database and download cache.",
    )
    db_filename: str = Field(
        default="hpo.sqlite",
        description="SQLite database filename within data_dir.",
    )
    ontology_edition: Literal["hp.json", "hp-base.json"] = Field(
        default="hp.json",
        description="HPO ontology edition filename to download.",
    )
    download_timeout: int = Field(
        default=300,
        ge=5,
        le=1800,
        description="HTTP timeout (seconds) for downloading an HPO release file.",
    )
    user_agent: str = Field(
        default=f"hpo-link/{__version__} (+https://github.com/berntpopp/hpo-link)",
        description="User-Agent sent to the OBO PURLs.",
    )
    auto_bootstrap: bool = Field(
        default=True,
        description="Build the database on first use by downloading HPO if absent.",
    )
    prefer_prebuilt: bool = Field(
        default=True,
        description="Prefer a prebuilt SQLite database over building from source.",
    )
    prebuilt_db_url: str | None = Field(
        default=None,
        description="URL of a prebuilt SQLite database to download (optional).",
    )
    refresh_enabled: bool = Field(
        default=False,
        description=(
            "Run an in-process scheduler (unified/http transports only) that "
            "conditionally refreshes the database on an interval. Default OFF: HPO "
            "releases are best refreshed by an external cron job (see docs/deployment.md)."
        ),
    )
    refresh_interval_hours: float = Field(
        default=168.0,
        ge=1.0,
        le=720.0,
        description=(
            "Hours between conditional refresh checks (when refresh_enabled). HPO "
            "releases update roughly weekly; a weekly check is cheap because unchanged "
            "files 304."
        ),
    )
    refresh_jitter_seconds: int = Field(
        default=600,
        ge=0,
        le=86400,
        description="Random jitter added to each refresh to avoid thundering herds.",
    )
    build_lock_timeout: int = Field(
        default=900,
        ge=1,
        le=7200,
        description="Seconds to wait for the cross-process build lock before giving up.",
    )
    cache_size: int = Field(
        default=1024,
        ge=0,
        le=65536,
        description="Max entries in the in-process query cache (0 disables).",
    )
    cache_ttl: int = Field(
        default=3600,
        ge=0,
        le=86400,
        description="Query cache TTL in seconds.",
    )

    @property
    def db_path(self) -> Path:
        """Absolute path to the SQLite database file."""
        return self.data_dir / self.db_filename

    @field_validator("data_dir")
    @classmethod
    def _expand_data_dir(cls, v: Path) -> Path:
        return Path(v).expanduser()


class ServerSettings(BaseSettings):
    """Top-level server settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_prefix="HPO_LINK_",
        env_nested_delimiter="__",
    )

    host: str = Field(default="127.0.0.1", description="Server host.")
    port: int = Field(default=8000, ge=1024, le=65535, description="Server port.")
    reload: bool = Field(default=False, description="Enable auto-reload in development.")

    transport: Literal["unified", "http", "stdio"] = Field(
        default="unified",
        description="Server transport mode.",
    )
    mcp_path: str = Field(default="/mcp", description="MCP endpoint path.")

    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origins.",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level.",
    )
    log_format: Literal["json", "console"] = Field(
        default="console",
        description="Log format.",
    )

    data: HPODataConfig = Field(
        default_factory=HPODataConfig,
        description="Local data store configuration.",
    )

    @field_validator("mcp_path")
    @classmethod
    def validate_mcp_path(cls, v: str) -> str:
        """Ensure the MCP path starts with a forward slash."""
        return v if v.startswith("/") else f"/{v}"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """Parse CORS origins from a comma-separated string or list."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return list(v) if v else []


settings = ServerSettings()


def get_data_config() -> HPODataConfig:
    """Return the active data-store configuration (used by the ingest CLI)."""
    return settings.data
