"""Regression tests for published HPO data-release identity decisions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hpo_link.exceptions import DownloadError
from hpo_link.ingest.release_identity import classify_existing_release

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "releases" / "hpo_db_v2026_06_23.json"


def _legacy_release() -> dict[str, object]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_only_the_audited_legacy_release_can_noop() -> None:
    """The pre-standard release is accepted only after its full known identity matches."""
    assert classify_existing_release(_legacy_release()) == "legacy_verified_noop"


@pytest.mark.parametrize("field", ["bundle_sha256", "manifest", "assets"])
def test_legacy_identity_mismatch_is_a_collision(field: str) -> None:
    """A changed legacy invariant must never be mistaken for a safe existing release."""
    release = _legacy_release()
    if field == "bundle_sha256":
        release[field] = "0" * 64
    elif field == "manifest":
        release[field] = {**release[field], "sqlite_bytes": 1}  # type: ignore[index]
    else:
        release[field] = ["manifest.json"]

    with pytest.raises(DownloadError, match="legacy release identity mismatch"):
        classify_existing_release(release)


def test_any_other_release_is_not_eligible_for_legacy_noop() -> None:
    release = _legacy_release()
    release["tag"] = "db-v2026-06-24"

    assert classify_existing_release(release) == "published_noop"
