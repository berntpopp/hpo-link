"""Unit tests for the /health endpoint — Transport Standard v1 contract."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from hpo_link import __version__
from hpo_link.app import create_app


@pytest.fixture()
def client() -> TestClient:
    """Create a test client that skips the lifespan (no bootstrap needed)."""
    application = create_app()
    # raise_server_exceptions=True is the default; disable lifespan for unit isolation.
    return TestClient(application, raise_server_exceptions=True)


def test_health_returns_required_fields(client: TestClient) -> None:
    """GET /health must return {status, version, transport} per Transport Standard v1."""
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok", f"Expected status='ok', got: {body}"
    assert body["version"] == __version__, f"Expected version={__version__!r}, got: {body}"
    assert body["transport"] == "streamable-http-stateless", (
        f"Expected transport='streamable-http-stateless', got: {body}"
    )
