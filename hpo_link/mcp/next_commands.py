"""Builders for `_meta.next_commands` entries: `{tool, arguments}` steps.

The envelope-facing subset (``cmd``, ``widen_cmd``, ``default_error_next_commands``,
``withdrawn_recovery``) is consumed by the error boundary; the per-tool ``after_*``
chainers steer the success path (resolve -> record -> hierarchy -> cross-ontology).
"""

from __future__ import annotations

from typing import Any

from hpo_link.identifiers import infer_xref_source, looks_like_mondo_id


def cmd(tool: str, **arguments: Any) -> dict[str, Any]:
    """One ready-to-call next step."""
    return {"tool": tool, "arguments": arguments}


def widen_cmd(tool: str, base_args: dict[str, Any], total: int, ceiling: int) -> dict[str, Any]:
    """A ready-to-call step that re-runs ``tool`` with ``limit`` raised to fit."""
    return cmd(tool, **{**base_args, "limit": min(total, ceiling)})


def page_cmd(tool: str, base_args: dict[str, Any], next_offset: int) -> dict[str, Any]:
    """A ready-to-call step that fetches the NEXT page (advance ``offset`` forward).

    Preferred over ``widen_cmd`` for large closures: it never re-sends rows the
    client already has, where raising ``limit`` re-fetches the whole head.
    """
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


def default_error_next_commands(
    tool: str, error_code: str, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    """A sensible recovery step for any error lacking an explicit fallback."""
    if tool in (
        "resolve_disease",
        "get_disease",
        "get_ancestors",
        "get_descendants",
        "get_parents",
        "get_children",
        "map_cross_ontology",
    ):
        value = str(arguments.get("term", "") or arguments.get("query", ""))
        source = infer_xref_source(value)
        if source:
            return [cmd("resolve_xref", xref_id=value), cmd("search_diseases", query=value)]
        if value and not looks_like_mondo_id(value):
            return [cmd("search_diseases", query=value), cmd("get_server_capabilities")]
    if tool == "resolve_xref":
        value = str(arguments.get("xref_id", ""))
        return [cmd("search_diseases", query=value)] if value else [cmd("get_server_capabilities")]
    if error_code == "data_unavailable":
        return [cmd("get_diagnostics")]
    return [cmd("get_server_capabilities")]


def withdrawn_recovery(replaced_by: list[dict[str, str]]) -> list[dict[str, Any]]:
    """After an obsolete-term error: chain to the successor record(s)."""
    targets = [r.get("mondo_id") for r in replaced_by if r.get("mondo_id")]
    if not targets:
        return [cmd("get_server_capabilities")]
    return [cmd("get_disease", term=t) for t in targets[:2]]


def after_capabilities() -> list[dict[str, Any]]:
    """After get_server_capabilities (the discovery root): start the canonical
    resolve->record workflow, then offer the freshness/diagnostics check.

    The discovery root is not exempt from the universal ``next_commands`` invariant
    (its own ``per_call_meta`` lists ``next_commands`` as guaranteed), so it points
    at the first real step rather than leaving the chain empty.
    """
    return [cmd("resolve_disease", query="Marfan syndrome"), cmd("get_diagnostics")]


def after_resolve_disease(resolution: dict[str, Any]) -> list[dict[str, Any]]:
    """After resolve_disease: open the canonical record, else fall back to search."""
    mondo_id = resolution.get("mondo_id")
    if not mondo_id:
        return [
            cmd("search_diseases", query=str(resolution.get("query", ""))),
            cmd("get_server_capabilities"),
        ]
    return [cmd("get_disease", term=mondo_id)]


def after_search(query: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After search_diseases: open the top hit; widen if truncated."""
    hits = payload.get("results", [])
    if not hits:
        return [cmd("resolve_disease", query=query), cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    top = hits[0].get("mondo_id")
    if top:
        steps.append(cmd("get_disease", term=top))
    steps += _more_steps("search_diseases", {"query": query}, payload, 200)
    return steps or [cmd("get_server_capabilities")]


def after_get_disease(disease: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_disease: walk up the DAG and map across ontologies."""
    mondo_id = disease.get("mondo_id")
    if not mondo_id:
        return [cmd("get_server_capabilities")]
    return [
        cmd("get_disease_ancestors", term=mondo_id),
        cmd("map_cross_ontology", term=mondo_id),
    ]


def after_ancestors(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_disease_ancestors: offer parents/descendants; widen if truncated."""
    mondo_id = payload.get("mondo_id")
    if not mondo_id:
        return [cmd("get_server_capabilities")]
    steps = _more_steps("get_disease_ancestors", {"term": mondo_id}, payload, 1000)
    steps += [
        cmd("get_disease_parents", term=mondo_id),
        cmd("get_disease_descendants", term=mondo_id),
    ]
    return steps


def after_descendants(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_disease_descendants: offer children/ancestors; widen if truncated."""
    mondo_id = payload.get("mondo_id")
    if not mondo_id:
        return [cmd("get_server_capabilities")]
    steps = _more_steps("get_disease_descendants", {"term": mondo_id}, payload, 1000)
    steps += [
        cmd("get_disease_children", term=mondo_id),
        cmd("get_disease_ancestors", term=mondo_id),
    ]
    return steps


def after_parents(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_disease_parents: open the first parent, then the full ancestor set."""
    mondo_id = payload.get("mondo_id")
    parents = payload.get("parents", [])
    if not mondo_id:
        return [cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    if parents and parents[0].get("mondo_id"):
        steps.append(cmd("get_disease", term=parents[0]["mondo_id"]))
    steps.append(cmd("get_disease_ancestors", term=mondo_id))
    return steps


def after_children(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_disease_children: open the first child, then the full descendant set."""
    mondo_id = payload.get("mondo_id")
    children = payload.get("children", [])
    if not mondo_id:
        return [cmd("get_server_capabilities")]
    steps: list[dict[str, Any]] = []
    if children and children[0].get("mondo_id"):
        steps.append(cmd("get_disease", term=children[0]["mondo_id"]))
    steps.append(cmd("get_disease_descendants", term=mondo_id))
    return steps


def after_resolve_xref(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After resolve_xref: open the top matching Mondo term; widen if truncated."""
    matches = payload.get("matches", [])
    if not matches:
        return [
            cmd("search_diseases", query=str(payload.get("xref_id", ""))),
            cmd("get_server_capabilities"),
        ]
    steps: list[dict[str, Any]] = []
    top = matches[0].get("mondo_id")
    if top:
        steps.append(cmd("get_disease", term=top))
    if payload.get("xref_id"):
        steps += _more_steps("resolve_xref", {"xref_id": payload["xref_id"]}, payload, 200)
    return steps or [cmd("get_server_capabilities")]


def after_cross_ontology(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After map_cross_ontology: walk up the DAG, or open the record itself."""
    mondo_id = payload.get("mondo_id")
    if not mondo_id:
        return [cmd("get_server_capabilities")]
    return [cmd("get_disease_ancestors", term=mondo_id), cmd("get_disease", term=mondo_id)]


def _first_resolved_id(payload: dict[str, Any]) -> str | None:
    """Return the mondo_id of the first successfully resolved item in a batch."""
    for item in payload.get("results", []):
        if item.get("ok") and item.get("mondo_id"):
            return str(item["mondo_id"])
    return None


def after_resolve_batch(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After resolve_disease_batch: open the first successfully resolved record."""
    mondo_id = _first_resolved_id(payload)
    if mondo_id:
        return [cmd("get_disease", term=mondo_id)]
    return [cmd("get_server_capabilities")]


def after_get_disease_batch(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """After get_disease_batch: map the first resolved record across ontologies."""
    mondo_id = _first_resolved_id(payload)
    if mondo_id:
        return [cmd("map_cross_ontology", term=mondo_id)]
    return [cmd("get_server_capabilities")]
