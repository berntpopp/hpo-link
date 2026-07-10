"""Conditional download of the HPO OBO JSON + HPOA release files.

The OBO PURL serves HPO releases at version-pinned URLs. We resolve the latest
version from the GitHub API, then issue conditional GET requests using
``ETag`` / ``Last-Modified`` validators cached between runs so a re-download
only transfers a body when the upstream release actually changed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import structlog

from hpo_link.constants import GITHUB_RELEASES_LATEST_URL, obo_purl
from hpo_link.exceptions import DownloadError
from hpo_link.ingest.download_security import (
    DownloadPolicy,
    open_validated_stream,
    read_bounded,
    stream_atomic,
)

if TYPE_CHECKING:
    from hpo_link.config import ServerSettings

logger = structlog.get_logger()

CACHE_FILENAME = "download_cache.json"
_METADATA_MAX_BYTES = 64 * 1024
HPO_SOURCE_POLICY = DownloadPolicy(
    allowed_hosts=frozenset(
        {"purl.obolibrary.org", "github.com", "release-assets.githubusercontent.com"}
    ),
    max_redirects=5,
)


@dataclass
class DownloadResult:
    """Outcome of a conditional download of one release file."""

    key: str
    path: Path | None = None
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False
    content_length: int | None = None


def resolve_latest_version(client: httpx.Client, *, max_bytes: int = _METADATA_MAX_BYTES) -> str:
    """Resolve the latest HPO release tag from the GitHub Releases API.

    Returns the tag name with a leading ``v`` stripped (e.g. ``"2026-06-06"``).
    Raises :class:`DownloadError` on any HTTP or network failure.
    """
    try:
        with client.stream("GET", GITHUB_RELEASES_LATEST_URL, follow_redirects=False) as resp:
            if resp.is_redirect:
                raise DownloadError("GitHub Releases API redirect is not allowed")
            resp.raise_for_status()
            raw = read_bounded(resp, max_bytes=max_bytes)
    except httpx.HTTPStatusError as exc:
        raise DownloadError(
            f"GitHub Releases API failed: {exc.response.status_code}",
            status_code=exc.response.status_code,
        ) from exc
    except httpx.HTTPError as exc:
        raise DownloadError(f"GitHub Releases API failed: {exc}") from exc
    try:
        data: dict[str, str] = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise DownloadError("GitHub Releases API returned invalid JSON") from exc
    return data["tag_name"].lstrip("v")


def _cache_path(config: ServerSettings) -> Path:
    return config.data.data_dir / CACHE_FILENAME


def _read_cache(config: ServerSettings) -> dict[str, dict[str, str | None]]:
    p = _cache_path(config)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_cache(
    config: ServerSettings,
    url: str,
    *,
    etag: str | None,
    last_modified: str | None,
) -> None:
    p = _cache_path(config)
    data = _read_cache(config)
    data[url] = {"etag": etag, "last_modified": last_modified}
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def download_file(
    client: httpx.Client,
    url: str,
    dest: Path,
    *,
    force: bool,
    cached_validators: dict[str, str | None],
    config: ServerSettings,
) -> DownloadResult:
    """Conditionally download ``url`` to ``dest``.

    Sends ``If-None-Match`` / ``If-Modified-Since`` from ``cached_validators``
    unless ``force``. A 304 reuses the existing local file.
    """
    key = dest.name
    headers: dict[str, str] = {"User-Agent": config.data.user_agent}
    if not force:
        if cached_validators.get("etag"):
            headers["If-None-Match"] = str(cached_validators["etag"])
        if cached_validators.get("last_modified"):
            headers["If-Modified-Since"] = str(cached_validators["last_modified"])

    try:
        policy = DownloadPolicy(
            allowed_hosts=HPO_SOURCE_POLICY.allowed_hosts,
            max_redirects=HPO_SOURCE_POLICY.max_redirects,
            max_bytes=config.data.max_source_bytes,
            max_seconds=config.data.max_download_seconds,
        )
        with open_validated_stream(client, url, headers=headers, policy=policy) as response:
            if response.status_code == httpx.codes.NOT_MODIFIED:
                logger.info("not_modified", url=url)
                return DownloadResult(
                    key=key,
                    path=dest if dest.exists() else None,
                    etag=headers.get("If-None-Match"),
                    last_modified=headers.get("If-Modified-Since"),
                    not_modified=True,
                )
            response.raise_for_status()
            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")
            content_length = _int_or_none(response.headers.get("Content-Length"))
            # Log the filename only — not the full local path or source URL.
            logger.info("downloading", file=dest.name)
            stream_atomic(
                response,
                dest,
                max_bytes=config.data.max_source_bytes,
                max_seconds=config.data.max_download_seconds,
            )
    except httpx.HTTPStatusError as exc:
        raise DownloadError(
            f"GET {url} failed: {exc.response.status_code}",
            status_code=exc.response.status_code,
        ) from exc
    except httpx.HTTPError as exc:
        raise DownloadError(f"GET {url} failed: {exc}") from exc

    _write_cache(config, url, etag=etag, last_modified=last_modified)
    return DownloadResult(
        key=key,
        path=dest,
        etag=etag,
        last_modified=last_modified,
        not_modified=False,
        content_length=content_length,
    )


def _validators_from_results(
    results: dict[str, DownloadResult],
) -> dict[str, dict[str, str | None]]:
    """Return per-key ``{etag, last_modified}`` dicts for provenance."""
    return {k: {"etag": r.etag, "last_modified": r.last_modified} for k, r in results.items()}


def download_bulk(config: ServerSettings, *, force: bool = False) -> dict[str, DownloadResult]:
    """Resolve the latest HPO release and download all required files.

    Returns a ``dict`` keyed by:
    - ``"ontology"`` - hp.json (or hp-base.json)
    - ``"phenotype_hpoa"`` - phenotype.hpoa
    - ``"genes_to_phenotype"`` - genes_to_phenotype.txt
    - ``"genes_to_disease"`` - genes_to_disease.txt
    """
    data_dir = config.data.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(follow_redirects=False, timeout=config.data.download_timeout) as client:
        version = resolve_latest_version(client, max_bytes=config.data.max_manifest_bytes)
        logger.info("resolved_hpo_version", version=version)

        file_map: dict[str, str] = {
            "ontology": config.data.ontology_edition,
            "phenotype_hpoa": "phenotype.hpoa",
            "genes_to_phenotype": "genes_to_phenotype.txt",
            "genes_to_disease": "genes_to_disease.txt",
        }
        cache = _read_cache(config)
        results: dict[str, DownloadResult] = {}

        for key, filename in file_map.items():
            url = obo_purl(version, filename)
            dest = data_dir / filename
            cached_validators: dict[str, str | None] = cache.get(url, {})
            results[key] = download_file(
                client,
                url,
                dest,
                force=force,
                cached_validators=cached_validators,
                config=config,
            )

    return results
