"""Host/Origin boundary contracts for HPO's HTTP applications."""

from __future__ import annotations

import inspect
from importlib.metadata import version

import pytest
from fastapi.testclient import TestClient
from fastmcp import FastMCP
from packaging.version import Version

from hpo_link import server_manager
from hpo_link.config import ServerSettings, settings


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        settings,
        "allowed_hosts",
        ["localhost", "127.0.0.1", "::1", "hpo-link.genefoundry.org"],
    )
    monkeypatch.setattr(settings, "allowed_origins", ["https://genefoundry.org"])
    return TestClient(server_manager.create_unified_app(), raise_server_exceptions=False)


def test_fastmcp_344_guard_api_is_installed() -> None:
    assert Version(version("fastmcp")) >= Version("3.4.4")
    parameters = inspect.signature(FastMCP.http_app).parameters
    assert "host_origin_protection" in parameters
    assert "allowed_hosts" in parameters
    assert "allowed_origins" in parameters


@pytest.mark.parametrize("host", ["hpo-link.genefoundry.org", "hpo-link.genefoundry.org:443"])
def test_configured_public_host_is_allowed(client: TestClient, host: str) -> None:
    response = client.get("/mcp", headers={"Host": host})
    assert response.status_code not in {403, 421}


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_loopback_hosts_are_allowed(client: TestClient, host: str) -> None:
    response = client.get("/mcp", headers={"Host": host})
    assert response.status_code not in {403, 421}


@pytest.mark.parametrize("path", ["/", "/health", "/docs", "/mcp"])
def test_untrusted_host_is_rejected_on_every_route(client: TestClient, path: str) -> None:
    assert client.get(path, headers={"Host": "evil.example"}).status_code == 421


def test_absent_and_configured_origins_are_allowed(client: TestClient) -> None:
    no_origin = client.get("/mcp", headers={"Host": "hpo-link.genefoundry.org"})
    configured = client.get(
        "/mcp",
        headers={
            "Host": "hpo-link.genefoundry.org",
            "Origin": "https://genefoundry.org",
        },
    )
    assert no_origin.status_code not in {403, 421}
    assert configured.status_code not in {403, 421}


@pytest.mark.parametrize("path", ["/", "/health", "/docs", "/mcp"])
def test_untrusted_origin_is_rejected_on_every_route(client: TestClient, path: str) -> None:
    response = client.get(
        path,
        headers={
            "Host": "hpo-link.genefoundry.org",
            "Origin": "https://evil.example",
        },
    )
    assert response.status_code == 403


def test_untrusted_preflight_is_rejected_by_outer_guard(client: TestClient) -> None:
    response = client.options(
        "/health",
        headers={
            "Host": "evil.example",
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 421


def test_http_only_app_uses_the_same_outer_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "allowed_hosts", ["localhost"])
    monkeypatch.setattr(settings, "allowed_origins", [])
    http_client = TestClient(server_manager.create_http_app(), raise_server_exceptions=False)
    assert http_client.get("/health", headers={"Host": "evil.example"}).status_code == 421


@pytest.mark.parametrize("wildcard", ["*", "*.example.org", "host?.example.org", "host[0]"])
def test_wildcard_host_is_rejected(wildcard: str) -> None:
    with pytest.raises(ValueError, match="wildcard"):
        ServerSettings(_env_file=None, allowed_hosts=[wildcard])


def test_json_environment_allowlists_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "HPO_LINK_ALLOWED_HOSTS",
        '["localhost","hpo-link.genefoundry.org"]',
    )
    monkeypatch.setenv("HPO_LINK_ALLOWED_ORIGINS", '["https://genefoundry.org"]')

    configured = ServerSettings(_env_file=None)

    assert configured.allowed_hosts == ["localhost", "hpo-link.genefoundry.org"]
    assert configured.allowed_origins == ["https://genefoundry.org"]
