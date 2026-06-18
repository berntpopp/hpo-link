"""Parse the Mondo OBO release and the SSSOM cross-ontology mapping table.

The OBO file carries a header block (``format-version``, ``data-version``,
``date``, ``subsetdef`` ...) before the first ``[Term]`` stanza, followed by one
stanza per term. Only ``MONDO:`` terms are kept; ``id``/``is_a``/``replaced_by``/
``consider`` values that are not Mondo ids are ignored. The closure recursion and
top-grouping rollup mirror ``mgi-link``'s ``mp_closure_pairs`` / ``mp_top_systems``
(MP -> MONDO, ``MP_ROOT`` -> :data:`hpo_link.constants.MONDO_ROOT`).

The SSSOM table is a TSV with an optional ``#``-comment metadata block, a header
row, and one mapping per row. ``skos:exactMatch`` etc. collapse to short forms and
object ids are normalised through :func:`hpo_link.identifiers.normalize_xref`.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from io import StringIO
from typing import Any

from hpo_link.constants import MONDO_ROOT
from hpo_link.identifiers import normalize_mondo_id, normalize_xref, xref_prefix

csv.field_size_limit(1 << 24)

_SCOPES = {"EXACT", "RELATED", "BROAD", "NARROW"}
_SCOPE_TO_LABEL_TYPE = {
    "EXACT": "exact_synonym",
    "RELATED": "related_synonym",
    "BROAD": "broad_synonym",
    "NARROW": "narrow_synonym",
}
#: SSSOM / OBO mapping predicate -> short form surfaced in the xref predicate.
_PREDICATE_MAP = {
    "skos:exactMatch": "exactMatch",
    "skos:closeMatch": "closeMatch",
    "skos:broadMatch": "broadMatch",
    "skos:narrowMatch": "narrowMatch",
    "exactMatch": "exactMatch",
    "closeMatch": "closeMatch",
    "broadMatch": "broadMatch",
    "narrowMatch": "narrowMatch",
}

_SYNONYM_RE = re.compile(r'^"(?P<text>(?:[^"\\]|\\.)*)"\s+(?P<rest>.*)$')
_TRAILING_SOURCES_RE = re.compile(r"\[(?P<body>.*?)\]\s*$")
_TRAILING_CURLY_RE = re.compile(r"\s*\{.*\}\s*$")
_DEF_RE = re.compile(r'^"(?P<text>(?:[^"\\]|\\.)*)"')


def parse_obo_header(text: str) -> dict[str, str]:
    """Return header tags (e.g. ``data_version``, ``date``) before the first ``[Term]``.

    Tag names are normalised to snake_case (``data-version`` -> ``data_version``).
    """
    header: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.rstrip("\n")
        if line.strip().startswith("["):
            break
        if ":" not in line:
            continue
        tag, _, value = line.partition(":")
        key = tag.strip().replace("-", "_")
        header[key] = value.strip()
    return header


def _strip_sources(rest: str) -> tuple[str, list[str]]:
    """Split a trailing ``[curie, curie]`` source list off ``rest``.

    Returns the remaining prefix text and the parsed source CURIEs (may be empty).
    """
    match = _TRAILING_SOURCES_RE.search(rest)
    if not match:
        return rest.strip(), []
    body = match.group("body").strip()
    prefix = rest[: match.start()].strip()
    sources = [tok.strip() for tok in body.split(",") if tok.strip()]
    return prefix, sources


def _parse_synonym(value: str) -> dict[str, Any] | None:
    """Parse ``"TEXT" SCOPE [TYPE] [sources]`` into a structured synonym."""
    value = _TRAILING_CURLY_RE.sub("", value).strip()
    match = _SYNONYM_RE.match(value)
    if not match:
        return None
    text = match.group("text")
    rest, sources = _strip_sources(match.group("rest"))
    tokens = rest.split()
    scope = tokens[0] if tokens and tokens[0] in _SCOPES else None
    if scope is None:
        return None
    type_ = tokens[1] if len(tokens) > 1 else None
    return {"text": text, "scope": scope, "type": type_, "sources": sources}


def _parse_xref(value: str) -> dict[str, Any] | None:
    """Parse an ``xref:`` value into ``{prefix, object_id, predicate, source}``."""
    trailing = _TRAILING_CURLY_RE.search(value)
    annotation = trailing.group(0) if trailing else ""
    curie = _TRAILING_CURLY_RE.sub("", value).strip()
    normalized = normalize_xref(curie)
    if normalized is None:
        return None
    predicate = "equivalentTo" if "MONDO:equivalentTo" in annotation else "xref"
    return {
        "prefix": xref_prefix(normalized),
        "object_id": normalized,
        "predicate": predicate,
        "source": None,
    }


def _strip_definition(value: str) -> str | None:
    """Strip surrounding quotes and a trailing ``[refs]`` from a ``def:`` value."""
    value = value.strip()
    match = _DEF_RE.match(value)
    if match:
        return match.group("text").strip()
    return value or None


def _new_term() -> dict[str, Any]:
    return {
        "id": None,
        "name": None,
        "definition": None,
        "parents": [],
        "synonyms": [],
        "xrefs": [],
        "subsets": [],
        "obsolete": False,
        "replaced_by": None,
        "consider": [],
    }


def _apply_tag(term: dict[str, Any], tag: str, value: str) -> None:
    """Mutate ``term`` for a single ``tag: value`` line inside a ``[Term]`` stanza."""
    if tag == "name":
        term["name"] = value
    elif tag == "def":
        term["definition"] = _strip_definition(value)
    elif tag == "synonym":
        parsed = _parse_synonym(value)
        if parsed is not None:
            term["synonyms"].append(parsed)
    elif tag == "xref":
        parsed_xref = _parse_xref(value)
        if parsed_xref is not None:
            term["xrefs"].append(parsed_xref)
    elif tag == "subset":
        token = value.split()[0] if value.split() else None
        if token:
            term["subsets"].append(token)
    elif tag == "is_a":
        parent = normalize_mondo_id(_TRAILING_CURLY_RE.sub("", value.split("!")[0]).strip())
        if parent:
            term["parents"].append(parent)
    elif tag == "is_obsolete" and value.lower() == "true":
        term["obsolete"] = True
    elif tag == "replaced_by":
        replaced = normalize_mondo_id(value)
        if replaced:
            term["replaced_by"] = replaced
    elif tag == "consider":
        consider = normalize_mondo_id(value)
        if consider:
            term["consider"].append(consider)


def parse_mondo_obo(text: str) -> dict[str, dict[str, Any]]:
    """Parse the Mondo OBO into ``{mondo_id: term-dict}`` (MONDO ids only)."""
    terms: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    in_term = False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "[Term]":
            current = _new_term()
            in_term = True
            continue
        if line.startswith("[") and line.endswith("]"):
            in_term = False
            current = None
            continue
        if not in_term or current is None or ":" not in line:
            continue
        tag, _, value = line.partition(":")
        tag = tag.strip()
        value = value.strip()
        if tag == "id":
            mondo_id = normalize_mondo_id(value)
            if mondo_id is None:
                in_term = False
                current = None
                continue
            current["id"] = mondo_id
            terms[mondo_id] = current
        else:
            _apply_tag(current, tag, value)
    return terms


def mondo_closure_pairs(terms: dict[str, dict[str, Any]]) -> Iterator[tuple[str, str]]:
    """Yield ``(mondo_id, ancestor_id)`` transitive-ancestor pairs incl. the self-pair."""
    cache: dict[str, set[str]] = {}

    def ancestors(mondo_id: str, stack: frozenset[str]) -> set[str]:
        if mondo_id in cache:
            return cache[mondo_id]
        acc: set[str] = {mondo_id}
        for parent in terms.get(mondo_id, {}).get("parents", []):
            if parent in stack:  # cycle guard
                continue
            acc.add(parent)
            acc |= ancestors(parent, stack | {parent})
        cache[mondo_id] = acc
        return acc

    for mondo_id in terms:
        for anc in ancestors(mondo_id, frozenset({mondo_id})):
            yield (mondo_id, anc)


def mondo_top_groupings(terms: dict[str, dict[str, Any]]) -> list[tuple[str, str, int]]:
    """Return the direct children of :data:`MONDO_ROOT` as ``(id, name, order)``.

    Ordered alphabetically by display name for a stable rollup layout.
    """
    groupings = [
        (mondo_id, term["name"])
        for mondo_id, term in terms.items()
        if MONDO_ROOT in term.get("parents", []) and not term.get("obsolete") and term.get("name")
    ]
    groupings.sort(key=lambda pair: pair[1].lower())
    return [(mondo_id, name, order) for order, (mondo_id, name) in enumerate(groupings)]


def parse_mondo_sssom(text: str) -> Iterator[dict[str, Any]]:
    """Yield ``{subject_id, object_id, predicate, source, object_label}`` rows.

    Skips blank / ``#``-comment lines, reads the TSV header, maps the SSSOM
    predicate to a short form, normalises the object id, and keeps only rows whose
    subject is a Mondo id. ``source`` is the ``mapping_justification`` column when
    present; ``object_label`` is the target term's human-readable name when present
    (so cross-references can be returned with a label, not just an id).
    """
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return
    reader = csv.DictReader(StringIO("\n".join(lines)), delimiter="\t")
    for row in reader:
        subject = normalize_mondo_id((row.get("subject_id") or "").strip())
        if subject is None:
            continue
        predicate = _PREDICATE_MAP.get((row.get("predicate_id") or "").strip())
        if predicate is None:
            continue
        object_id = normalize_xref((row.get("object_id") or "").strip())
        if object_id is None:
            continue
        yield {
            "subject_id": subject,
            "object_id": object_id,
            "predicate": predicate,
            "source": (row.get("mapping_justification") or "").strip() or None,
            "object_label": (row.get("object_label") or "").strip() or None,
        }
