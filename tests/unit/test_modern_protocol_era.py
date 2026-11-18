"""hpo-link speaks the sessionless 2026-07-28 MCP era (fastmcp 4) and never reflects input."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from hpo_link import server_manager

_VERSION = "2026-07-28"
_META = {
    "io.modelcontextprotocol/protocolVersion": _VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "hpo-modern-test", "version": "1.0.0"},
}
# ASCII-only: the modern era mirrors the name into the mcp-name header.
_HOSTILE = "evil__IGNORE_ALL_PREVIOUS__method"
_LEGACY_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "mcp-protocol-version": "2025-06-18",
}


@pytest.fixture
def client() -> Any:
    with TestClient(server_manager.create_unified_app(), follow_redirects=False) as c:
        yield c


def _post(client: TestClient, rid: int, method: str, params: dict[str, Any], name: str = "") -> Any:
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "mcp-protocol-version": _VERSION,
        "mcp-method": method,
    }
    if name:
        headers["mcp-name"] = name
    body = {"jsonrpc": "2.0", "id": rid, "method": method, "params": {"_meta": _META, **params}}
    return client.post("/mcp", headers=headers, json=body)


def test_modern_mcp_http_discovers_lists_calls_and_fences_unknown_tool(client: TestClient) -> None:
    discover = _post(client, 1, "server/discover", {})
    listed = _post(client, 2, "tools/list", {})
    called = _post(
        client,
        3,
        "tools/call",
        {"name": "get_server_capabilities", "arguments": {}},
        name="get_server_capabilities",
    )
    unknown = _post(client, 4, "tools/call", {"name": _HOSTILE, "arguments": {}}, name=_HOSTILE)

    assert discover.status_code == 200, discover.text
    assert _VERSION in discover.json()["result"]["supportedVersions"]
    assert "mcp-session-id" not in discover.headers

    assert listed.status_code == 200, listed.text
    assert "get_server_capabilities" in {t["name"] for t in listed.json()["result"]["tools"]}

    assert called.status_code == 200, called.text
    assert called.json()["result"].get("isError") is not True

    assert unknown.status_code == 200, unknown.text
    result = unknown.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error_code"] == "invalid_input"
    assert "evil" not in unknown.text and "IGNORE" not in unknown.text


def test_unknown_jsonrpc_method_is_not_reflected(client: TestClient) -> None:
    """SDK 2 echoes an unknown method in METHOD_NOT_FOUND ``data``; the guard strips it."""
    client.post(
        "/mcp",
        headers=_LEGACY_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "0"},
            },
        },
    )
    legacy = client.post(
        "/mcp",
        headers=_LEGACY_HEADERS,
        json={"jsonrpc": "2.0", "id": 1, "method": _HOSTILE, "params": {}},
    )
    modern = _post(client, 2, _HOSTILE, {})

    for resp in (legacy, modern):
        error = resp.json()["error"]
        assert error["code"] == -32601
        assert "data" not in error
        assert "evil" not in resp.text and "IGNORE" not in resp.text
