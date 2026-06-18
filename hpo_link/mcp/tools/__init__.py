"""Mondo MCP tool registration functions (one register_* per domain module)."""

from __future__ import annotations

from hpo_link.mcp.tools.batch import register_batch_tools
from hpo_link.mcp.tools.discovery import register_discovery_tools
from hpo_link.mcp.tools.diseases import register_disease_tools
from hpo_link.mcp.tools.hierarchy import register_hierarchy_tools
from hpo_link.mcp.tools.xref import register_xref_tools

__all__ = [
    "register_batch_tools",
    "register_discovery_tools",
    "register_disease_tools",
    "register_hierarchy_tools",
    "register_xref_tools",
]
