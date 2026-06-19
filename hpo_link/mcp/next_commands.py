"""Builders for `_meta.next_commands` entries: `{tool, arguments}` steps.

The envelope-facing subset (``cmd``, ``widen_cmd``, ``default_error_next_commands``,
``withdrawn_recovery``) is consumed by the error boundary; the per-tool ``after_*``
chainers steer the success path (resolve -> record -> hierarchy -> cross-ontology).
"""

from __future__ import annotations

from typing import Any

from hpo_link.identifiers import is_hpo_id


def cmd(tool: str, **arguments: Any) -> dict[str, Any]:
    """One ready-to-call next step."""
    return {"tool": tool, "arguments": arguments}


def widen_cmd(tool: str, base_args: dict[str, Any], total: int, ceiling: int) -> dict[str, Any]:
    """A ready-to-call step that re-runs ``tool`` with ``limit`` raised to fit."""
    return cmd(tool, **{**base_args, "limit": min(total, ceiling)})


def page_cmd(tool: str, base_args: dict[str, Any], next_offset: int) -> dict[str, Any]:
    """A ready-to-call step that fetches the NEXT page (advance ``offset`` forward)."""
    return cmd(tool, **{**base_args, "offset": next_offset})


def _more_steps(
    tool: str, base_args: dict[str, Any], payload: dict[str, Any], ceiling: int
) -> list[dict[str, Any]]:
    """Forward-page step (if any) then a widen step, for a truncated list payload."""
    if not payload.get("truncated"):
        return []
    steps: list[dict[str, Any]] = []
    next_offset = payload.get("next_offset")
    if next_offset is not None:
        steps.append(page_cmd(tool, base_args, int(next_offset)))
    steps.append(widen_cmd(tool, base_args, int(payload.get("total", 0)), ceiling))
    return steps


def _looks_like_xref_curie(value: str) -> bool:
    """Return True when value looks like an external CURIE (PREFIX:local, not HP:)."""
    return ":" in value and not is_hpo_id(value)


def default_error_next_commands(
    tool: str, error_code: str, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    """A sensible recovery step for any error lacking an explicit fallback."""
    if tool in (
        "resolve_term",
        "get_term",
        "get_term_ancestors",
        "get_term_descendants",
        "get_term_parents",
        "get_term_children",
        "map_cross_ontology",
    ):
        value = str(arguments.get("term", "") or arguments.get("query", ""))
        if value and _looks_like_xref_curie(value):
            return [cmd("resolve_xref", xref_id=value), cmd("search_terms", query=value)]
        if value and not is_hpo_id(value):
            return [cmd("search_terms", query=value), cmd("get_server_capabilities")]
        if is_hpo_id(value):
            return [cmd("resolve_term", query=value), cmd("get_server_capabilities")]
    if tool == "resolve_xref":
        value = str(arguments.get("xref_id", ""))
        return [cmd("search_terms", query=value)] if value else [cmd("get_server_capabilities")]
    if error_code == "data_unavailable":
        return [cmd("get_server_capabilities")]
    return [cmd("get_server_capabilities")]


def withdrawn_recovery(replaced_by: list[dict[str, str]]) -> list[dict[str, Any]]:
    """After an obsolete-term error: chain to the successor record(s)."""
    targets = [r.get("hpo_id") for r in replaced_by if r.get("hpo_id")]
    if not targets:
        return [cmd("get_server_capabilities")]
    return [cmd("get_term", term=t) for t in targets[:2]]


def after_capabilities() -> list[dict[str, Any]]:
    """After get_server_capabilities: start the canonical resolve->record workflow."""
    return [
        cmd("resolve_term", query="Phenotypic abnormality"),
        cmd("search_terms", query="seizure"),
    ]


def after_resolve_term(resolution: dict[str, Any]) -> list[dict[str, Any]]:
    """After resolve_term: open the canonical record, else fall back to search."""
    hpo_id = resolution.get("hpo_id")
    if not hpo_id:
        return [
            cmd("search_terms", query=str(resolution.get("query", ""))),
            cmd("get_server_capabilities"),
        ]
    return [cmd("get_term", term=hpo_id)]


def after_search(query: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After search_terms: open the top hit; widen if truncated."""
    hits = payload.get("results", [])
    if not hits:
        return [cmd("resolve_term", query=query), cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    top = hits[0].get("hpo_id")
    if top:
        steps.append(cmd("get_term", term=top))
    steps += _more_steps("search_terms", {"query": query}, payload, 200)
    return steps or [cmd("get_server_capabilities")]


def after_get_term(term: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_term: walk up the DAG and map across ontologies."""
    hpo_id = term.get("hpo_id")
    if not hpo_id:
        return [cmd("get_server_capabilities")]
    return [
        cmd("get_term_ancestors", term=hpo_id),
        cmd("map_cross_ontology", term=hpo_id),
    ]


def after_ancestors(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_term_ancestors: offer parents/descendants; widen if truncated."""
    hpo_id = payload.get("hpo_id")
    if not hpo_id:
        return [cmd("get_server_capabilities")]
    steps = _more_steps("get_term_ancestors", {"term": hpo_id}, payload, 1000)
    steps += [
        cmd("get_term_parents", term=hpo_id),
        cmd("get_term_descendants", term=hpo_id),
    ]
    return steps


def after_descendants(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_term_descendants: offer children/ancestors; widen if truncated."""
    hpo_id = payload.get("hpo_id")
    if not hpo_id:
        return [cmd("get_server_capabilities")]
    steps = _more_steps("get_term_descendants", {"term": hpo_id}, payload, 1000)
    steps += [
        cmd("get_term_children", term=hpo_id),
        cmd("get_term_ancestors", term=hpo_id),
    ]
    return steps


def after_parents(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_term_parents: open the first parent, then the full ancestor set."""
    hpo_id = payload.get("hpo_id")
    parents = payload.get("parents", [])
    if not hpo_id:
        return [cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    if parents and parents[0].get("hpo_id"):
        steps.append(cmd("get_term", term=parents[0]["hpo_id"]))
    steps.append(cmd("get_term_ancestors", term=hpo_id))
    return steps


def after_children(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_term_children: open the first child, then the full descendant set."""
    hpo_id = payload.get("hpo_id")
    children = payload.get("children", [])
    if not hpo_id:
        return [cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    if children and children[0].get("hpo_id"):
        steps.append(cmd("get_term", term=children[0]["hpo_id"]))
    steps.append(cmd("get_term_descendants", term=hpo_id))
    return steps


def after_resolve_xref(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After resolve_xref: open the top matching HPO term; widen if truncated."""
    matches = payload.get("matches", [])
    if not matches:
        return [
            cmd("search_terms", query=str(payload.get("xref_id", ""))),
            cmd("get_server_capabilities"),
        ]
    steps: list[dict[str, Any]] = []
    top = matches[0].get("hpo_id")
    if top:
        steps.append(cmd("get_term", term=top))
    if payload.get("xref_id"):
        steps += _more_steps("resolve_xref", {"xref_id": payload["xref_id"]}, payload, 200)
    return steps or [cmd("get_server_capabilities")]


def after_cross_ontology(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After map_cross_ontology: walk up the DAG, or open the record itself."""
    hpo_id = payload.get("hpo_id")
    if not hpo_id:
        return [cmd("get_server_capabilities")]
    return [cmd("get_term_ancestors", term=hpo_id), cmd("get_term", term=hpo_id)]
