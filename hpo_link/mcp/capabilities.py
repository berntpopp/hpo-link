"""Capabilities payload and hpo:// discovery resources."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from hpo_link import __version__
from hpo_link.buildinfo import build_info
from hpo_link.constants import (
    HPO_LICENSE,
    LATENCY_SLO_P99_MS,
    RECOMMENDED_CITATION,
    XREF_PREFIXES,
)
from hpo_link.mcp.arg_help import tool_signature
from hpo_link.mcp.resources import (
    HPO_REFERENCE_NOTES,
    HPO_USAGE_NOTES,
    RESEARCH_USE_NOTICE,
)
from hpo_link.mcp.service_adapters import get_hpo_service
from hpo_link.services.shaping import DEFAULT_RESPONSE_MODE, RESPONSE_MODES

if TYPE_CHECKING:
    from fastmcp import FastMCP

#: Error taxonomy surfaced by every tool (see hpo_link.mcp.envelope).
ERROR_CODES: list[str] = [
    "invalid_input",
    "not_found",
    "ambiguous_query",
    "data_unavailable",
    "rate_limited",
    "upstream_unavailable",
    "internal_error",
]

#: Frozen tool surface. capabilities.TOOLS must equal the registered tool set.
TOOLS: list[str] = [
    "get_server_capabilities",
    "get_diagnostics",
    "resolve_term",
    "search_terms",
    "get_term",
    "get_term_parents",
    "get_term_children",
    "get_term_ancestors",
    "get_term_descendants",
    "resolve_xref",
    "map_cross_ontology",
    "get_phenotypes_for_gene",
    "get_genes_for_phenotype",
    "get_phenotypes_for_disease",
    "get_diseases_for_phenotype",
    "get_genes_for_disease",
    "get_diseases_for_gene",
]

#: Machine-readable tool-transition graph — the static form of _meta.next_commands.
#: For each tool, the tools that legitimately follow it, so a COLD client can plan a
#: whole workflow from get_server_capabilities without trial calls. Every node and
#: edge must name a real tool in TOOLS (enforced by test_tools_ontology.py).
TOOL_GRAPH: dict[str, list[str]] = {
    "get_server_capabilities": ["resolve_term", "search_terms", "get_diagnostics"],
    "get_diagnostics": ["resolve_term", "get_server_capabilities"],
    "resolve_term": ["get_term", "search_terms"],
    "search_terms": ["get_term", "resolve_term"],
    "get_term": [
        "get_term_parents",
        "get_term_children",
        "get_term_ancestors",
        "get_term_descendants",
        "map_cross_ontology",
        "get_genes_for_phenotype",
        "get_diseases_for_phenotype",
    ],
    "get_term_parents": ["get_term", "get_term_ancestors"],
    "get_term_children": ["get_term", "get_term_descendants"],
    "get_term_ancestors": ["get_term_parents", "get_term_descendants", "get_term"],
    "get_term_descendants": ["get_term_children", "get_term_ancestors", "get_term"],
    "map_cross_ontology": ["get_term", "resolve_xref", "get_term_ancestors"],
    "resolve_xref": ["get_term", "map_cross_ontology"],
    "get_genes_for_phenotype": ["get_diseases_for_gene", "get_phenotypes_for_gene"],
    "get_diseases_for_phenotype": ["get_genes_for_disease", "get_phenotypes_for_disease"],
    "get_phenotypes_for_gene": ["get_diseases_for_gene", "get_term"],
    "get_diseases_for_gene": ["get_phenotypes_for_disease", "get_genes_for_disease"],
    "get_genes_for_disease": ["get_phenotypes_for_gene", "get_diseases_for_gene"],
    "get_phenotypes_for_disease": ["get_genes_for_disease", "get_diseases_for_phenotype"],
}

_SUMMARY_KEYS: tuple[str, ...] = (
    "server",
    "server_version",
    "build",
    "capabilities_version",
    "hpo_version",
    "data_source",
    "research_use_only",
    "research_use_notice",
    "recommended_citation",
    "license",
    "tools",
    "tool_count",
    "response_modes",
    "default_response_mode",
    "recommended_workflows",
    "search_semantics",
    "truncation_contract",
    "absent_entity_contract",
    "tool_graph",
    "latency_slo",
    "error_codes",
    "limits",
    "read_only",
)

#: capabilities_version is a content hash of the discovery CONTRACT, cached per
#: HPO release so the per-call envelope echo never re-derives it. ``build`` (the
#: per-deploy git sha / timestamp) and the self-hash are excluded so unrelated
#: redeploys do not churn the value -- a warm client diffs it to skip re-fetching.
_HASH_EXCLUDE: frozenset[str] = frozenset({"build", "capabilities_version"})
_VERSION_CACHE: dict[str, str] = {}


def _hpo_version() -> str | None:
    """Best-effort loaded HPO release (never raises, never forces a build)."""
    try:
        svc = get_hpo_service()
        # Access private _version property; safe since None repo is guarded there.
        return svc._version
    except Exception:  # pragma: no cover
        return None


def _hash_contract(payload: dict[str, Any]) -> str:
    """Deterministic short hash of the discovery contract (volatile keys removed)."""
    contract = {k: v for k, v in payload.items() if k not in _HASH_EXCLUDE}
    blob = json.dumps(contract, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def capabilities_version() -> str:
    """Cached content hash of the discovery contract (echoed in every ``_meta``)."""
    key = _hpo_version() or "unbuilt"
    cached = _VERSION_CACHE.get(key)
    if cached is None:
        cached = build_capabilities()["capabilities_version"]
        _VERSION_CACHE[key] = cached
    return cached


def build_capabilities() -> dict[str, Any]:
    """Return the discovery surface describing this server."""
    payload: dict[str, Any] = {
        "server": "hpo-link",
        "server_version": __version__,
        "build": build_info(),
        "hpo_version": _hpo_version(),
        "data_source": (
            "Local SQLite index built from the Human Phenotype Ontology (HPO) OBO "
            "and HPOA annotation releases (https://hpo.jax.org/), refreshed by cron."
        ),
        "research_use_only": True,
        "research_use_notice": RESEARCH_USE_NOTICE,
        "recommended_citation": RECOMMENDED_CITATION,
        "license": HPO_LICENSE,
        "tools": TOOLS,
        "tool_count": len(TOOLS),
        "response_modes": list(RESPONSE_MODES),
        "default_response_mode": DEFAULT_RESPONSE_MODE,
        "xref_prefixes": list(XREF_PREFIXES),
        "provenance_policy": (
            "Static provenance (research-use restriction, citation, HPO release) is "
            "declared here and applies to ALL tool outputs. Every non-minimal payload "
            "carries hpo_version as the per-call citation anchor; the long-form "
            "recommended_citation is inlined only at response_mode standard/full (term "
            "and association payloads alike, one uniform rule) and is otherwise fetched "
            "once from here to conserve context tokens."
        ),
        "per_call_meta": [
            "tool",
            "request_id",
            "elapsed_ms",
            "capabilities_version",
            "next_commands",
        ],
        "per_call_meta_semantics": (
            "_meta verbosity is tiered by response_mode to control the per-call token "
            "tax: minimal returns only {tool, request_id}; compact (default) adds "
            "next_commands (workflow guidance) and capabilities_version (the warm-client "
            "cache key) but omits elapsed_ms; standard/full add elapsed_ms. Every compact "
            "or richer response carries next_commands; minimal is the explicit opt-out."
        ),
        "capabilities_version_semantics": (
            "_meta.capabilities_version is a content hash of this discovery contract. "
            "A warm client caches the last value it saw and skips re-fetching "
            "get_server_capabilities while it is unchanged. It is omitted in minimal "
            "mode (the caller has opted out of all non-essential _meta)."
        ),
        "field_projection": (
            "get_term and map_cross_ontology accept fields=[...] for a sparse "
            "projection: top-level keys, or dotted into a group (e.g. 'xrefs.UMLS'). "
            "Identity anchors (hpo_id, name, hpo_version) are always returned."
        ),
        "id_normalization": (
            "HP ids accepted/returned as 'HP:0000118' (7-digit zero-padded); "
            "external xrefs as CURIEs (UMLS:C0036572, SNOMEDCT_US:263681008, ...)."
        ),
        "search_semantics": (
            "search_terms is full-text search over HPO term names, synonyms, and "
            "definitions (relevance-ranked). To normalise a single label/id/xref to "
            "its canonical term use resolve_term; an ambiguous label returns "
            "ambiguous_query with candidates."
        ),
        "truncation_contract": (
            "List tools (search_terms, get_term_ancestors, "
            "get_term_descendants, resolve_xref) return total (matches before "
            "the cap), returned (rows in this payload), limit (cap applied), offset "
            "(rows skipped), and truncated (rows remain beyond this page). When "
            "truncated is true, next_offset carries the offset for the next page and "
            "_meta.next_commands includes a ready-to-call forward-page step."
        ),
        "response_mode_semantics": (
            "standard/full return the complete record (structured synonyms with "
            "scope/type, and the full definition on search hits); compact (default) "
            "drops null/empty values and returns search hits as hpo_id + name + score "
            "+ a short definition_snippet; minimal keeps only hpo_id + name."
        ),
        "recommended_workflows": [
            "label/id/xref -> resolve_term -> get_term",
            "term -> get_term_parents / get_term_children (immediate neighbours)",
            "term -> get_term_ancestors / get_term_descendants (transitive closure)",
            "external CURIE -> resolve_xref (xref -> HPO)",
            "term -> map_cross_ontology (HPO -> UMLS/SNOMED/NCIT/...)",
        ],
        "not_found_contract": (
            "An id/label/xref with no term returns error_code 'not_found'. An "
            "ambiguous label returns 'ambiguous_query' with candidates and "
            "next_commands to each candidate. An obsolete HP id returns "
            "'not_found' with replaced_by successors and next_commands to them."
        ),
        "absent_entity_contract": (
            "Malformed identifier → invalid_input (with field). A well-formed but "
            "unknown id (valid shape, no annotations) → an empty 200 page with "
            "total:0 — NOT not_found. not_found is reserved for genuine "
            "identity-resolution failure: the resolve_* tools and phenotype→term "
            "lookups where a free-text term cannot be resolved to any HPO id. "
            "The malformed→invalid_input rule is uniform across the six "
            "association tools (get_phenotypes_for_gene/disease, "
            "get_genes_for_phenotype/disease, get_diseases_for_phenotype/gene); "
            "resolve_xref likewise returns an empty 200 page for a well-formed but "
            "unknown xref (it accepts a bare object id or a CURIE, so it does not "
            "shape-validate)."
        ),
        "tool_graph": TOOL_GRAPH,
        "latency_slo": {
            "p99_ms": LATENCY_SLO_P99_MS,
            "scope": (
                "local in-process query (a deep is_a closure walk or a 25-row "
                "association page); measured server-side, surfaced in get_diagnostics"
            ),
        },
        "error_codes": ERROR_CODES,
        "limits": {
            "max_search_limit": 200,
            "max_closure_limit": 1000,
            "max_xref_limit": 1000,
            "default_search_limit": 25,
            "default_closure_limit": 50,
            "default_xref_limit": 25,
        },
        "read_only": True,
        "notes": HPO_REFERENCE_NOTES,
    }
    payload["capabilities_version"] = _hash_contract(payload)
    return payload


async def collect_tool_signatures(mcp: FastMCP) -> dict[str, str]:
    """Map every registered tool to its rendered signature (from the live schema)."""
    tools = sorted(await mcp.list_tools(), key=lambda t: t.name)
    return {t.name: tool_signature(t.name, t.parameters or {}) for t in tools}


async def build_tools_overview(mcp: FastMCP) -> dict[str, Any]:
    """Lightweight discovery payload: name, one-line summary, and call signature."""
    tools = sorted(await mcp.list_tools(), key=lambda t: t.name)
    entries: list[dict[str, str]] = []
    for tool in tools:
        summary = (tool.description or "").split(". ")[0].strip()
        entries.append(
            {
                "name": tool.name,
                "summary": summary[:200],
                "signature": tool_signature(tool.name, tool.parameters or {}),
            }
        )
    return {"server": "hpo-link", "tool_count": len(entries), "tools": entries}


def project_capabilities(
    detail: str, tool_signatures: dict[str, str] | None = None
) -> dict[str, Any]:
    """Return the full capabilities payload, or a light summary (default)."""
    full = build_capabilities()
    if tool_signatures is not None:
        full["tool_signatures"] = tool_signatures
    if detail == "full":
        full["detail"] = "full"
        return full
    summary: dict[str, Any] = {k: full[k] for k in _SUMMARY_KEYS if k in full}
    if tool_signatures is not None:
        summary["tool_signatures"] = tool_signatures
    summary["detail"] = "summary"
    summary["more"] = (
        "Call get_server_capabilities(detail='full') or read hpo://capabilities "
        "for reference notes; hpo://tools lists call signatures."
    )
    return summary


def register_capability_resources(mcp: FastMCP) -> None:
    """Register the hpo:// resource family on a FastMCP instance."""

    @mcp.resource("hpo://capabilities", mime_type="application/json")
    def capabilities() -> str:
        return json.dumps(build_capabilities(), indent=2)

    @mcp.resource("hpo://tools", mime_type="application/json")
    async def tools_overview() -> str:
        return json.dumps(await build_tools_overview(mcp), indent=2)

    @mcp.resource("hpo://usage", mime_type="text/plain")
    def usage() -> str:
        return HPO_USAGE_NOTES

    @mcp.resource("hpo://reference", mime_type="text/plain")
    def reference() -> str:
        return HPO_REFERENCE_NOTES

    @mcp.resource("hpo://research-use", mime_type="text/plain")
    def research_use() -> str:
        return RESEARCH_USE_NOTICE

    @mcp.resource("hpo://citation", mime_type="text/plain")
    def citation() -> str:
        return RECOMMENDED_CITATION
