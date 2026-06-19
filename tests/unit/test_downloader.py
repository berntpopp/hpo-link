"""Tests for hpo_link.ingest.downloader."""

from __future__ import annotations

import httpx
import respx

from hpo_link.constants import GITHUB_RELEASES_LATEST_URL
from hpo_link.ingest.downloader import resolve_latest_version


@respx.mock
def test_resolve_latest_version() -> None:
    respx.get(GITHUB_RELEASES_LATEST_URL).mock(
        return_value=httpx.Response(200, json={"tag_name": "v2026-06-06"})
    )
    with httpx.Client() as c:
        assert resolve_latest_version(c) == "2026-06-06"
