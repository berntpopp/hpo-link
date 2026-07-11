"""MCP facade for hpo-link: assemble the FastMCP instance with all tools."""

from __future__ import annotations

from fastmcp import FastMCP

from hpo_link import __version__
from hpo_link.mcp.capabilities import register_capability_resources
from hpo_link.mcp.log_filters import install_external_error_filter
from hpo_link.mcp.middleware import ArgValidationMiddleware, install_protocol_error_handler
from hpo_link.mcp.resources import HPO_SERVER_INSTRUCTIONS
from hpo_link.mcp.tools import (
    register_annotation_tools,
    register_discovery_tools,
    register_hierarchy_tools,
    register_ontology_tools,
    register_xref_tools,
)


def create_hpo_mcp() -> FastMCP:
    """Build a FastMCP instance with all hpo-link tools, resources, middleware."""
    mcp = FastMCP(
        name="hpo-link",
        version=__version__,
        instructions=HPO_SERVER_INSTRUCTIONS,
        mask_error_details=True,
    )
    # FastMCP configures its own non-propagating RichHandlers, which bypass the root
    # handler's scrub filter — attach the filter to them now that they exist, so FastMCP's
    # raw pydantic-validation WARNING (caller argument values) never reaches a log sink.
    install_external_error_filter()

    register_discovery_tools(mcp)
    register_ontology_tools(mcp)
    register_hierarchy_tools(mcp)
    register_xref_tools(mcp)
    register_annotation_tools(mcp)
    register_capability_resources(mcp)
    mcp.add_middleware(ArgValidationMiddleware())

    # Layer-3 protocol backstop: wrap the raw tool/resource/prompt request handlers as
    # the OUTERMOST guard so FastMCP core cannot reflect a caller-supplied name/URI/
    # prompt name (nor its code points) in a not-found JSON-RPC error frame. Installed
    # last, after all handlers exist.
    install_protocol_error_handler(mcp)

    return mcp
