"""Stateless-tier construction guard (in-process, no server needed)."""

from __future__ import annotations

import inspect

from hpo_link import server_manager


def test_unified_server_builds_stateless_json_mcp_app() -> None:
    src = inspect.getsource(server_manager.create_unified_app)
    assert "stateless_http=True" in src, "MCP app must be built stateless"
    assert "json_response=True" in src, "MCP app must return JSON responses"
    assert 'mount("/"' in src, "MCP ASGI app must mount at root (no 307)"
