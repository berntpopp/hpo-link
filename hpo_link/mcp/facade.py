"""MCP facade for hpo-link: assemble the FastMCP instance with all tools."""

from __future__ import annotations

from fastmcp import FastMCP

from hpo_link.mcp.capabilities import register_capability_resources
from hpo_link.mcp.middleware import ArgValidationMiddleware
from hpo_link.mcp.resources import HPO_SERVER_INSTRUCTIONS
from hpo_link.mcp.tools import (
    register_discovery_tools,
    register_hierarchy_tools,
    register_xref_tools,
)


def create_hpo_mcp() -> FastMCP:
    """Build a FastMCP instance with all hpo-link tools, resources, middleware."""
    mcp = FastMCP(
        name="hpo-link",
        instructions=HPO_SERVER_INSTRUCTIONS,
        mask_error_details=True,
    )

    register_discovery_tools(mcp)
    register_hierarchy_tools(mcp)
    register_xref_tools(mcp)
    register_capability_resources(mcp)
    mcp.add_middleware(ArgValidationMiddleware())

    return mcp
