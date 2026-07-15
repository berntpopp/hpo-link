"""Ontology lookup tools: resolve_term, search_terms, get_term."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from hpo_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
from hpo_link.mcp.next_commands import after_get_term, after_resolve_term, after_search
from hpo_link.mcp.service_adapters import get_hpo_service
from hpo_link.mcp.tools._common import FieldsArg, QueryStr, ResponseMode, ToolReturn

if TYPE_CHECKING:
    from fastmcp import FastMCP

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


def register_ontology_tools(mcp: FastMCP) -> None:
    """Register the HPO ontology lookup/search tools on a FastMCP instance."""

    @mcp.tool(
        name="resolve_term",
        title="Resolve HPO Term",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B1/B2: outputSchema is optional & unread; suppress to cut surface
        tags={"hpo", "resolve"},
        description=(
            "Resolve a phenotype label, synonym, HP id (HP:0000118), or external "
            "cross-reference CURIE (UMLS:C0000737, SNOMEDCT_US:263681008, ...) to the "
            "canonical HPO term {hpo_id, name, match_type}. An ambiguous label returns "
            "ambiguous_query with candidates (each {hpo_id, name}); an obsolete HP id "
            "resolves with success:true, obsolete:true, and its successor in replaced_by. "
            "This is the recommended first step — resolve any query to a canonical HP id "
            "before calling get_term. Signature: resolve_term(query, response_mode=)."
        ),
    )
    async def resolve_term(query: QueryStr, response_mode: ResponseMode = "compact") -> ToolReturn:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().resolve_term(query, response_mode=response_mode)
            payload.setdefault("_meta", {})["next_commands"] = after_resolve_term(payload)
            return payload

        return await run_mcp_tool(
            "resolve_term",
            call,
            context=McpErrorContext(
                "resolve_term",
                arguments={"query": query},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="search_terms",
        title="Search HPO Terms",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B1/B2: outputSchema is optional & unread; suppress to cut surface
        tags={"hpo", "search"},
        description=(
            "Full-text search over HPO phenotype term names, synonyms, and definitions "
            "(FTS, relevance-ranked). Returns {hpo_id, name, score} -- compact adds "
            "a short definition_snippet; standard/full add the complete definition -- "
            "plus a pagination block {total, returned, limit, offset, truncated, "
            "next_offset}. When truncated, next_commands carries a forward-page step "
            "(offset advanced) and a widen step. Obsolete terms are excluded unless "
            "include_obsolete=true. "
            "Signature: search_terms(query, limit=, offset=, include_obsolete=, response_mode=)."
        ),
    )
    async def search_terms(
        query: QueryStr,
        limit: Annotated[int, Field(ge=1, le=200, description="Max hits (default 25).")] = 25,
        offset: Annotated[
            int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
        ] = 0,
        include_obsolete: Annotated[
            bool, Field(description="Include obsolete terms (default false).")
        ] = False,
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().search_terms(
                query,
                limit=limit,
                offset=offset,
                include_obsolete=include_obsolete,
                response_mode=response_mode,
            )
            payload.setdefault("_meta", {})["next_commands"] = after_search(query, payload)
            return payload

        return await run_mcp_tool(
            "search_terms",
            call,
            context=McpErrorContext(
                "search_terms",
                arguments={"query": query},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="get_term",
        title="Get HPO Term",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B1/B2: outputSchema is optional & unread; suppress to cut surface
        tags={"hpo"},
        description=(
            "Return an HPO phenotype term record: definition, synonyms (exact/related/"
            "broad/narrow), alt_ids, subsets, comments, cross-references, direct "
            "parents and children, and obsolescence (replaced_by). The term accepts an "
            "HP id, a label/synonym, or an external xref CURIE (resolved first). "
            "Pass fields=['synonyms', 'definition'] for a sparse projection. "
            "Note on synonyms shape: compact (default) returns synonyms as plain "
            "strings; standard/full return {text, scope} objects. "
            "Signature: get_term(hpo_id, response_mode=, fields=)."
        ),
    )
    async def get_term(
        hpo_id: HpoIdStr,
        response_mode: ResponseMode = "compact",
        fields: FieldsArg = None,
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().get_term(hpo_id, response_mode=response_mode, fields=fields)
            payload.setdefault("_meta", {})["next_commands"] = after_get_term(payload)
            return payload

        return await run_mcp_tool(
            "get_term",
            call,
            context=McpErrorContext(
                "get_term",
                arguments={"hpo_id": hpo_id, "term": hpo_id},
                response_mode=response_mode,
            ),
        )
