"""Configuration management for hpo-link.

Settings load from environment variables with the ``HPO_LINK_`` prefix (nested
models use ``__``, e.g. ``HPO_LINK_DATA__DB_FILENAME=hpo.sqlite``) and an
optional ``.env`` file.

hpo-link has no live API: the local HPO index, built from the hp.json + HPOA
releases served on the OBO PURLs, is the only data source.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from hpo_link import __version__

# Project root: <repo>/hpo_link/config.py -> <repo>
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_IMMUTABLE_TAG_FORBIDDEN = frozenset({"latest", "main", "master", "head", "stable", "current"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ImmutableDataRequirement(BaseModel):
    """One exact HPO bundle that an init sidecar may materialize.

    This separate frozen model is intentionally not a general release-discovery
    configuration.  The serving app receives only the selected database path;
    the init process receives an immutable URL plus the independent digest it
    must verify before a snapshot becomes current.
    """

    model_config = ConfigDict(frozen=True)

    reference_root: Path
    release_tag: str
    bundle_url: AnyHttpUrl
    compressed_sha256: str
    expanded_tree_sha256: str
    schema_version: int
    hpo_version: str
    hpoa_version: str
    max_compressed_bytes: int
    max_expanded_bytes: int

    @model_validator(mode="after")
    def validate_immutable_pin(self) -> ImmutableDataRequirement:
        """Reject mutable, incomplete, or mismatched bundle identities."""
        if not self.release_tag or self.release_tag.lower() in _IMMUTABLE_TAG_FORBIDDEN:
            raise ValueError("immutable data release_tag must not be mutable")
        if self.bundle_url.scheme != "https":
            raise ValueError("immutable data bundle_url must use HTTPS")
        if not _SHA256_RE.fullmatch(self.compressed_sha256):
            raise ValueError("immutable data compressed_sha256 must be lowercase SHA-256")
        if not _SHA256_RE.fullmatch(self.expanded_tree_sha256):
            raise ValueError("immutable data expanded_tree_sha256 must be lowercase SHA-256")
        if (
            self.schema_version <= 0
            or self.max_compressed_bytes <= 0
            or self.max_expanded_bytes <= 0
        ):
            raise ValueError("immutable data schema and byte limits must be positive")
        bundle_path = self.bundle_url.path
        if bundle_path is None:
            raise ValueError("immutable data bundle_url must contain an asset path")
        asset = bundle_path.rsplit("/", maxsplit=1)[-1]
        if not bundle_path.endswith(f"/{self.release_tag}/{asset}") or not asset.endswith(
            ".sqlite.zst"
        ):
            raise ValueError("immutable data bundle_url must name an asset under release_tag")
        return self


def _default_immutable_data_requirement() -> ImmutableDataRequirement:
    """Return the reviewed HPO reference bundle identity for production materialization."""
    return ImmutableDataRequirement(
        reference_root=Path("/data"),
        release_tag="db-v2026-06-23",
        bundle_url=AnyHttpUrl(
            "https://github.com/berntpopp/hpo-link/releases/download/"
            "db-v2026-06-23/hpo-2026-06-23.sqlite.zst"
        ),
        compressed_sha256="d677a96efd8c274045241934c33b25dfb6fc9a6414c27bed7ae3334d05d4c9f6",
        expanded_tree_sha256="f98176204ac9b70d4451efab7fcafa4756e1aac2f14b64a5f2c5ec0d574ebee3",
        schema_version=1,
        hpo_version="2026-06-23",
        hpoa_version="2026-06-23",
        max_compressed_bytes=128 * 1024 * 1024,
        max_expanded_bytes=512 * 1024 * 1024,
    )


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
    max_source_bytes: int = Field(
        default=128 * 1024 * 1024,
        ge=1,
        description=(
            "Per-source cap; largest source measured 35,672,303 bytes on 2026-07-10. "
            "Override with HPO_LINK_DATA__MAX_SOURCE_BYTES as releases grow."
        ),
    )
    max_manifest_bytes: int = Field(
        default=64 * 1024,
        ge=1,
        description=(
            "GitHub metadata cap; manifest measured 550 bytes on 2026-07-10. "
            "Override with HPO_LINK_DATA__MAX_MANIFEST_BYTES if metadata grows."
        ),
    )
    max_bundle_bytes: int = Field(
        default=128 * 1024 * 1024,
        ge=1,
        description=(
            "Compressed prebuilt cap; bundle measured 19,083,660 bytes on 2026-07-10. "
            "Override with HPO_LINK_DATA__MAX_BUNDLE_BYTES as releases grow."
        ),
    )
    max_database_bytes: int = Field(
        default=512 * 1024 * 1024,
        ge=1,
        description=(
            "Expanded SQLite cap; database measured 136,249,344 bytes on 2026-07-10. "
            "Override with HPO_LINK_DATA__MAX_DATABASE_BYTES as releases grow."
        ),
    )
    max_download_seconds: float = Field(
        default=1800.0,
        ge=1.0,
        description="Total download deadline; override HPO_LINK_DATA__MAX_DOWNLOAD_SECONDS.",
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
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "::1"],
        description="Exact Host header values accepted by the request guard.",
    )
    allowed_origins: list[str] = Field(
        default_factory=list,
        description="Browser Origin values accepted by the request guard.",
    )

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
    immutable_data: ImmutableDataRequirement = Field(
        default_factory=_default_immutable_data_requirement,
        description="Exact immutable HPO bundle materialized only by the init sidecar.",
    )

    @field_validator("mcp_path")
    @classmethod
    def validate_mcp_path(cls, v: str) -> str:
        """Ensure the MCP path starts with a forward slash."""
        return v if v.startswith("/") else f"/{v}"

    @field_validator("allowed_hosts")
    @classmethod
    def reject_wildcard_hosts(cls, v: list[str]) -> list[str]:
        """Require exact Host values rather than wildcard patterns."""
        if any(any(marker in host for marker in "*?[]") for host in v):
            raise ValueError("wildcard patterns are not allowed in allowed_hosts")
        return v

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
