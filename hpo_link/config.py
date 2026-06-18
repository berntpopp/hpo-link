"""Configuration management for hpo-link.

Settings load from environment variables with the ``MONDO_LINK_`` prefix (nested
models use ``__``, e.g. ``MONDO_LINK_DATA__DB_FILENAME=mondo.sqlite``) and an
optional ``.env`` file.

hpo-link has no live API: the local Mondo index, built from the OBO + SSSOM
releases served on the Monarch PURLs, is the only data source.
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

#: Monarch publishes the Mondo OBO release at this PURL.
DEFAULT_OBO_URL = "http://purl.obolibrary.org/obo/mondo.obo"

#: Mondo publishes the consolidated SSSOM cross-ontology mappings in-repo. (The
#: ``obo/mondo.sssom.tsv`` PURL 404s; the OBO already carries dbxrefs, so SSSOM
#: is treated as a supplementary, optional source — see ``ingest.downloader``.)
DEFAULT_SSSOM_URL = (
    "https://raw.githubusercontent.com/monarch-initiative/mondo/master/"
    "src/ontology/mappings/mondo.sssom.tsv"
)


class MondoDataConfig(BaseModel):
    """Local data store: Mondo OBO + SSSOM releases -> built SQLite index."""

    data_dir: Path = Field(
        default=_DEFAULT_DATA_DIR,
        description="Directory holding the built SQLite database and download cache.",
    )
    db_filename: str = Field(
        default="mondo.sqlite",
        description="SQLite database filename within data_dir.",
    )
    obo_url: str = Field(
        default=DEFAULT_OBO_URL,
        description="URL of the Mondo OBO release (Monarch PURL).",
    )
    sssom_url: str = Field(
        default=DEFAULT_SSSOM_URL,
        description="URL of the Mondo SSSOM cross-ontology mapping release (Monarch PURL).",
    )
    download_timeout: int = Field(
        default=300,
        ge=5,
        le=1800,
        description="HTTP timeout (seconds) for downloading a Mondo release file.",
    )
    user_agent: str = Field(
        default=f"hpo-link/{__version__} (+https://github.com/berntpopp/hpo-link)",
        description="User-Agent sent to the Monarch PURLs.",
    )
    auto_bootstrap: bool = Field(
        default=True,
        description="Build the database on first use by downloading Mondo if absent.",
    )
    refresh_enabled: bool = Field(
        default=False,
        description=(
            "Run an in-process scheduler (unified/http transports only) that "
            "conditionally refreshes the database on an interval. Default OFF: Mondo "
            "releases are best refreshed by an external cron job (see docs/deployment.md)."
        ),
    )
    refresh_interval_hours: float = Field(
        default=168.0,
        ge=1.0,
        le=720.0,
        description=(
            "Hours between conditional refresh checks (when refresh_enabled). Mondo "
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
        env_prefix="MONDO_LINK_",
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

    data: MondoDataConfig = Field(
        default_factory=MondoDataConfig,
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


def get_data_config() -> MondoDataConfig:
    """Return the active data-store configuration (used by the ingest CLI)."""
    return settings.data
