"""HPO MCP tool registration functions (one register_* per domain module)."""

from __future__ import annotations

from hpo_link.mcp.tools.discovery import register_discovery_tools
from hpo_link.mcp.tools.hierarchy import register_hierarchy_tools
from hpo_link.mcp.tools.ontology import register_ontology_tools
from hpo_link.mcp.tools.xref import register_xref_tools

__all__ = [
    "register_discovery_tools",
    "register_hierarchy_tools",
    "register_ontology_tools",
    "register_xref_tools",
]
