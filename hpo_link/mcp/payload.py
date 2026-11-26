"""Response-Envelope v1 §1: the primary payload key of a successful data result.

A collection tool's list is ``results`` (array); a record tool's fields, or the grouped
mappings of ``map_cross_ontology``, sit under ``result`` (object). Envelope keys and list
metadata stay at the top level.
"""

from __future__ import annotations

from typing import Any

#: Collection tool -> the list its service returns, served as ``results``.
_RESULTS_KEY = {
    "search_terms": "results",
    "resolve_terms_batch": "results",
    "resolve_xref": "matches",
    "get_term_parents": "parents",
    "get_term_children": "children",
    "get_term_ancestors": "ancestors",
    "get_term_descendants": "descendants",
    "get_genes_for_phenotype": "genes",
    "get_genes_for_disease": "genes",
    "get_diseases_for_phenotype": "diseases",
    "get_diseases_for_gene": "diseases",
    "get_phenotypes_for_gene": "phenotypes",
    "get_phenotypes_for_disease": "phenotypes",
    "score_genes_for_phenotypes": "genes",
}
#: Record tools: every field outside ``_TOP_LEVEL`` moves under ``result``.
_RECORD_TOOLS = frozenset({"get_term", "resolve_term"})
_TOP_LEVEL = frozenset({"success", "_meta", "hpo_version", "recommended_citation"})


def nest_payload(tool_name: str, result: dict[str, Any]) -> None:
    """Move a success payload under its primary key in place; errors and ops tools stay flat."""
    if result.get("success") is not True:
        return
    key = _RESULTS_KEY.get(tool_name)
    if key is not None:
        result["results"] = result.pop(key, [])
    elif tool_name == "map_cross_ontology":
        # the grouped mappings are the payload; hpo_id and name stay beside it, and the
        # behaviour gate still reads a dict of lists as a collection
        result["result"] = result.pop("mappings", {})
    elif tool_name in _RECORD_TOOLS and "result" not in result:
        result["result"] = {k: result.pop(k) for k in list(result) if k not in _TOP_LEVEL}
