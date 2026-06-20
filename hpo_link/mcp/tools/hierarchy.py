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
from hpo_link.mcp.tools._common import ResponseMode

if TYPE_CHECKING:
    from fastmcp import FastMCP

_ClosureLimit = Annotated[int, Field(ge=1, le=1000, description="Max rows returned (default 50).")]
_ClosureOffset = Annotated[
    int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
]
HpoIdStr = Annotated[
    str,
    Field(
        description=(
            "Canonical HP id for the resolved HPO term (HP:0000118). Legacy `term` "
            "arguments are accepted as an alias."
        ),
        examples=["HP:0000118"],
    ),
]


def register_hierarchy_tools(mcp: FastMCP) -> None:
    """Register the is_a hierarchy tools on a FastMCP instance."""

    @mcp.tool(
        name="get_term_ancestors",
        title="Get HPO Term Ancestors",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=ANCESTORS_SCHEMA,
        tags={"hpo", "hierarchy", "closure"},
        description=(
            "Return all transitive is_a ancestors (broader phenotype terms) of an HPO "
            "term via the precomputed closure, with a pagination block {total, returned, "
            "limit, offset, truncated, next_offset}. When truncated, next_commands "
            "carries a forward-page step (offset) so you can walk a >limit closure "
            "without re-sending rows. Use get_term_parents for only the immediate "
            "parents. "
            "Signature: get_term_ancestors(hpo_id, limit=, offset=, response_mode=)."
        ),
    )
    async def get_term_ancestors(
        hpo_id: HpoIdStr,
        limit: _ClosureLimit = 50,
        offset: _ClosureOffset = 0,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().term_ancestors(
                hpo_id, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_ancestors(payload)
            return payload

        return await run_mcp_tool(
            "get_term_ancestors",
            call,
            context=McpErrorContext(
                "get_term_ancestors",
                arguments={"hpo_id": hpo_id, "term": hpo_id},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="get_term_descendants",
        title="Get HPO Term Descendants",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=DESCENDANTS_SCHEMA,
        tags={"hpo", "hierarchy", "closure"},
        description=(
            "Return all transitive is_a descendants (more specific phenotype terms) of an "
            "HPO term via the precomputed closure, with a pagination block {total, "
            "returned, limit, offset, truncated, next_offset}. When truncated, "
            "next_commands carries a forward-page step (offset) so you can walk a "
            ">limit closure without re-sending rows. Use get_term_children for only "
            "the immediate children. "
            "Signature: get_term_descendants(hpo_id, limit=, offset=, response_mode=)."
        ),
    )
    async def get_term_descendants(
        hpo_id: HpoIdStr,
        limit: _ClosureLimit = 50,
        offset: _ClosureOffset = 0,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().term_descendants(
                hpo_id, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_descendants(payload)
            return payload

        return await run_mcp_tool(
            "get_term_descendants",
            call,
            context=McpErrorContext(
                "get_term_descendants",
                arguments={"hpo_id": hpo_id, "term": hpo_id},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="get_term_parents",
        title="Get HPO Term Parents",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=PARENTS_SCHEMA,
        tags={"hpo", "hierarchy"},
        description=(
            "Return the direct is_a parents (immediate broader phenotype terms) of an HPO "
            "term. Use get_term_ancestors for the full transitive set. "
            "Signature: get_term_parents(hpo_id, response_mode=)."
        ),
    )
    async def get_term_parents(
        hpo_id: HpoIdStr, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().term_parents(hpo_id, response_mode=response_mode)
            payload.setdefault("_meta", {})["next_commands"] = after_parents(payload)
            return payload

        return await run_mcp_tool(
            "get_term_parents",
            call,
            context=McpErrorContext(
                "get_term_parents",
                arguments={"hpo_id": hpo_id, "term": hpo_id},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="get_term_children",
        title="Get HPO Term Children",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=CHILDREN_SCHEMA,
        tags={"hpo", "hierarchy"},
        description=(
            "Return the direct is_a children (immediate more-specific phenotype terms) of "
            "an HPO term. Use get_term_descendants for the full transitive set. "
            "Signature: get_term_children(hpo_id, response_mode=)."
        ),
    )
    async def get_term_children(
        hpo_id: HpoIdStr, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().term_children(hpo_id, response_mode=response_mode)
            payload.setdefault("_meta", {})["next_commands"] = after_children(payload)
            return payload

        return await run_mcp_tool(
            "get_term_children",
            call,
            context=McpErrorContext(
                "get_term_children",
                arguments={"hpo_id": hpo_id, "term": hpo_id},
                response_mode=response_mode,
            ),
        )
