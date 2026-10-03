"""Verify the immutable HPO data release reported to the fleet controller."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from hpo_link.config import ImmutableDataRequirement
from hpo_link.exceptions import DataUnavailableError
from hpo_link.immutable_data import canonical_tree_sha256

_IDENTITY_KEYS = frozenset(
    {
        "release_tag",
        "compressed_sha256",
        "expanded_tree_sha256",
        "schema_version",
        "hpo_version",
        "hpoa_version",
    }
)


def _read_identity(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise DataUnavailableError("The selected HPO data release identity is unavailable.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DataUnavailableError("The selected HPO data release identity is invalid.") from exc
    if not isinstance(value, dict) or set(value) != _IDENTITY_KEYS:
        raise DataUnavailableError("The selected HPO data release identity is incomplete.")
    return value


def _verify_runtime_database(
    database: Path, requirement: ImmutableDataRequirement
) -> tuple[Path, dict[str, str]]:
    """Verify the exact served file and return its stable path plus public identity."""
    if database.name != "hpo.sqlite" or database.is_symlink():
        raise DataUnavailableError("The selected HPO database file is invalid.")
    try:
        resolved_database = database.resolve(strict=True)
    except OSError as exc:
        raise DataUnavailableError("The selected HPO database is unavailable.") from exc
    resolved_root = resolved_database.parent
    if (
        not resolved_database.is_file()
        or resolved_database.name != "hpo.sqlite"
        or not resolved_root.is_dir()
        or resolved_root.name != requirement.compressed_sha256
    ):
        raise DataUnavailableError("The selected HPO database has the wrong identity.")

    identity_path = resolved_root / "identity.json"
    identity = _read_identity(identity_path)
    expected = {
        "release_tag": requirement.release_tag,
        "compressed_sha256": requirement.compressed_sha256,
        "expanded_tree_sha256": requirement.expanded_tree_sha256,
        "schema_version": requirement.schema_version,
        "hpo_version": requirement.hpo_version,
        "hpoa_version": requirement.hpoa_version,
    }
    if identity != expected:
        raise DataUnavailableError("The selected HPO data release does not match its pin.")
    if canonical_tree_sha256(resolved_database) != requirement.expanded_tree_sha256:
        raise DataUnavailableError("The selected HPO SQLite bytes do not match their pin.")
    try:
        connection = sqlite3.connect(f"file:{resolved_database}?mode=ro&immutable=1", uri=True)
        try:
            metadata = connection.execute(
                "SELECT schema_version, hpo_version, hpoa_version FROM meta WHERE id = 1"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise DataUnavailableError("The selected HPO SQLite metadata is unavailable.") from exc
    if metadata != (
        requirement.schema_version,
        requirement.hpo_version,
        requirement.hpoa_version,
    ):
        raise DataUnavailableError("The selected HPO SQLite metadata does not match its pin.")
    if (
        _read_identity(identity_path) != identity
        or database.is_symlink()
        or database.resolve(strict=True) != resolved_database
    ):
        raise DataUnavailableError("The selected HPO data identity changed during verification.")
    return resolved_database, {
        "release_tag": requirement.release_tag,
        "digest": f"sha256:{requirement.compressed_sha256}",
    }


def verify_runtime_identity(
    database: Path, requirement: ImmutableDataRequirement
) -> dict[str, str]:
    """Prove the exact served SQLite file matches the configured immutable release."""
    _verified_database, identity = _verify_runtime_database(database, requirement)
    return identity


def verified_database_path(database: Path, requirement: ImmutableDataRequirement) -> Path:
    """Return the stable resolved SQLite path after verifying its release identity."""
    verified_database, _identity = _verify_runtime_database(database, requirement)
    return verified_database


def expected_identity(requirement: ImmutableDataRequirement) -> dict[str, str]:
    """Return the public release identity derived solely from validated configuration."""
    return {
        "release_tag": requirement.release_tag,
        "digest": f"sha256:{requirement.compressed_sha256}",
    }


__all__ = ["expected_identity", "verify_runtime_identity", "verified_database_path"]
