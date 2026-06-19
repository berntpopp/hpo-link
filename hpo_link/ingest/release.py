"""Prebuilt-database artifact discovery and fetch for hpo-link.

Queries the hpo-link GitHub Releases API for ``db-v*`` tags, retrieves the
manifest, verifies the sha256 of the compressed artifact, and decompresses it
to the final destination path atomically.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog
import zstandard

from hpo_link.constants import GITHUB_DB_OWNER_REPO

logger = structlog.get_logger()

_CHUNK_SIZE = 1 << 16
_GH_RELEASES_URL = "https://api.github.com/repos/{owner_repo}/releases"


@dataclass(frozen=True)
class PrebuiltAsset:
    """Metadata for a published prebuilt HPO SQLite artifact."""

    hpo_version: str
    download_url: str
    sha256: str
    zst_bytes: int


def find_prebuilt_asset(
    client: httpx.Client,
    *,
    owner_repo: str = GITHUB_DB_OWNER_REPO,
    want_version: str | None = None,
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
        resp = client.get(url, headers={"Accept": "application/vnd.github+json"})
        resp.raise_for_status()
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

    releases: list[dict[str, object]] = resp.json()

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

    _ = zst_name  # captured for logging only

    # Fetch the manifest
    try:
        mresp = client.get(manifest_url)
        mresp.raise_for_status()
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

    manifest: dict[str, object] = mresp.json()

    hpo_version = str(manifest.get("hpo_version", ""))
    sha256 = str(manifest.get("sha256", ""))
    zst_bytes_raw = manifest.get("zst_bytes")
    zst_bytes = int(zst_bytes_raw) if isinstance(zst_bytes_raw, (int, float, str)) else 0

    if not hpo_version or not sha256:
        logger.warning("manifest_missing_fields", manifest=manifest)
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
    )


def fetch_prebuilt_db(
    client: httpx.Client,
    asset: PrebuiltAsset,
    dest: Path,
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
    from hpo_link.exceptions import DataUnavailableError, DownloadError

    dest.parent.mkdir(parents=True, exist_ok=True)

    # Download the .zst to a temp file
    fd_zst, tmp_zst_name = tempfile.mkstemp(dir=dest.parent, suffix=".sqlite.zst.tmp")
    os.close(fd_zst)
    tmp_zst = Path(tmp_zst_name)

    hasher = hashlib.sha256()
    try:
        try:
            with client.stream("GET", asset.download_url) as response:
                response.raise_for_status()
                with tmp_zst.open("wb") as fh:
                    for chunk in response.iter_bytes(_CHUNK_SIZE):
                        fh.write(chunk)
                        hasher.update(chunk)
        except httpx.HTTPStatusError as exc:
            raise DownloadError(
                f"GET {asset.download_url} failed: {exc.response.status_code}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.HTTPError as exc:
            raise DownloadError(f"GET {asset.download_url} failed: {exc}") from exc

        actual_sha256 = hasher.hexdigest()
        if actual_sha256 != asset.sha256:
            tmp_zst.unlink(missing_ok=True)
            raise DataUnavailableError(
                f"Prebuilt DB sha256 mismatch: expected {asset.sha256}, got {actual_sha256}"
            )

        logger.info("prebuilt_db_sha256_ok", sha256=actual_sha256[:16] + "...")

        # Decompress .zst to a second temp file, then atomic-replace dest
        fd_db, tmp_db_name = tempfile.mkstemp(dir=dest.parent, suffix=".sqlite.tmp")
        os.close(fd_db)
        tmp_db = Path(tmp_db_name)
        try:
            dctx = zstandard.ZstdDecompressor()
            with tmp_zst.open("rb") as src, tmp_db.open("wb") as dst:
                dctx.copy_stream(src, dst)
            os.replace(tmp_db, dest)
        except Exception:
            tmp_db.unlink(missing_ok=True)
            raise
    finally:
        tmp_zst.unlink(missing_ok=True)

    logger.info("prebuilt_db_placed", dest=str(dest))
    return dest
