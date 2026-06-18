"""Disease lookup tools: resolve_disease, search_diseases, get_disease."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from hpo_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
from hpo_link.mcp.next_commands import after_get_disease, after_resolve_disease, after_search
from hpo_link.mcp.schemas import DISEASE_SCHEMA, RESOLVE_DISEASE_SCHEMA, SEARCH_SCHEMA
from hpo_link.mcp.service_adapters import get_hpo_service
from hpo_link.mcp.tools._common import FieldsArg, QueryStr, ResponseMode, TermStr

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_disease_tools(mcp: FastMCP) -> None:
    """Register the disease lookup/search tools on a FastMCP instance."""

    @mcp.tool(
        name="resolve_disease",
        title="Resolve Disease",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=RESOLVE_DISEASE_SCHEMA,
        tags={"disease", "resolve"},
        description=(
            "Resolve a disease label, synonym, MONDO id, or external cross-reference "
            "CURIE (OMIM/Orphanet/DOID/...) to the canonical Mondo term "
            "{mondo_id, name, match_type}. A near-miss or acronym-like label falls "
            "back to a conservative fuzzy match (match_type='fuzzy'); an ambiguous "
            "label returns ambiguous_query with candidates; an obsolete id returns "
            "not_found with its successor. "
            "Signature: resolve_disease(query, response_mode=)."
        ),
    )
    async def resolve_disease(
        query: QueryStr, response_mode: ResponseMode = "compact"
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().resolve_disease(query, response_mode=response_mode)
            payload.setdefault("_meta", {})["next_commands"] = after_resolve_disease(payload)
            return payload

        return await run_mcp_tool(
            "resolve_disease",
            call,
            context=McpErrorContext(
                "resolve_disease", arguments={"query": query}, response_mode=response_mode
            ),
        )

    @mcp.tool(
        name="search_diseases",
        title="Search Diseases",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=SEARCH_SCHEMA,
        tags={"disease", "search"},
        description=(
            "Full-text search over Mondo disease names, synonyms, and definitions "
            "(FTS, relevance-ranked). Returns {mondo_id, name, score} -- compact adds "
            "a short definition_snippet; standard/full add the complete definition -- "
            "plus a pagination block {total, returned, limit, offset, truncated, "
            "next_offset}. When truncated, next_commands carries a forward-page step "
            "(offset advanced) and a widen step. Obsolete terms are excluded unless "
            "include_obsolete=true. "
            "Signature: search_diseases(query, limit=, offset=, include_obsolete=, response_mode=)."
        ),
    )
    async def search_diseases(
        query: QueryStr,
        limit: Annotated[int, Field(ge=1, le=200, description="Max hits (default 25).")] = 25,
        offset: Annotated[
            int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
        ] = 0,
        include_obsolete: Annotated[
            bool, Field(description="Include obsolete terms (default false).")
        ] = False,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().search_diseases(
                query,
                limit=limit,
                offset=offset,
                include_obsolete=include_obsolete,
                response_mode=response_mode,
            )
            payload.setdefault("_meta", {})["next_commands"] = after_search(query, payload)
            return payload

        return await run_mcp_tool(
            "search_diseases",
            call,
            context=McpErrorContext(
                "search_diseases", arguments={"query": query}, response_mode=response_mode
            ),
        )

    @mcp.tool(
        name="get_disease",
        title="Get Disease",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=DISEASE_SCHEMA,
        tags={"disease"},
        description=(
            "Return a Mondo disease term: definition, synonyms, grouped "
            "cross-references, direct parents and children, top-level groupings, "
            "subsets, and obsolescence (replaced_by/consider). The term accepts a "
            "MONDO id, a label/synonym, or an external xref CURIE (resolved first). "
            "Pass fields=['xrefs.OMIM', ...] for a sparse projection. "
            "Signature: get_disease(term, response_mode=, fields=)."
        ),
    )
    async def get_disease(
        term: TermStr,
        response_mode: ResponseMode = "compact",
        fields: FieldsArg = None,
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().get_disease(
                term, response_mode=response_mode, fields=fields
            )
            payload.setdefault("_meta", {})["next_commands"] = after_get_disease(payload)
            return payload

        return await run_mcp_tool(
            "get_disease",
            call,
            context=McpErrorContext(
                "get_disease", arguments={"term": term}, response_mode=response_mode
            ),
        )
