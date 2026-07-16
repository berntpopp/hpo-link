"""Bounded materialization of the reviewed immutable HPO SQLite bundle."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

import httpx
import zstandard

from hpo_link.config import ImmutableDataRequirement
from hpo_link.exceptions import DataUnavailableError, DownloadError
from hpo_link.ingest.download_security import DownloadPolicy, copy_bounded, open_validated_stream

_SQLITE_HEADER = b"SQLite format 3\x00"
_DOWNLOAD_POLICY = DownloadPolicy(
    allowed_hosts=frozenset({"github.com", "release-assets.githubusercontent.com"}),
    max_redirects=5,
)

__all__ = ["canonical_tree_sha256", "materialize_immutable_data"]


def canonical_tree_sha256(path: Path) -> str:
    """Return the canonical one-file immutable-tree identity for *path*."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            hasher.update(chunk)
    file_sha256 = hasher.hexdigest()
    record = f"hpo.sqlite\0{0o444:o}\0{path.stat().st_size}\0{file_sha256}"
    return hashlib.sha256(record.encode()).hexdigest()


def _fsync(path: Path) -> None:
    """Persist a regular file or directory before atomically selecting it."""
    flags = os.O_RDONLY | (os.O_DIRECTORY if path.is_dir() else 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _download_bundle(requirement: ImmutableDataRequirement, destination: Path) -> None:
    """Download exactly one bounded URL and verify its committed compressed digest."""
    hasher = hashlib.sha256()
    policy = DownloadPolicy(
        allowed_hosts=_DOWNLOAD_POLICY.allowed_hosts,
        max_redirects=_DOWNLOAD_POLICY.max_redirects,
        max_bytes=requirement.max_compressed_bytes,
    )
    try:
        with (
            httpx.Client(follow_redirects=False, timeout=300) as client,
            open_validated_stream(
                client,
                str(requirement.bundle_url),
                headers={"Accept": "application/octet-stream"},
                policy=policy,
            ) as response,
        ):
            response.raise_for_status()
            written = 0
            with destination.open("xb") as handle:
                for chunk in response.iter_bytes(1 << 16):
                    written += len(chunk)
                    if written > requirement.max_compressed_bytes:
                        raise DataUnavailableError("immutable HPO bundle exceeds its size limit")
                    hasher.update(chunk)
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
    except (DownloadError, httpx.HTTPError, OSError) as exc:
        if isinstance(exc, DataUnavailableError):
            raise
        raise DataUnavailableError("immutable HPO bundle download failed") from exc
    if hasher.hexdigest() != requirement.compressed_sha256:
        raise DataUnavailableError("immutable HPO bundle digest verification failed")


def _verify_database(requirement: ImmutableDataRequirement, database: Path) -> None:
    """Verify database format, immutable-tree identity, and HPO metadata."""
    with database.open("rb") as handle:
        header = handle.read(len(_SQLITE_HEADER))
    if header != _SQLITE_HEADER:
        raise DataUnavailableError("immutable HPO bundle is not a SQLite database")
    os.chmod(database, 0o444)
    if canonical_tree_sha256(database) != requirement.expanded_tree_sha256:
        raise DataUnavailableError("immutable HPO expanded-tree verification failed")
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
        try:
            row = connection.execute(
                "SELECT schema_version, hpo_version, hpoa_version FROM meta WHERE id = 1"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise DataUnavailableError("immutable HPO bundle metadata verification failed") from exc
    if row != (requirement.schema_version, requirement.hpo_version, requirement.hpoa_version):
        raise DataUnavailableError("immutable HPO bundle metadata verification failed")


def _write_identity(requirement: ImmutableDataRequirement, staging: Path) -> None:
    """Write the small, audited identity record before selecting the snapshot."""
    identity = {
        "compressed_sha256": requirement.compressed_sha256,
        "expanded_tree_sha256": requirement.expanded_tree_sha256,
        "schema_version": requirement.schema_version,
        "hpo_version": requirement.hpo_version,
        "hpoa_version": requirement.hpoa_version,
    }
    temporary = staging / ".identity.json.tmp"
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(identity, handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    identity_path = staging / "identity.json"
    os.replace(temporary, identity_path)
    os.chmod(identity_path, 0o444)
    _fsync(identity_path)


def _select_snapshot(requirement: ImmutableDataRequirement, staging: Path) -> Path:
    """Atomically publish the verified digest directory and ``current`` link."""
    root = requirement.reference_root
    target = root / requirement.compressed_sha256
    database = staging / "hpo.sqlite"
    if target.exists():
        identity_path = target / "identity.json"
        try:
            identity = json.loads(identity_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataUnavailableError(
                "immutable HPO existing snapshot verification failed"
            ) from exc
        expected_identity = {
            "compressed_sha256": requirement.compressed_sha256,
            "expanded_tree_sha256": requirement.expanded_tree_sha256,
            "schema_version": requirement.schema_version,
            "hpo_version": requirement.hpo_version,
            "hpoa_version": requirement.hpoa_version,
        }
        existing_database = target / database.name
        if identity != expected_identity or not existing_database.is_file():
            raise DataUnavailableError("immutable HPO existing snapshot verification failed")
        if canonical_tree_sha256(existing_database) != requirement.expanded_tree_sha256:
            raise DataUnavailableError("immutable HPO existing snapshot verification failed")
        shutil.rmtree(staging)
    else:
        os.replace(staging, target)
    next_current = root / f".current-{os.getpid()}"
    next_current.symlink_to(requirement.compressed_sha256)
    os.replace(next_current, root / "current")
    _fsync(root)
    return target / database.name


def materialize_immutable_data(requirement: ImmutableDataRequirement) -> Path:
    """Fetch, verify, and atomically select the one reviewed HPO bundle.

    An existing ``current`` link is not changed until every byte, metadata field,
    and canonical tree identity has passed.  The function is intended only for
    the short-lived init sidecar; application start paths never call it.
    """
    root = requirement.reference_root
    root.mkdir(mode=0o755, parents=True, exist_ok=True)
    staging = root / f".{requirement.compressed_sha256}.staging-{os.getpid()}"
    lock_path = root / ".materialize.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(mode=0o700)
            compressed = staging / "hpo.sqlite.zst"
            _download_bundle(requirement, compressed)
            database = staging / "hpo.sqlite"
            try:
                with (
                    compressed.open("rb") as source,
                    database.open("xb") as destination,
                    zstandard.ZstdDecompressor().stream_reader(source) as stream,
                ):
                    copy_bounded(stream, destination, max_bytes=requirement.max_expanded_bytes)
                    destination.flush()
                    os.fsync(destination.fileno())
            except (OSError, zstandard.ZstdError, DownloadError) as exc:
                raise DataUnavailableError("immutable HPO bundle decompression failed") from exc
            compressed.unlink()
            _verify_database(requirement, database)
            _write_identity(requirement, staging)
            _fsync(database)
            _fsync(staging)
            return _select_snapshot(requirement, staging)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
