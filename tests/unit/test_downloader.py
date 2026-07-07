"""Tests for hpo_link.ingest.downloader."""

from __future__ import annotations

from pathlib import Path

import httpx
import respx
from structlog.testing import capture_logs

from hpo_link.constants import GITHUB_RELEASES_LATEST_URL
from hpo_link.ingest.downloader import download_file, resolve_latest_version


def _settings(tmp_path: Path) -> object:
    """Minimal ServerSettings pointing at tmp_path (mirrors test_builder)."""
    from hpo_link.config import HPODataConfig, ServerSettings

    return ServerSettings.model_construct(data=HPODataConfig(data_dir=tmp_path))


@respx.mock
def test_resolve_latest_version() -> None:
    respx.get(GITHUB_RELEASES_LATEST_URL).mock(
        return_value=httpx.Response(200, json={"tag_name": "v2026-06-06"})
    )
    with httpx.Client() as c:
        assert resolve_latest_version(c) == "2026-06-06"


@respx.mock
def test_download_file_logs_basename_not_full_path_or_url(tmp_path: Path) -> None:
    """Guard (PII/path hygiene): the 'downloading' event logs the filename only.

    The full local path (deployment-layout disclosure) and the source URL must
    not appear in structured log fields.
    """
    url = "https://purl.obolibrary.org/obo/hp/releases/2026-06-06/hp.json"
    dest = tmp_path / "hp.json"
    respx.get(url).mock(return_value=httpx.Response(200, content=b"{}"))

    with httpx.Client() as client, capture_logs() as logs:
        download_file(
            client,
            url,
            dest,
            force=True,
            cached_validators={},
            config=_settings(tmp_path),  # type: ignore[arg-type]
        )

    downloading = [e for e in logs if e.get("event") == "downloading"]
    assert downloading, f"no 'downloading' event captured: {logs}"
    event = downloading[0]
    assert event.get("file") == "hp.json"
    # Neither the full local path nor the source URL may leak into log fields.
    assert str(dest) not in str(event)
    assert url not in str(event)
