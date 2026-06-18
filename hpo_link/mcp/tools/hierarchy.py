"""Hierarchy tools: ancestors/descendants (closure) and parents/children (direct)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from hpo_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
from hpo_link.mcp.next_commands import (
    after_ancestors,
    after_children,
    after_descendants,
    after_parents,
)
from hpo_link.mcp.schemas import (
    ANCESTORS_SCHEMA,
    CHILDREN_SCHEMA,
    DESCENDANTS_SCHEMA,
    PARENTS_SCHEMA,
)
from hpo_link.mcp.service_adapters import get_hpo_service
from hpo_link.mcp.tools._common import ResponseMode, TermStr

if TYPE_CHECKING:
    from fastmcp import FastMCP

_ClosureLimit = Annotated[int, Field(ge=1, le=1000, description="Max rows returned (default 200).")]
_ClosureOffset = Annotated[
    int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
]


def register_hierarchy_tools(mcp: FastMCP) -> None:
    """Register the is_a hierarchy tools on a FastMCP instance."""

    @mcp.tool(
        name="get_disease_ancestors",
        title="Get Disease Ancestors",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=ANCESTORS_SCHEMA,
        tags={"disease", "hierarchy", "closure"},
        description=(
            "Return all transitive is_a ancestors (broader diseases) of a Mondo term "
            "via the precomputed closure, with a pagination block {total, returned, "
            "limit, offset, truncated, next_offset}. When truncated, next_commands "
            "carries a forward-page step (offset) so you can walk a >limit closure "
            "without re-sending rows. Use get_disease_parents for only the immediate "
            "parents. "
            "Signature: get_disease_ancestors(term, limit=, offset=, response_mode=)."
        ),
    )
    async def get_disease_ancestors(
        term: TermStr,
        limit: _ClosureLimit = 200,
        offset: _ClosureOffset = 0,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().get_ancestors(
                term, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_ancestors(payload)
            return payload

        return await run_mcp_tool(
            "get_disease_ancestors",
            call,
            context=McpErrorContext(
                "get_disease_ancestors", arguments={"term": term}, response_mode=response_mode
            ),
        )

    @mcp.tool(
        name="get_disease_descendants",
        title="Get Disease Descendants",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=DESCENDANTS_SCHEMA,
        tags={"disease", "hierarchy", "closure"},
        description=(
            "Return all transitive is_a descendants (more specific diseases) of a "
            "Mondo term via the precomputed closure, with a pagination block {total, "
            "returned, limit, offset, truncated, next_offset}. When truncated, "
            "next_commands carries a forward-page step (offset) so you can walk a "
            ">limit closure without re-sending rows. Use get_disease_children for only "
            "the immediate children. "
            "Signature: get_disease_descendants(term, limit=, offset=, response_mode=)."
        ),
    )
    async def get_disease_descendants(
        term: TermStr,
        limit: _ClosureLimit = 200,
        offset: _ClosureOffset = 0,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().get_descendants(
                term, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_descendants(payload)
            return payload

        return await run_mcp_tool(
            "get_disease_descendants",
            call,
            context=McpErrorContext(
                "get_disease_descendants", arguments={"term": term}, response_mode=response_mode
            ),
        )

    @mcp.tool(
        name="get_disease_parents",
        title="Get Disease Parents",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=PARENTS_SCHEMA,
        tags={"disease", "hierarchy"},
        description=(
            "Return the direct is_a parents (immediate broader diseases) of a Mondo "
            "term. Use get_disease_ancestors for the full transitive set. "
            "Signature: get_disease_parents(term, response_mode=)."
        ),
    )
    async def get_disease_parents(
        term: TermStr, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().get_parents(term, response_mode=response_mode)
            payload.setdefault("_meta", {})["next_commands"] = after_parents(payload)
            return payload

        return await run_mcp_tool(
            "get_disease_parents",
            call,
            context=McpErrorContext(
                "get_disease_parents", arguments={"term": term}, response_mode=response_mode
            ),
        )

    @mcp.tool(
        name="get_disease_children",
        title="Get Disease Children",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=CHILDREN_SCHEMA,
        tags={"disease", "hierarchy"},
        description=(
            "Return the direct is_a children (immediate more-specific diseases) of a "
            "Mondo term. Use get_disease_descendants for the full transitive set. "
            "Signature: get_disease_children(term, response_mode=)."
        ),
    )
    async def get_disease_children(
        term: TermStr, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().get_children(term, response_mode=response_mode)
            payload.setdefault("_meta", {})["next_commands"] = after_children(payload)
            return payload

        return await run_mcp_tool(
            "get_disease_children",
            call,
            context=McpErrorContext(
                "get_disease_children", arguments={"term": term}, response_mode=response_mode
            ),
        )
