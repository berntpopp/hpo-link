"""Discovery tools: get_server_capabilities, get_diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from hpo_link.buildinfo import build_info
from hpo_link.mcp import metrics
from hpo_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from hpo_link.mcp.capabilities import collect_tool_signatures, project_capabilities
from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
from hpo_link.mcp.next_commands import after_capabilities, cmd
from hpo_link.mcp.schemas import CAPABILITIES_SCHEMA, DIAGNOSTICS_SCHEMA
from hpo_link.mcp.service_adapters import get_hpo_service

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_discovery_tools(mcp: FastMCP) -> None:
    """Register the discovery tools on a FastMCP instance."""

    @mcp.tool(
        name="get_server_capabilities",
        title="Get Server Capabilities",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=CAPABILITIES_SCHEMA,
        tags={"discovery"},
        description=(
            "Return the hpo-link discovery surface: identity/build/HPO release, "
            "the tool list WITH call signatures, response modes, recommended "
            "workflows, the xref prefixes, the error taxonomy, and limits. "
            "detail='full' adds the full policy notes. Call this first in a cold "
            "session, or read hpo://tools / hpo://capabilities. "
            "Signature: get_server_capabilities(detail=)."
        ),
    )
    async def get_server_capabilities(
        detail: Annotated[
            Literal["summary", "full"],
            Field(description="summary (default, light) or full (adds policy notes)."),
        ] = "summary",
    ) -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            signatures = await collect_tool_signatures(mcp)
            payload = project_capabilities(detail, signatures)
            payload.setdefault("_meta", {})["next_commands"] = after_capabilities()
            return payload

        return await run_mcp_tool(
            "get_server_capabilities",
            call,
            context=McpErrorContext("get_server_capabilities"),
        )

    @mcp.tool(
        name="get_diagnostics",
        title="Get HPO Diagnostics",
        annotations=READ_ONLY_OPEN_WORLD,
        output_schema=DIAGNOSTICS_SCHEMA,
        tags={"discovery"},
        description=(
            "Report the local HPO index status: whether the data is built, the "
            "loaded HPO and HPOA release versions, term/obsolete/closure/xref/annotation "
            "counts, when it was built, and a runtime block (request/error counts and "
            "latency percentiles p50/p95/p99). Use this to confirm freshness or diagnose "
            "a data_unavailable error. "
            "Signature: get_diagnostics()."
        ),
    )
    async def get_diagnostics() -> dict[str, Any]:
        async def call() -> dict[str, Any]:
            svc = get_hpo_service()
            repo = svc._repo  # intentional introspection into private attr
            if repo is not None:
                meta = repo.read_meta()
                index_status = "available"
                index_built = True
            else:
                meta = {}
                index_status = "unavailable"
                index_built = False

            payload: dict[str, Any] = {
                "success": True,
                "server": "hpo-link",
                "index_status": index_status,
                "hpo_version": meta.get("hpo_version"),
                "hpoa_version": meta.get("hpoa_version"),
                "counts": {
                    "terms": meta.get("num_terms"),
                    "obsolete": meta.get("num_obsolete"),
                    "closure": meta.get("num_closure"),
                    "xref": meta.get("num_xref"),
                    "disease_phenotype": meta.get("num_disease_phenotype"),
                    "gene_phenotype": meta.get("num_gene_phenotype"),
                    "gene_disease": meta.get("num_gene_disease"),
                },
                "build_utc": meta.get("build_utc"),
                "build": build_info(),
                "runtime_metrics": metrics.snapshot(),
            }
            payload.setdefault("_meta", {})["next_commands"] = (
                [cmd("hpo_resolve_term", query="HP:0000118")]
                if index_built
                else [cmd("get_server_capabilities")]
            )
            return payload

        return await run_mcp_tool(
            "get_diagnostics",
            call,
            context=McpErrorContext("get_diagnostics"),
        )
