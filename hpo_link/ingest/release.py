"""Prebuilt-database artifact discovery and fetch for hpo-link.

Queries the hpo-link GitHub Releases API for ``db-v*`` tags, retrieves the
manifest, verifies the sha256 of the compressed artifact, and decompresses it
to the final destination path atomically.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog
import zstandard

from hpo_link.constants import GITHUB_DB_OWNER_REPO
from hpo_link.exceptions import DataUnavailableError, DownloadError
from hpo_link.ingest.download_security import (
    DownloadPolicy,
    copy_bounded,
    open_validated_stream,
    read_bounded,
    stream_atomic,
    validate_https_url,
)

logger = structlog.get_logger()

_GH_RELEASES_URL = "https://api.github.com/repos/{owner_repo}/releases"
_DEFAULT_MANIFEST_BYTES = 64 * 1024
_DEFAULT_BUNDLE_BYTES = 128 * 1024 * 1024
_DEFAULT_DATABASE_BYTES = 512 * 1024 * 1024
_GITHUB_API_POLICY = DownloadPolicy(allowed_hosts=frozenset({"api.github.com"}), max_redirects=0)
_GITHUB_ASSET_POLICY = DownloadPolicy(
    allowed_hosts=frozenset({"github.com", "release-assets.githubusercontent.com"}),
    max_redirects=5,
)
_SQLITE_HEADER = b"SQLite format 3\x00"


@dataclass(frozen=True)
class PrebuiltAsset:
    """Metadata for a published prebuilt HPO SQLite artifact."""

    hpo_version: str
    download_url: str
    sha256: str
    zst_bytes: int
    sqlite_bytes: int


def _read_direct_metadata(
    client: httpx.Client,
    url: str,
    *,
    headers: dict[str, str],
    max_bytes: int,
) -> bytes:
    """Read bounded GitHub API metadata without accepting redirects."""
    target = httpx.URL(url)
    validate_https_url(target, _GITHUB_API_POLICY)
    request = client.build_request("GET", target, headers=headers)
    response = client.send(request, stream=True, follow_redirects=False)
    try:
        if response.is_redirect:
            raise DownloadError("GitHub API redirect is not allowed")
        response.raise_for_status()
        return read_bounded(response, max_bytes=max_bytes)
    finally:
        response.close()


def _read_asset_metadata(client: httpx.Client, url: str, *, max_bytes: int) -> bytes:
    """Read bounded release metadata through the validated GitHub asset chain."""
    with open_validated_stream(
        client,
        url,
        headers={"Accept": "application/json"},
        policy=_GITHUB_ASSET_POLICY,
    ) as response:
        response.raise_for_status()
        return read_bounded(response, max_bytes=max_bytes)


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return 0
    try:
        parsed = int(value)
    except (OverflowError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def find_prebuilt_asset(
    client: httpx.Client,
    *,
    owner_repo: str = GITHUB_DB_OWNER_REPO,
    want_version: str | None = None,
    max_manifest_bytes: int = _DEFAULT_MANIFEST_BYTES,
    max_bundle_bytes: int = _DEFAULT_BUNDLE_BYTES,
    max_database_bytes: int = _DEFAULT_DATABASE_BYTES,
) -> PrebuiltAsset | None:
    """Return the best matching ``PrebuiltAsset`` from GitHub Releases, or ``None``.

    Fetches the list of releases for *owner_repo*, filters to tags starting with
    ``db-v``, picks the release whose DATE suffix equals *want_version* (when
    given) or the newest tag otherwise, then fetches its ``manifest.json`` and
    returns a :class:`PrebuiltAsset`.

    Returns ``None`` when no ``db-v*`` release or required assets are found.
    """
    url = _GH_RELEASES_URL.format(owner_repo=owner_repo)
    try:
        raw_releases = _read_direct_metadata(
            client,
            url,
            headers={"Accept": "application/vnd.github+json"},
            max_bytes=max_manifest_bytes,
        )
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "github_releases_http_error",
            url=url,
            status=exc.response.status_code,
        )
        return None
    except httpx.HTTPError as exc:
        logger.warning("github_releases_network_error", url=url, error=str(exc))
        return None
    except DownloadError as exc:
        logger.warning("github_releases_invalid", url=url, error=str(exc))
        return None

    try:
        parsed_releases = json.loads(raw_releases)
    except json.JSONDecodeError:
        logger.warning("github_releases_invalid_json", url=url)
        return None
    if not isinstance(parsed_releases, list):
        logger.warning("github_releases_invalid_shape", url=url)
        return None
    releases: list[dict[str, object]] = [
        release for release in parsed_releases if isinstance(release, dict)
    ]

    # Filter to db-v* tags only
    db_releases = [
        r
        for r in releases
        if isinstance(r.get("tag_name"), str) and str(r["tag_name"]).startswith("db-v")
    ]
    if not db_releases:
        logger.info("no_db_releases_found", owner_repo=owner_repo)
        return None

    # Select by want_version or newest (tags are lexicographically ordered; first = newest)
    selected: dict[str, object] | None = None
    if want_version is not None:
        for release in db_releases:
            tag = str(release["tag_name"])
            # tag is db-v{DATE}, so DATE = tag[4:]
            if tag[4:] == want_version:
                selected = release
                break
        if selected is None:
            logger.info(
                "no_db_release_for_version", want_version=want_version, owner_repo=owner_repo
            )
            return None
    else:
        # Pick the one with the latest tag (releases list is newest-first from GitHub)
        selected = db_releases[0]

    # Locate manifest.json and the .zst asset in the selected release
    raw_assets = selected.get("assets", [])
    assets: list[dict[str, object]] = list(raw_assets) if isinstance(raw_assets, list) else []

    manifest_url: str | None = None
    zst_url: str | None = None
    zst_name: str | None = None
    for asset in assets:
        name = str(asset.get("name", ""))
        dl_url = str(asset.get("browser_download_url", ""))
        if name == "manifest.json":
            manifest_url = dl_url
        elif name.endswith(".sqlite.zst") and not name.endswith(".sha256"):
            zst_url = dl_url
            zst_name = name

    if manifest_url is None or zst_url is None:
        tag = str(selected.get("tag_name", "?"))
        logger.warning(
            "prebuilt_assets_incomplete",
            tag=tag,
            manifest_found=manifest_url is not None,
            zst_found=zst_url is not None,
        )
        return None

    # Fetch the manifest
    try:
        raw_manifest = _read_asset_metadata(client, manifest_url, max_bytes=max_manifest_bytes)
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "manifest_http_error",
            manifest_url=manifest_url,
            status=exc.response.status_code,
        )
        return None
    except httpx.HTTPError as exc:
        logger.warning("manifest_network_error", manifest_url=manifest_url, error=str(exc))
        return None
    except DownloadError as exc:
        logger.warning("manifest_invalid_download", manifest_url=manifest_url, error=str(exc))
        return None

    try:
        parsed_manifest = json.loads(raw_manifest)
    except json.JSONDecodeError:
        logger.warning("manifest_invalid_json")
        return None
    if not isinstance(parsed_manifest, dict):
        logger.warning("manifest_invalid_shape")
        return None
    manifest: dict[str, object] = parsed_manifest

    hpo_version = str(manifest.get("hpo_version", ""))
    sqlite_zst = str(manifest.get("sqlite_zst", ""))
    sha256 = str(manifest.get("sha256", ""))
    zst_bytes = _positive_int(manifest.get("zst_bytes"))
    sqlite_bytes = _positive_int(manifest.get("sqlite_bytes"))

    if not hpo_version:
        # Log only fixed field-presence metadata — never the parsed upstream manifest,
        # whose values are attacker-influenceable and can carry hostile text / bidi / NUL.
        logger.warning(
            "manifest_missing_fields",
            has_hpo_version=bool(hpo_version),
            has_sqlite_zst=bool(sqlite_zst),
            has_sha256=bool(sha256),
        )
        return None
    selected_tag = str(selected.get("tag_name", ""))
    if hpo_version != selected_tag[4:] or sqlite_zst != zst_name:
        logger.warning("manifest_release_mismatch")
        return None
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        logger.warning("manifest_invalid_sha256")
        return None
    if zst_bytes <= 0 or sqlite_bytes <= 0:
        logger.warning("manifest_invalid_sizes")
        return None
    if zst_bytes > max_bundle_bytes or sqlite_bytes > max_database_bytes:
        logger.warning(
            "manifest_sizes_exceed_limits",
            zst_bytes=zst_bytes,
            sqlite_bytes=sqlite_bytes,
        )
        return None

    logger.info(
        "prebuilt_asset_found",
        hpo_version=hpo_version,
        sha256=sha256[:16] + "...",
        zst_bytes=zst_bytes,
    )
    return PrebuiltAsset(
        hpo_version=hpo_version,
        download_url=zst_url,
        sha256=sha256,
        zst_bytes=zst_bytes,
        sqlite_bytes=sqlite_bytes,
    )


def fetch_prebuilt_db(
    client: httpx.Client,
    asset: PrebuiltAsset,
    dest: Path,
    *,
    max_compressed_bytes: int = _DEFAULT_BUNDLE_BYTES,
    max_db_bytes: int = _DEFAULT_DATABASE_BYTES,
    max_download_seconds: float | None = None,
) -> Path:
    """Download, verify, decompress, and atomically place the prebuilt DB.

    Downloads the ``.zst`` artifact to a temp file, computes its sha256,
    raises :class:`~hpo_link.exceptions.DataUnavailableError` on mismatch,
    decompresses with ``zstandard``, then atomically replaces *dest*.

    Args:
        client: An :class:`httpx.Client` for HTTP requests.
        asset:  The :class:`PrebuiltAsset` to download.
        dest:   Target path for the decompressed SQLite database.

    Returns:
        *dest* on success.

    Raises:
        DataUnavailableError: When the downloaded sha256 does not match.
        DownloadError: When the HTTP request fails.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if asset.zst_bytes > max_compressed_bytes:
        raise DataUnavailableError(f"compressed artifact exceeded {max_compressed_bytes} bytes")
    if asset.sqlite_bytes > max_db_bytes:
        raise DataUnavailableError(f"expanded artifact exceeded {max_db_bytes} bytes")

    # Download the .zst to a temp file
    fd_zst, tmp_zst_name = tempfile.mkstemp(dir=dest.parent, suffix=".sqlite.zst.tmp")
    os.close(fd_zst)
    tmp_zst = Path(tmp_zst_name)

    hasher = hashlib.sha256()
    try:
        try:
            policy = DownloadPolicy(
                allowed_hosts=_GITHUB_ASSET_POLICY.allowed_hosts,
                max_redirects=_GITHUB_ASSET_POLICY.max_redirects,
                max_bytes=max_compressed_bytes,
                max_seconds=max_download_seconds,
            )
            with open_validated_stream(
                client,
                asset.download_url,
                headers={"Accept": "application/octet-stream"},
                policy=policy,
            ) as response:
                response.raise_for_status()
                stream_atomic(
                    response,
                    tmp_zst,
                    max_bytes=max_compressed_bytes,
                    expected_size=asset.zst_bytes,
                    hasher=hasher,
                    max_seconds=max_download_seconds,
                )
        except httpx.HTTPStatusError as exc:
            raise DownloadError(
                f"GET {asset.download_url} failed: {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise DownloadError(f"GET {asset.download_url} failed: {exc}") from exc

        actual_sha256 = hasher.hexdigest()
        if actual_sha256.lower() != asset.sha256.lower():
            raise DataUnavailableError(
                f"Prebuilt DB sha256 mismatch: expected {asset.sha256}, got {actual_sha256}"
            )

        logger.info("prebuilt_db_sha256_ok", sha256=actual_sha256[:16] + "...")

        # Decompress .zst to a second temp file, then atomic-replace dest
        fd_db, tmp_db_name = tempfile.mkstemp(dir=dest.parent, suffix=".sqlite.tmp")
        tmp_db = Path(tmp_db_name)
        try:
            dctx = zstandard.ZstdDecompressor()
            with (
                os.fdopen(fd_db, "wb") as dst,
                tmp_zst.open("rb") as compressed,
                dctx.stream_reader(compressed) as src,
            ):
                try:
                    written = copy_bounded(src, dst, max_bytes=max_db_bytes)
                except DownloadError as exc:
                    raise DataUnavailableError(str(exc)) from exc
            if written != asset.sqlite_bytes:
                raise DataUnavailableError(
                    "Prebuilt DB expanded size mismatch: "
                    f"expected {asset.sqlite_bytes}, received {written}"
                )
            with tmp_db.open("rb") as handle:
                sqlite_header = handle.read(len(_SQLITE_HEADER))
            if sqlite_header != _SQLITE_HEADER:
                raise DataUnavailableError("Prebuilt DB has invalid SQLite header")
            os.replace(tmp_db, dest)
        except (OSError, zstandard.ZstdError) as exc:
            raise DataUnavailableError(f"Prebuilt DB decompression failed: {exc}") from exc
        finally:
            tmp_db.unlink(missing_ok=True)
    finally:
        tmp_zst.unlink(missing_ok=True)

    logger.info("prebuilt_db_placed", dest=str(dest))
    return dest
