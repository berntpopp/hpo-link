"""Cross-reference tools: resolve_xref (external -> HPO), map_cross_ontology."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field

from hpo_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
from hpo_link.mcp.next_commands import after_cross_ontology, after_resolve_xref
from hpo_link.mcp.service_adapters import get_hpo_service
from hpo_link.mcp.tools._common import FieldsArg, ResponseMode, ToolReturn, XrefIdStr

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


def register_xref_tools(mcp: FastMCP) -> None:
    """Register the cross-reference tools on a FastMCP instance."""

    @mcp.tool(
        name="resolve_xref",
        title="Resolve HPO Cross-Reference",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B1/B2: outputSchema is optional & unread; suppress to cut surface
        tags={"hpo", "xref", "resolve"},
        description=(
            "Resolve an external cross-reference CURIE (UMLS/SNOMEDCT_US/NCIT/MEDDRA/"
            "ICD-10/ICD-9/MONDO/DOID/ORPHA) back to the HPO term(s) that cross-reference "
            "it. Returns matches[] plus a pagination block {total, returned, limit, "
            "offset, truncated, next_offset}; when truncated, next_commands carries a "
            "forward-page step (offset). "
            "Signature: resolve_xref(xref_id, limit=, offset=, response_mode=)."
        ),
    )
    async def resolve_xref(
        xref_id: XrefIdStr,
        limit: Annotated[int, Field(ge=1, le=1000, description="Max matches (default 25).")] = 25,
        offset: Annotated[
            int, Field(ge=0, description="Rows to skip for forward paging (default 0).")
        ] = 0,
        response_mode: ResponseMode = "compact",
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().resolve_xref(
                xref_id, limit=limit, offset=offset, response_mode=response_mode
            )
            payload.setdefault("_meta", {})["next_commands"] = after_resolve_xref(payload)
            return payload

        return await run_mcp_tool(
            "resolve_xref",
            call,
            context=McpErrorContext(
                "resolve_xref",
                arguments={"xref_id": xref_id},
                response_mode=response_mode,
            ),
        )

    @mcp.tool(
        name="map_cross_ontology",
        title="Map HPO Cross-Ontology",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=None,  # B1/B2: outputSchema is optional & unread; suppress to cut surface
        tags={"hpo", "xref"},
        description=(
            "List an HPO term's cross-references to other ontologies/vocabularies, "
            "grouped by target prefix (UMLS/SNOMEDCT_US/NCIT/MEDDRA/ICD-10/ICD-9/"
            "MONDO/DOID/ORPHA/EFO/MSH/MESH). Optionally restrict to a subset of "
            "prefixes. "
            "Signature: map_cross_ontology(hpo_id, prefixes=, response_mode=, fields=)."
        ),
    )
    async def map_cross_ontology(
        hpo_id: HpoIdStr,
        prefixes: Annotated[
            list[str] | None,
            Field(
                description="Restrict to these target prefixes, e.g. ['UMLS','SNOMEDCT_US'].",
                examples=[["UMLS", "SNOMEDCT_US"]],
            ),
        ] = None,
        response_mode: ResponseMode = "compact",
        fields: FieldsArg = None,
    ) -> ToolReturn:
        async def call() -> dict[str, Any]:
            payload = get_hpo_service().map_cross_ontology(
                hpo_id, prefixes=prefixes, response_mode=response_mode, fields=fields
            )
            payload.setdefault("_meta", {})["next_commands"] = after_cross_ontology(payload)
            return payload

        return await run_mcp_tool(
            "map_cross_ontology",
            call,
            context=McpErrorContext(
                "map_cross_ontology",
                arguments={"hpo_id": hpo_id, "term": hpo_id},
                response_mode=response_mode,
            ),
        )
