"""Parse hp.json obographs format into HPO terms, parents, and transitive closure.

Implements the hp.json parsing contract from the design spec §4.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from hpo_link.identifiers import iri_to_curie


def safe_get_nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely traverse nested dict keys; returns default if any key is missing."""
    result: Any = data
    for key in keys:
        if isinstance(result, dict):
            result = result.get(key)
            if result is None:
                return default
        else:
            return default
    return result if result is not None else default


def safe_get_list(data: dict[str, Any], *keys: str) -> list[Any]:
    """Safely retrieve a nested list; returns [] if missing or wrong type."""
    result = safe_get_nested(data, *keys, default=[])
    return result if isinstance(result, list) else []


_SYNONYM_PRED_MAP: dict[str, str] = {
    "hasExactSynonym": "exact",
    "hasRelatedSynonym": "related",
    "hasBroadSynonym": "broad",
    "hasNarrowSynonym": "narrow",
}

_VERSION_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_ALT_ID_PRED = "http://www.geneontology.org/formats/oboInOwl#hasAlternativeId"
_REPLACED_BY_PRED = "http://purl.obolibrary.org/obo/IAO_0100001"


@dataclass
class TermRecord:
    hpo_id: str
    name: str
    definition: str | None = None
    synonyms: list[dict[str, str]] = field(default_factory=list)
    xrefs: list[dict[str, str]] = field(default_factory=list)
    alt_ids: list[str] = field(default_factory=list)
    subsets: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    is_obsolete: bool = False
    replaced_by: str | None = None


@dataclass
class ParsedOntology:
    terms: dict[str, TermRecord]
    parents: dict[str, set[str]]
    version: str


def _parse_node(node: dict[str, Any]) -> TermRecord | None:
    """Convert a single obographs node into a TermRecord."""
    raw_id: str = node.get("id", "")
    hpo_id = iri_to_curie(raw_id)
    if not hpo_id or not hpo_id.startswith("HP:"):
        return None

    name: str = node.get("lbl", "") or ""
    meta: dict[str, Any] = node.get("meta", {}) or {}

    definition: str | None = safe_get_nested(meta, "definition", "val")

    # Synonyms
    synonyms: list[dict[str, str]] = []
    for s in safe_get_list(meta, "synonyms"):
        pred = s.get("pred", "")
        scope = _SYNONYM_PRED_MAP.get(pred)
        if scope:
            synonyms.append({"text": s.get("val", ""), "scope": scope})

    # Xrefs: split "PREFIX:id" on first colon
    xrefs: list[dict[str, str]] = []
    for x in safe_get_list(meta, "xrefs"):
        val: str = x.get("val", "")
        if ":" in val:
            prefix, obj_id = val.split(":", 1)
            xrefs.append({"prefix": prefix, "object_id": obj_id})

    # basicPropertyValues → alt_ids + replaced_by
    alt_ids: list[str] = []
    replaced_by: str | None = None
    for bpv in safe_get_list(meta, "basicPropertyValues"):
        pred = bpv.get("pred", "")
        val = bpv.get("val", "")
        if pred == _ALT_ID_PRED:
            alt_ids.append(val)
        elif pred == _REPLACED_BY_PRED:
            replaced_by = iri_to_curie(val) or val

    # Subsets
    subsets: list[str] = [str(s) for s in safe_get_list(meta, "subsets")]

    # Comments
    comments: list[str] = [str(c) for c in safe_get_list(meta, "comments")]

    is_obsolete: bool = bool(safe_get_nested(meta, "deprecated", default=False))

    return TermRecord(
        hpo_id=hpo_id,
        name=name,
        definition=definition,
        synonyms=synonyms,
        xrefs=xrefs,
        alt_ids=alt_ids,
        subsets=subsets,
        comments=comments,
        is_obsolete=is_obsolete,
        replaced_by=replaced_by,
    )


def parse_hp_json(text: str) -> ParsedOntology:
    """Parse hp.json obographs text into a ParsedOntology."""
    data = json.loads(text)
    graphs: list[dict[str, Any]] = data.get("graphs", [])
    if not graphs:
        return ParsedOntology(terms={}, parents={}, version="")

    graph = graphs[0]

    # Extract version YYYY-MM-DD from version IRI
    version_iri: str = safe_get_nested(graph, "meta", "version", default="") or ""
    m = _VERSION_RE.search(version_iri)
    version = m.group(1) if m else ""

    # Parse nodes
    terms: dict[str, TermRecord] = {}
    for node in safe_get_list(graph, "nodes"):
        rec = _parse_node(node)
        if rec is not None:
            terms[rec.hpo_id] = rec

    # Parse edges → parents dict
    parents: dict[str, set[str]] = {}
    for edge in safe_get_list(graph, "edges"):
        if edge.get("pred") != "is_a":
            continue
        sub = iri_to_curie(edge.get("sub", ""))
        obj = iri_to_curie(edge.get("obj", ""))
        if sub and obj and sub.startswith("HP:") and obj.startswith("HP:"):
            parents.setdefault(sub, set()).add(obj)

    return ParsedOntology(terms=terms, parents=parents, version=version)


def compute_closure(parents: dict[str, set[str]]) -> Iterator[tuple[str, str]]:
    """Yield (hpo_id, ancestor_id) pairs incl. self-pairs; iterative BFS, cycle-guarded."""
    all_ids: set[str] = set(parents.keys())
    for pset in parents.values():
        all_ids.update(pset)

    for hpo_id in all_ids:
        visited: set[str] = set()
        queue: deque[str] = deque([hpo_id])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            yield (hpo_id, current)
            for parent in parents.get(current, set()):
                if parent not in visited:
                    queue.append(parent)
