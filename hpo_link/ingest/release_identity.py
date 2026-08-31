"""Fail-closed identity checks for existing HPO database releases.

The first HPO database release predates the standard ``SHA256SUMS`` and
attestation contract.  Its one audited tuple is therefore deliberately kept in
code rather than treating a successful GitHub release lookup as proof that a
rerun may publish nothing.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, cast

from hpo_link.exceptions import DownloadError

ReleaseState = Literal["legacy_verified_noop", "published_noop"]

_LEGACY_TAG = "db-v2026-06-23"
_LEGACY_ASSETS = frozenset(
    {
        "hpo-2026-06-23.sqlite.zst",
        "hpo-2026-06-23.sqlite.zst.sha256",
        "manifest.json",
    }
)
_LEGACY_SHA256 = "d677a96efd8c274045241934c33b25dfb6fc9a6414c27bed7ae3334d05d4c9f6"
_LEGACY_MANIFEST: dict[str, object] = {
    "hpo_version": "2026-06-23",
    "hpoa_version": "2026-06-23",
    "schema_version": 1,
    "sqlite_zst": "hpo-2026-06-23.sqlite.zst",
    "sha256": _LEGACY_SHA256,
    "sqlite_bytes": 136249344,
    "zst_bytes": 19083660,
    "counts": {
        "term_count": 20413,
        "obsolete_count": 577,
        "closure_count": 222576,
        "xref_count": 18063,
        "disease_phenotype_count": 285598,
        "gene_phenotype_count": 332599,
        "gene_disease_count": 15944,
    },
}


def _is_exact_legacy_identity(release: Mapping[str, object]) -> bool:
    """Return whether a release matches every immutable pre-standard invariant."""
    assets = release.get("assets")
    if not isinstance(assets, Sequence) or isinstance(assets, str):
        return False
    if any(not isinstance(asset, str) for asset in assets):
        return False
    checksum = release.get("checksum")
    manifest = release.get("manifest")
    if not isinstance(manifest, Mapping):
        return False
    stable_manifest = {key: value for key, value in manifest.items() if key != "built_utc"}
    return (
        release.get("tag") == _LEGACY_TAG
        and frozenset(cast(Sequence[str], assets)) == _LEGACY_ASSETS
        and release.get("bundle_sha256") == _LEGACY_SHA256
        and checksum == f"{_LEGACY_SHA256}\n"
        and stable_manifest == _LEGACY_MANIFEST
        and isinstance(manifest.get("built_utc"), str)
    )


def classify_existing_release(release: Mapping[str, object]) -> ReleaseState:
    """Classify a verified existing release without allowing ambiguous legacy skips.

    Callers must validate the full modern asset/checksum/attestation contract
    before using ``published_noop``.  The sole legacy release is additionally
    checked here because it cannot satisfy the modern contract by design.
    """
    tag = release.get("tag")
    if not isinstance(tag, str) or not tag:
        raise DownloadError("release identity requires a tag")
    if tag != _LEGACY_TAG:
        return "published_noop"
    if not _is_exact_legacy_identity(release):
        raise DownloadError("legacy release identity mismatch")
    return "legacy_verified_noop"


def verify_legacy_release(release_dir: Path) -> ReleaseState:
    """Verify the complete audited legacy tuple downloaded from GitHub Releases.

    This deliberately validates bytes, not GitHub's release metadata: the
    historical release predates provenance attestations and is eligible for a
    no-op only under its frozen, independently audited contract.
    """
    bundle = release_dir / "hpo-2026-06-23.sqlite.zst"
    checksum_path = release_dir / "hpo-2026-06-23.sqlite.zst.sha256"
    manifest_path = release_dir / "manifest.json"
    names = {path.name for path in release_dir.iterdir() if path.is_file()}
    try:
        manifest_bytes = manifest_path.read_bytes()
        checksum = checksum_path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as exc:
        raise DownloadError("legacy release identity mismatch") from exc
    if len(manifest_bytes) > 1024 * 1024:
        raise DownloadError("legacy release identity mismatch")
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise DownloadError("legacy release identity mismatch") from exc
    if bundle.is_file():
        with bundle.open("rb") as bundle_file:
            bundle_sha256 = hashlib.file_digest(bundle_file, "sha256").hexdigest()
    else:
        bundle_sha256 = ""
    return classify_existing_release(
        {
            "tag": _LEGACY_TAG,
            "assets": sorted(names),
            "bundle_sha256": bundle_sha256,
            "checksum": checksum,
            "manifest": manifest,
        }
    )
