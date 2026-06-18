"""Conditional download of the Mondo OBO + SSSOM release files.

Monarch serves the Mondo releases on stable PURLs that honour ``ETag`` /
``Last-Modified``. We cache the last-seen validators per URL and issue
conditional ``GET`` requests, so a re-download only transfers a body when the
upstream release actually changed (a weekly cron check is then almost always a
cheap ``304``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from hpo_link.exceptions import DownloadError

if TYPE_CHECKING:
    from hpo_link.config import ServerSettings

logger = logging.getLogger(__name__)

#: Logical key -> local filename for the release files the index is built from.
REPORT_FILENAMES: dict[str, str] = {"obo": "mondo.obo", "sssom": "mondo.sssom.tsv"}

#: Supplementary keys: a download failure degrades gracefully (the index is still
#: built from the OBO, which already carries dbxrefs) rather than aborting.
OPTIONAL_KEYS: frozenset[str] = frozenset({"sssom"})

CACHE_FILENAME = "download_cache.json"
_CHUNK_SIZE = 1 << 16


@dataclass
class DownloadResult:
    """Outcome of a conditional download of one release file."""

    key: str
    path: Path | None = None
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False
    content_length: int | None = None


@dataclass
class BulkDownload:
    """Outcome of downloading a set of release files together."""

    results: dict[str, DownloadResult] = field(default_factory=dict)

    @property
    def not_modified(self) -> bool:
        """True only when every downloaded file returned ``304`` (nothing changed)."""
        return bool(self.results) and all(r.not_modified for r in self.results.values())

    def path(self, key: str) -> Path | None:
        """Local path for a release key (``None`` if not downloaded)."""
        res = self.results.get(key)
        return res.path if res is not None else None

    def validators(self) -> dict[str, dict[str, str | None]]:
        """Per-file ``{etag, last_modified}`` for provenance."""
        return {
            key: {"etag": r.etag, "last_modified": r.last_modified}
            for key, r in self.results.items()
        }


def _url_for(config: ServerSettings, key: str) -> str:
    urls = {"obo": config.data.obo_url, "sssom": config.data.sssom_url}
    return urls[key]


def _cache_path(config: ServerSettings) -> Path:
    return config.data.data_dir / CACHE_FILENAME


def _read_cache(config: ServerSettings) -> dict[str, dict[str, str | None]]:
    cache_path = _cache_path(config)
    if not cache_path.exists():
        return {}
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(
    config: ServerSettings, url: str, *, etag: str | None, last_modified: str | None
) -> None:
    cache_path = _cache_path(config)
    data = _read_cache(config)
    data[url] = {"etag": etag, "last_modified": last_modified}
    cache_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stream_to_file(response: httpx.Response, path: Path) -> None:
    with path.open("wb") as handle:
        for chunk in response.iter_bytes(_CHUNK_SIZE):
            handle.write(chunk)


def download_file(
    config: ServerSettings,
    key: str,
    *,
    force: bool = False,
) -> DownloadResult:
    """Conditionally download the release ``key`` to ``data_dir/<filename>``.

    Sends ``If-None-Match`` / ``If-Modified-Since`` from the cache unless
    ``force``. A ``304`` reuses the existing local file without a body transfer.
    """
    config.data.data_dir.mkdir(parents=True, exist_ok=True)
    url = _url_for(config, key)
    filename = REPORT_FILENAMES[key]
    dest = config.data.data_dir / filename
    headers = {"User-Agent": config.data.user_agent}
    if not force:
        cached = _read_cache(config).get(url, {})
        if cached.get("etag"):
            headers["If-None-Match"] = str(cached["etag"])
        if cached.get("last_modified"):
            headers["If-Modified-Since"] = str(cached["last_modified"])

    try:
        with (
            httpx.Client(follow_redirects=True, timeout=config.data.download_timeout) as client,
            client.stream("GET", url, headers=headers) as response,
        ):
            if response.status_code == httpx.codes.NOT_MODIFIED:
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
            _stream_to_file(response, dest)
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


def download_bulk(
    config: ServerSettings, *, keys: list[str] | None = None, force: bool = False
) -> BulkDownload:
    """Download the configured Mondo release files (conditionally unless ``force``)."""
    selected = keys if keys is not None else list(REPORT_FILENAMES)
    bulk = BulkDownload()
    for key in selected:
        try:
            bulk.results[key] = download_file(config, key, force=force)
        except DownloadError:
            if key not in OPTIONAL_KEYS:
                raise
            # Supplementary file unavailable: keep a previously-downloaded copy if
            # present, else proceed without it. Mark not_modified so a missing
            # optional file never forces a rebuild on its own.
            dest = config.data.data_dir / REPORT_FILENAMES[key]
            logger.warning(
                "optional_release_file_unavailable key=%s url=%s", key, _url_for(config, key)
            )
            bulk.results[key] = DownloadResult(
                key=key,
                path=dest if dest.exists() else None,
                not_modified=True,
            )
    return bulk
