"""Tests for hpo_link.ingest.downloader."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from structlog.testing import capture_logs

from hpo_link.constants import GITHUB_RELEASES_LATEST_URL
from hpo_link.exceptions import DownloadError
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


@respx.mock
def test_purl_chain_allows_github_asset_host(tmp_path: Path) -> None:
    purl = "https://purl.obolibrary.org/obo/hp/releases/2026-06-06/hp.json"
    github = "https://github.com/obophenotype/human-phenotype-ontology/releases/download/v1/hp.json"
    asset = "https://release-assets.githubusercontent.com/asset?id=1"
    respx.get(purl).mock(return_value=httpx.Response(302, headers={"Location": github}))
    respx.get(github).mock(return_value=httpx.Response(302, headers={"Location": asset}))
    respx.get(asset).mock(return_value=httpx.Response(200, content=b"{}"))
    cfg = _settings(tmp_path)
    cfg.data.max_source_bytes = 8  # type: ignore[attr-defined]

    with httpx.Client(follow_redirects=False) as client:
        result = download_file(
            client,
            purl,
            tmp_path / "hp.json",
            force=True,
            cached_validators={},
            config=cfg,  # type: ignore[arg-type]
        )

    assert result.path == tmp_path / "hp.json"
    assert result.path.read_bytes() == b"{}"


@respx.mock
def test_purl_chain_blocks_intermediate_host_before_request(tmp_path: Path) -> None:
    purl = "https://purl.obolibrary.org/start"
    blocked_url = "https://169.254.169.254/latest/meta-data"
    blocked = respx.get(blocked_url).mock(return_value=httpx.Response(200))
    respx.get(purl).mock(return_value=httpx.Response(302, headers={"Location": blocked_url}))

    with (
        httpx.Client(follow_redirects=False) as client,
        pytest.raises(DownloadError, match="not allowed"),
    ):
        download_file(
            client,
            purl,
            tmp_path / "hp.json",
            force=True,
            cached_validators={},
            config=_settings(tmp_path),  # type: ignore[arg-type]
        )

    assert blocked.called is False


@respx.mock
def test_source_stream_limit_preserves_existing_file(tmp_path: Path) -> None:
    url = "https://purl.obolibrary.org/source"
    destination = tmp_path / "hp.json"
    destination.write_bytes(b"old-valid")
    cfg = _settings(tmp_path)
    cfg.data.max_source_bytes = 8  # type: ignore[attr-defined]
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            headers={"Content-Length": "1"},
            content=b"123456789",
        )
    )

    with (
        httpx.Client(follow_redirects=False) as client,
        pytest.raises(DownloadError, match="exceeded 8 bytes"),
    ):
        download_file(
            client,
            url,
            destination,
            force=True,
            cached_validators={},
            config=cfg,  # type: ignore[arg-type]
        )

    assert destination.read_bytes() == b"old-valid"
    assert list(tmp_path.glob("*.download.tmp")) == []
