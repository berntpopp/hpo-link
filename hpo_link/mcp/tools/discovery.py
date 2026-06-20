"""Discovery tools: get_server_capabilities, get_diagnostics."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from hpo_link.buildinfo import build_info
from hpo_link.constants import LATENCY_SLO_P99_MS, STALE_AFTER_DAYS
from hpo_link.mcp import metrics
from hpo_link.mcp.annotations import READ_ONLY_OPEN_WORLD
from hpo_link.mcp.capabilities import collect_tool_signatures, project_capabilities
from hpo_link.mcp.envelope import McpErrorContext, run_mcp_tool
from hpo_link.mcp.next_commands import after_capabilities, cmd
from hpo_link.mcp.schemas import CAPABILITIES_SCHEMA, DIAGNOSTICS_SCHEMA
from hpo_link.mcp.service_adapters import get_hpo_service

if TYPE_CHECKING:
    from fastmcp import FastMCP


def _resolve_counts(meta: dict[str, Any], repo: Any) -> dict[str, int]:
    """Resolve diagnostics counts from the meta dict, falling back to repo.counts().

    Prefers the pre-computed values stored in the ``meta`` table (keyed as
    ``term_count``, ``obsolete_count``, etc.).  When a value is missing or ``None``
    (e.g. an older DB built before a column existed), falls back to a live
    ``SELECT COUNT(*)`` via ``repo.counts()`` for that specific key.

    Args:
        meta: Column-keyed dict from ``HpoRepository.read_meta()``.
        repo:  ``HpoRepository`` instance (used only if a fallback is needed).

    Returns:
        Dict with exactly the seven keys expected by the diagnostics payload:
        ``terms``, ``obsolete``, ``closure``, ``xref``,
        ``disease_phenotype``, ``gene_phenotype``, ``gene_disease``.
    """
    # Mapping: (meta_column, result_key)
    meta_key_map: list[tuple[str, str]] = [
        ("term_count", "terms"),
        ("obsolete_count", "obsolete"),
        ("closure_count", "closure"),
        ("xref_count", "xref"),
        ("disease_phenotype_count", "disease_phenotype"),
        ("gene_phenotype_count", "gene_phenotype"),
        ("gene_disease_count", "gene_disease"),
    ]

    # Determine which keys need a live count (lazy — only call repo.counts() once)
    needs_fallback = any(meta.get(meta_col) is None for meta_col, _ in meta_key_map)
    fallback: dict[str, int] = repo.counts() if needs_fallback else {}

    return {
        result_key: (meta[meta_col] if meta.get(meta_col) is not None else fallback[result_key])
        for meta_col, result_key in meta_key_map
    }


def _freshness(build_utc: str | None, *, now: datetime | None = None) -> dict[str, Any]:
    """Built-date age + staleness signal so an operator sees a stale index locally.

    Returns a well-formed block even when build_utc is missing/unparseable: in that
    case age_days and stale are None. stale is True when the built index is older
    than STALE_AFTER_DAYS.
    """
    out: dict[str, Any] = {
        "build_utc": build_utc,
        "stale_after_days": STALE_AFTER_DAYS,
        "age_days": None,
        "stale": None,
    }
    if not build_utc:
        return out
    try:
        built = datetime.fromisoformat(build_utc)
    except ValueError:
        return out
    if built.tzinfo is None:
        built = built.replace(tzinfo=UTC)
    current = now or datetime.now(tz=UTC)
    age = (current - built).days
    out["age_days"] = age
    out["stale"] = age > STALE_AFTER_DAYS
    return out


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

            counts: dict[str, Any]
            if repo is not None:
                counts = _resolve_counts(meta, repo)
            else:
                counts = {
                    "terms": None,
                    "obsolete": None,
                    "closure": None,
                    "xref": None,
                    "disease_phenotype": None,
                    "gene_phenotype": None,
                    "gene_disease": None,
                }

            payload: dict[str, Any] = {
                "success": True,
                "server": "hpo-link",
                "index_status": index_status,
                "hpo_version": meta.get("hpo_version"),
                "hpoa_version": meta.get("hpoa_version"),
                "counts": counts,
                "build_utc": meta.get("build_utc"),
                "freshness": _freshness(meta.get("build_utc")),
                "latency_slo": {"p99_ms": LATENCY_SLO_P99_MS},
                "build": build_info(),
                "runtime_metrics": metrics.snapshot(),
            }
            payload.setdefault("_meta", {})["next_commands"] = (
                [cmd("resolve_term", query="HP:0000118")]
                if index_built
                else [cmd("get_server_capabilities")]
            )
            return payload

        return await run_mcp_tool(
            "get_diagnostics",
            call,
            context=McpErrorContext("get_diagnostics"),
        )
