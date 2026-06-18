"""Cross-reference tools: hpo_resolve_xref (external -> HPO), hpo_map_cross_ontology."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from hpo_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
from hpo_link.mcp.next_commands import after_cross_ontology, after_resolve_xref
from hpo_link.mcp.schemas import CROSS_ONTOLOGY_SCHEMA, RESOLVE_XREF_SCHEMA
from hpo_link.mcp.service_adapters import get_hpo_service
from hpo_link.mcp.tools._common import ResponseMode, TermStr, XrefIdStr

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_xref_tools(mcp: FastMCP) -> None:
    """Register the cross-reference tools on a FastMCP instance."""

    @mcp.tool(
        name="hpo_resolve_xref",
        title="Resolve HPO Cross-Reference",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=RESOLVE_XREF_SCHEMA,
        tags={"hpo", "xref", "resolve"},
        description=(
            "Resolve an external cross-reference CURIE (UMLS/SNOMEDCT_US/NCIT/MEDDRA/"
            "ICD-10/ICD-9/MONDO/DOID/ORPHA) back to the HPO term(s) that cross-reference "
            "it. Returns matches[] plus a pagination block {total, returned, limit, "
            "offset, truncated, next_offset}; when truncated, next_commands carries a "
            "forward-page step (offset). "
            "Signature: hpo_resolve_xref(xref_id, limit=, offset=, response_mode=)."
        ),
    )
    async def hpo_resolve_xref(
        xref_id: XrefIdStr,
        limit: Annotated[
            int, Field(ge=1, le=1000, description="Max matches (default 25).")
        ] = 25,
        offset: Annotated[
            int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
        ] = 0,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().resolve_xref(
                xref_id, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_resolve_xref(payload)
            return payload

        return await run_mcp_tool(
            "hpo_resolve_xref",
            call,
            context=McpErrorContext(
                "hpo_resolve_xref",
                arguments={"xref_id": xref_id},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="hpo_map_cross_ontology",
        title="Map HPO Cross-Ontology",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=CROSS_ONTOLOGY_SCHEMA,
        tags={"hpo", "xref"},
        description=(
            "List an HPO term's cross-references to other ontologies/vocabularies, "
            "grouped by target prefix (UMLS/SNOMEDCT_US/NCIT/MEDDRA/ICD-10/ICD-9/"
            "MONDO/DOID/ORPHA/EFO/MSH/MESH). Optionally restrict to a subset of "
            "prefixes. "
            "Signature: hpo_map_cross_ontology(term, prefixes=, response_mode=)."
        ),
    )
    async def hpo_map_cross_ontology(
        term: TermStr,
        prefixes: Annotated[
            list[str] | None,
            Field(
                description="Restrict to these target prefixes, e.g. ['UMLS','SNOMEDCT_US'].",
                examples=[["UMLS", "SNOMEDCT_US"]],
            ),
        ] = None,
        response_mode: ResponseMode = "compact",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().map_cross_ontology(
                term, prefixes=prefixes, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_cross_ontology(payload)
            return payload

        return await run_mcp_tool(
            "hpo_map_cross_ontology",
            call,
            context=McpErrorContext(
                "hpo_map_cross_ontology",
                arguments={"term": term},
                response_mode=response_mode,
            ),
        )
