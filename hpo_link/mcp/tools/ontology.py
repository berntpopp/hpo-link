"""Ontology lookup tools: resolve_term, search_terms, get_term."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from hpo_link.exceptions import AmbiguousQueryError
from hpo_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from hpo_link.mcp.envelope import (
    McpErrorContext,
    _valid_candidates,
    classify_exception,
    run_mcp_tool,
)
from hpo_link.mcp.next_commands import after_get_term, after_resolve_term, after_search, cmd
from hpo_link.mcp.service_adapters import get_hpo_service
from hpo_link.mcp.tools._common import FieldsArg, QueryStr, ResponseMode, ToolReturn
from hpo_link.mcp.untrusted_content import sanitize_message

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
            "canonical HPO term {hpo_id, name, match_type}. For 2 or more terms, call "
            "resolve_terms_batch once instead of calling this tool per item. An ambiguous "
            "label returns "
            "ambiguous_query with candidates (each {hpo_id, name}); an obsolete HP id "
            "resolves with success:true, obsolete:true, and its successor in replaced_by. "
            "This is the recommended first step — resolve any query to a canonical HP id "
            "before calling get_term. Returns the single best match; text queries add "
            "other_matches_count, and to list every term matching a text use search_terms. "
            "Signature: resolve_term(query, response_mode=)."
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
        name="resolve_terms_batch",
        title="Resolve HPO Terms (batch)",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B1/B2: outputSchema is optional & unread; suppress to cut surface
        tags={"hpo", "resolve", "batch"},
        description=(
            "Resolve many phenotype labels, synonyms, HP ids or xref CURIEs in one call "
            "(label -> HP id and HP id -> label); returns one results[] row per input in "
            "input order: {index, query, ok: true, hpo_id, name, match_type} or {index, "
            "ok: false, error_code, message} (an ambiguous label adds candidates). One bad "
            "item never fails the call; unresolved_count says how many missed. Max 100 items. "
            "Signature: resolve_terms_batch(queries, response_mode=)."
        ),
    )
    async def resolve_terms_batch(
        queries: Annotated[
            list[str],
            Field(
                min_length=1,
                max_length=100,
                description="1..100 phenotype labels/synonyms, HP ids, or xref CURIEs.",
                examples=[["Seizure", "HP:0001263", "Renal cyst"]],
            ),
        ],
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            svc = get_hpo_service()
            results: list[dict[str, Any]] = []
            for index, query in enumerate(queries):
                try:
                    rec = svc.resolve_term(query, response_mode="compact")
                    rec.pop("hpo_version", None)  # provenance is stated once, below
                    # the echoed query is caller text: strip forbidden code points, cap
                    rec["query"] = sanitize_message(rec["query"])[:200]
                    results.append({"index": index, "ok": True, **rec})
                except Exception as exc:  # per-item boundary; the call still succeeds
                    # Fixed classified message + index: the unresolved input is not echoed.
                    code, message = classify_exception(exc)
                    row: dict[str, Any] = {
                        "index": index,
                        "ok": False,
                        "error_code": code,
                        "message": message,
                    }
                    if isinstance(exc, AmbiguousQueryError):
                        row["candidates"] = _valid_candidates(exc.candidates)
                    results.append(row)
            resolved = [r["hpo_id"] for r in results if r["ok"]]
            return {
                "results": results,
                "count": len(results),
                "unresolved_count": len(results) - len(resolved),
                **svc._version_fields(response_mode),
                "_meta": {
                    "next_commands": [cmd("get_term", term=h) for h in resolved[:2]]
                    or [cmd("search_terms", query="seizure")]
                },
            }

        return await run_mcp_tool(
            "resolve_terms_batch",
            call,
            context=McpErrorContext("resolve_terms_batch", response_mode=response_mode),
        )

    @mcp.tool(
        name="search_terms",
        title="Search HPO Terms",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B1/B2: outputSchema is optional & unread; suppress to cut surface
        tags={"hpo", "search"},
        description=(
            "Full-text search over HPO phenotype term names, synonyms, and definitions "
            "(FTS, relevance-ranked); returns {hpo_id, name, score} -- compact adds "
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
            "For only the labels of several HP ids, call resolve_terms_batch once. "
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
