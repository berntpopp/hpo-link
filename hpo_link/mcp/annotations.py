"""Shared MCP tool annotations (read-only research server)."""

from __future__ import annotations

from mcp.types import ToolAnnotations

READ_ONLY_OPEN_WORLD = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)
