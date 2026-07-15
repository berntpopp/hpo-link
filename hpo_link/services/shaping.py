"""Response-mode projection for HPO term payloads.

``standard`` / ``full`` are the identity (the complete record, with structured
synonyms carrying scope/type/sources, and the inline ``recommended_citation``).
``compact`` (the default) drops null/empty values and collapses synonyms to plain
strings. ``minimal`` keeps only the identity anchors (``hpo_id`` + ``name`` +
``hpo_version``). The long-form citation is a standard/full convenience only;
``hpo_version`` is the always-present per-call citation anchor.
"""

from __future__ import annotations

from typing import Any

from hpo_link.exceptions import InvalidInputError
from hpo_link.mcp.untrusted_content import UntrustedText, fence_untrusted_text

RESPONSE_MODES: list[str] = ["minimal", "compact", "standard", "full"]
DEFAULT_RESPONSE_MODE = "compact"

#: Default cap for the compact search snippet (chars). search_terms is the
#: broadest-fan-out tool, so its default page must stay token-cheap: identity +
#: score + a short snippet, with the full definition reserved for standard/full.
SEARCH_SNIPPET_CHARS = 140

_PRESERVE_KEYS: frozenset[str] = frozenset({"_meta", "success"})

#: Identity anchors kept in ``minimal`` mode. ``hpo_version`` is the per-call
#: citation anchor; the long-form ``recommended_citation`` is NOT kept here — it is
#: fetched once from ``get_server_capabilities`` and inlined only at standard/full.
_MINIMAL_KEEP: frozenset[str] = frozenset({"hpo_id", "name", "hpo_version", "_meta"})

#: Identity/grounding anchors a sparse fieldset always retains.
_FIELD_ANCHORS: frozenset[str] = frozenset({"hpo_id", "name", "hpo_version", "_meta", "success"})

#: Response-Envelope v1.1 provenance source label for HPO-sourced free text.
UNTRUSTED_SOURCE = "hpo"


def _fence_field(raw: str, *, record_id: str) -> tuple[dict[str, Any], UntrustedText]:
    """Fence one externally sourced prose field at the MCP serialization boundary.

    Returns the ``UntrustedText`` object as an MCP-ready dict (``kind``/``text``/
    ``provenance``/``raw_sha256``) alongside the model instance, so callers can
    batch every fenced object in a response through ``enforce_untrusted_text_limits``.
    """
    fenced = fence_untrusted_text(raw, source=UNTRUSTED_SOURCE, record_id=record_id)
    return fenced.model_dump(mode="json"), fenced


def _fence_comments(
    comments: Any, *, hpo_id: str
) -> tuple[list[dict[str, Any]], list[UntrustedText]]:
    """Fence each upstream HPO ``comments`` entry as an ``untrusted_text`` object.

    ``record_id`` is ``{hpo_id}#comment:{i}`` so each comment is individually
    auditable. Non-string / empty entries are skipped.
    """
    dumps: list[dict[str, Any]] = []
    objs: list[UntrustedText] = []
    for i, comment in enumerate(comments or []):
        if not isinstance(comment, str) or not comment:
            continue
        dumped, fenced = _fence_field(comment, record_id=f"{hpo_id}#comment:{i}")
        dumps.append(dumped)
        objs.append(fenced)
    return dumps, objs


def _is_empty(value: Any) -> bool:
    """True for the null/empty values compact mode drops."""
    return value is None or value == [] or value == "" or value == {}


#: HPOA "no value" placeholders that annotation-row compact shaping drops as noise
#: (the source TSV uses ``-`` where a value is absent, e.g. an unparseable frequency).
_DROP_SENTINELS: frozenset[str] = frozenset({"-"})


def _plain_synonyms(synonyms: Any) -> list[str]:
    """Collapse a structured-synonym list to de-duplicated plain strings."""
    out: list[str] = []
    seen: set[str] = set()
    for syn in synonyms or []:
        text = syn.get("text") if isinstance(syn, dict) else syn
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def shape_term(
    record: dict[str, Any], mode: str
) -> tuple[dict[str, Any], dict[str, list[UntrustedText]]]:
    """Project a term record to the requested verbosity.

    - ``minimal``: ``hpo_id`` + ``name`` (and any preserved keys).
    - ``compact``: drop null/empty, collapse synonyms to plain strings,
      truncate definition to snippet.
    - ``standard`` / ``full``: the complete record incl. structured synonyms.

    ``definition`` and every ``comments`` entry (Response-Envelope v1.1) are
    externally sourced free text, so each is emitted as a fenced ``untrusted_text``
    object rather than a bare string/list-of-strings. Returns
    ``(shaped_record, fenced_by_field)`` mapping each fenced top-level field
    (``definition`` / ``comments``) to its ``UntrustedText`` objects, so ``get_term``
    can enforce limits over only the fields that survive sparse-field projection.
    """
    record_id = str(record.get("hpo_id") or "")
    fenced_by_field: dict[str, list[UntrustedText]] = {}
    if mode == "minimal":
        return {k: v for k, v in record.items() if k in _MINIMAL_KEEP}, fenced_by_field
    if mode in ("standard", "full"):
        out = dict(record)
        definition = out.get("definition")
        if isinstance(definition, str) and definition:
            dumped, fenced = _fence_field(definition, record_id=record_id)
            out["definition"] = dumped
            fenced_by_field["definition"] = [fenced]
        comment_dumps, comment_objs = _fence_comments(out.get("comments"), hpo_id=record_id)
        if comment_objs:
            out["comments"] = comment_dumps
            fenced_by_field["comments"] = comment_objs
        return out, fenced_by_field
    # compact
    out = {}
    for key, value in record.items():
        if key == "synonyms":
            value = _plain_synonyms(value)
        elif key == "definition" and isinstance(value, str) and value:
            snippet = _truncate_raw(value, SEARCH_SNIPPET_CHARS)
            dumped, fenced = _fence_field(snippet, record_id=record_id)
            value = dumped
            fenced_by_field["definition"] = [fenced]
        elif key == "comments":
            comment_dumps, comment_objs = _fence_comments(value, hpo_id=record_id)
            if comment_objs:
                fenced_by_field["comments"] = comment_objs
            value = comment_dumps
        if key not in _PRESERVE_KEYS and _is_empty(value):
            continue
        out[key] = value
    return out, fenced_by_field


def select_fields(
    payload: dict[str, Any],
    fields: list[str] | None,
    *,
    known: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Project a payload to a caller-requested sparse fieldset.

    Identity/grounding anchors (``hpo_id``, ``name``, ``hpo_version``, plus the
    preserved ``_meta``/``success``) are always retained. Supports top-level keys
    and ONE level of dotting into a grouped object -- e.g. ``"mappings.UMLS"`` keeps
    only the UMLS group under ``mappings``. Returns the payload unchanged when
    ``fields`` is falsy.

    When ``known`` is supplied it is the tool's STABLE projectable vocabulary: a field
    whose top-level key is neither an anchor nor in ``known`` is rejected with
    ``invalid_input`` rather than silently skipped (issue #28 review — an unrecognised
    field used to zero the payload with ``success: true``, a silent-empty). ``known`` is the
    full vocabulary, not the response-mode-shaped payload, so a valid-but-empty field
    (e.g. ``comments`` dropped in compact mode) is accepted, not rejected.

    A fenced ``untrusted_text`` object is treated as an OPAQUE leaf: a dotted
    projection like ``definition.text`` MUST NOT descend into the wrapper and return
    the bare ``text`` without ``kind``/``provenance``/``raw_sha256`` (that would
    silently unfence upstream prose). Such a projection emits the whole fenced object.
    """
    if not fields:
        return payload
    if known is not None:
        for field in fields:
            top = field.partition(".")[0]
            if top not in known and top not in _FIELD_ANCHORS:
                raise InvalidInputError(
                    f"field {top!r} is not a projectable field.",
                    field="fields",
                    allowed=sorted(set(known) | {"hpo_id", "name"}),
                    hint="fields selects top-level keys; omit it for the full payload.",
                )
    out: dict[str, Any] = {k: v for k, v in payload.items() if k in _FIELD_ANCHORS}
    for field in fields:
        top, _, sub = field.partition(".")
        if sub:
            container = payload.get(top)
            if isinstance(container, dict) and container.get("kind") == "untrusted_text":
                # opaque fenced leaf — never unwrap; emit the whole object
                out[top] = container
            elif isinstance(container, dict) and sub in container:
                nested = out.setdefault(top, {})
                if isinstance(nested, dict):
                    nested[sub] = container[sub]
        elif top in payload:
            out[top] = payload[top]
    return out


def shape_annotation_rows(rows: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    """Project annotation rows (phenotype/gene/disease) to the requested verbosity.

    - ``standard`` / ``full``: rows are returned unchanged (all columns preserved).
    - ``compact`` / ``minimal``: drop keys whose value is null/empty
      (``None``, ``""``, ``[]``, ``{}``) using the ``_is_empty`` predicate.
      ``hpo_id`` and ``name`` are always retained when present.

    Args:
        rows: List of annotation row dicts from the repository.
        mode: One of ``minimal``, ``compact``, ``standard``, ``full``.

    Returns:
        New list of dicts shaped to the requested mode.
    """
    if mode in ("standard", "full"):
        return [dict(r) for r in rows]
    # compact / minimal — drop null/empty values and the HPOA "-" no-data sentinel
    # (e.g. an undecodable raw ``frequency``), which is semantically empty but would
    # otherwise survive as token noise in the token-efficient modes.
    _always_keep: frozenset[str] = frozenset({"hpo_id", "name"})
    shaped: list[dict[str, Any]] = []
    for row in rows:
        out: dict[str, Any] = {}
        for key, value in row.items():
            # the sentinel is only ever the string "-"; restricting the membership
            # test to str also avoids a TypeError on unhashable (list/dict) values.
            is_sentinel = isinstance(value, str) and value in _DROP_SENTINELS
            if key in _always_keep or (not _is_empty(value) and not is_sentinel):
                out[key] = value
        shaped.append(out)
    return shaped


def _truncate_raw(text: str, limit: int) -> str:
    """Truncate ``text`` to at most ``limit`` chars on a word boundary.

    Preserves internal whitespace (tab/LF/CR) — it does NOT collapse whitespace
    runs. This matters because the truncated snippet is then fenced as an
    ``untrusted_text`` object, and Response-Envelope v1.1 requires the digest to
    cover the snippet's true pre-normalization bytes with tab/LF/CR intact (a
    ``" ".join(text.split())`` pre-fence would strip them and make ``raw_sha256``
    cover rewritten text). Appends ``…`` only when the text is actually truncated.
    """
    if len(text) <= limit:
        return text
    cut = text[:limit]
    head, _, _ = cut.rpartition(" ")
    return (head or cut) + "…"


def shape_search_hit(
    hit: dict[str, Any], mode: str, *, snippet_chars: int = SEARCH_SNIPPET_CHARS
) -> tuple[dict[str, Any], list[UntrustedText]]:
    """Project a search hit, keeping the hot path token-cheap.

    - ``minimal`` / ``compact``: ``{hpo_id, name, score}`` -- compact adds a
      ``definition_snippet`` (truncated to ``snippet_chars``) when a definition
      exists, but never the full paragraph.
    - ``standard`` / ``full``: identity + score + the complete ``definition``.

    ``definition``/``definition_snippet`` (Response-Envelope v1.1) are externally
    sourced free text, so each is emitted as a fenced ``untrusted_text`` object
    rather than a bare string. Returns ``(shaped_hit, fenced_objects)`` — callers
    accumulate ``fenced_objects`` across all hits and pass them to
    ``enforce_untrusted_text_limits`` before returning the MCP response.
    """
    out: dict[str, Any] = {
        "hpo_id": hit.get("hpo_id"),
        "name": hit.get("name"),
        "score": hit.get("score"),
    }
    record_id = str(hit.get("hpo_id") or "")
    fenced_objs: list[UntrustedText] = []
    definition = hit.get("definition")
    if mode in ("standard", "full"):
        if definition:
            dumped, fenced = _fence_field(definition, record_id=record_id)
            out["definition"] = dumped
            fenced_objs.append(fenced)
    elif mode == "compact" and definition:
        snippet = _truncate_raw(definition, snippet_chars)
        dumped, fenced = _fence_field(snippet, record_id=record_id)
        out["definition_snippet"] = dumped
        fenced_objs.append(fenced)
    return out, fenced_objs
