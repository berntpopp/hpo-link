"""Orchestration over the read-only HPO repository.

Returns plain dicts (no envelope); the MCP layer owns ``success``/``_meta``.
Every record payload carries ``hpo_version`` (from build provenance) for
grounding. The resolution cascade (HP id -> primary/synonym label -> external
xref CURIE) returns the match provenance and raises typed exceptions instead of
silently collapsing ambiguity.
"""

from __future__ import annotations

from typing import Any

from hpo_link.constants import RECOMMENDED_CITATION
from hpo_link.data.repository import HpoRepository
from hpo_link.exceptions import DataUnavailableError, InvalidInputError, NotFoundError
from hpo_link.mcp.untrusted_content import enforce_untrusted_text_limits
from hpo_link.services.pagination import page_fields
from hpo_link.services.resolution import Resolver, confidence_for
from hpo_link.services.shaping import (
    DEFAULT_RESPONSE_MODE,
    select_fields,
    shape_search_hit,
    shape_term,
)

_MAX_LIMIT = 1000

#: Stable projectable-field vocabularies for the two tools that accept ``fields=`` (issue #28
#: review — an unrecognised field must be rejected, not silently zero the payload). These are
#: the full field set, NOT the response-mode-shaped payload, so a valid-but-empty field
#: (e.g. ``comments`` dropped in compact mode) is still accepted.
_TERM_FIELDS: frozenset[str] = frozenset(
    {
        "hpo_id",
        "name",
        "definition",
        "synonyms",
        "alt_ids",
        "subsets",
        "comments",
        "obsolete",
        "replaced_by",
        "parents",
        "children",
        "hpo_version",
        "recommended_citation",
    }
)
_CROSS_ONTOLOGY_FIELDS: frozenset[str] = frozenset(
    {"hpo_id", "name", "mappings", "hpo_version", "recommended_citation"}
)

#: Hard ceiling on ``search_terms`` page size (mirrors the ``le=200`` tool bound in
#: ``mcp/tools/ontology.py`` and ``max_search_limit`` in capabilities). A full-mode
#: page can therefore emit up to 200 fenced ``untrusted_text`` definitions, so the
#: response-level untrusted-object limit for search uses this value rather than the
#: default 128 — otherwise a legitimate ``limit=200`` full-mode search would error.
_MAX_SEARCH_LIMIT = 200


class HpoService:
    """Service layer over the read-only HPO SQLite index."""

    def __init__(self, repo: HpoRepository | None) -> None:
        """Bind the service to a pre-opened HPO repository (or None when unavailable)."""
        self._repo = repo
        self._hpo_version: str | None = None

    # -- provenance ------------------------------------------------------------

    @property
    def _version(self) -> str | None:
        """Return the built HPO release string (lazily cached)."""
        if self._repo is None:
            return None
        if self._hpo_version is None:
            meta = self._repo.read_meta()
            self._hpo_version = meta.get("hpo_version") if meta else None
        return self._hpo_version

    @property
    def _db(self) -> HpoRepository:
        """Return the repository, raising DataUnavailableError when not loaded."""
        if self._repo is None:
            raise DataUnavailableError(
                "HPO index not built. Run the ingest pipeline to build the SQLite index."
            )
        return self._repo

    @property
    def _resolution(self) -> Resolver:
        """Resolver bound to the repository."""
        return Resolver(self._db)

    # -- internal helpers ------------------------------------------------------

    def _resolve_to_id(self, query: str) -> str:
        """Resolve any HP id / label / xref to a canonical HP id, raise NotFoundError on miss."""
        raw = (query or "").strip()
        if not raw:
            raise InvalidInputError("term must be a non-empty HP id, label, or xref.", field="term")
        return self._resolution.resolve_term_id(raw)

    def _version_fields(self, mode: str = DEFAULT_RESPONSE_MODE) -> dict[str, Any]:
        """Return version + citation anchors appended to every response.

        ``hpo_version`` is always present (the per-call citation anchor). The
        long-form ``recommended_citation`` (~250 chars) is inlined only at
        ``standard``/``full``; at ``compact``/``minimal`` it is fetched once from
        ``get_server_capabilities`` (mirrors ``AnnotationService._provenance``).
        """
        fields: dict[str, Any] = {"hpo_version": self._version}
        if mode in ("standard", "full"):
            fields["recommended_citation"] = RECOMMENDED_CITATION
        return fields

    # -- resolve_term ----------------------------------------------------------

    def resolve_term(
        self,
        query: str,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        """Resolve any id/label/xref to a canonical HPO term with match provenance.

        Raises:
            InvalidInputError: when ``query`` is empty.
            AmbiguousQueryError: when a label maps to multiple distinct HPO ids.
            NotFoundError: when nothing matches.
        """
        raw = (query or "").strip()
        if not raw:
            raise InvalidInputError(
                "query must be a non-empty HP id, label, or xref.", field="query"
            )
        match_type, hpo_id = self._resolution.classify_resolution(raw)
        record = self._db.get_term(hpo_id)
        if record is None:  # pragma: no cover - defensive
            raise NotFoundError(f"No HPO term for {hpo_id}.")
        out: dict[str, Any] = {
            "query": raw,
            "hpo_id": hpo_id,
            "name": record["name"],
            "match_type": match_type,
            "match_confidence": confidence_for(match_type),
            "obsolete": record["is_obsolete"],
            **self._version_fields(response_mode),
        }
        if record.get("replaced_by"):
            out["replaced_by"] = record["replaced_by"]
        return out

    # -- search_terms ----------------------------------------------------------

    def search_terms(
        self,
        query: str,
        limit: int = 25,
        offset: int = 0,
        include_obsolete: bool = False,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        """Free-text search over HPO name/synonyms/definition.

        Raises:
            InvalidInputError: when ``query`` is empty.
        """
        raw = (query or "").strip()
        if not raw:
            raise InvalidInputError("query must be a non-empty search string.", field="query")
        limit = max(1, min(limit, _MAX_SEARCH_LIMIT))
        offset = max(0, offset)
        hits, total = self._db.search(
            raw, limit=limit, offset=offset, include_obsolete=include_obsolete
        )
        shaped_hits = [shape_search_hit(hit, response_mode) for hit in hits]
        results = [shaped for shaped, _ in shaped_hits]
        # A full-mode page fences one untrusted_text per hit; the page can hold up to
        # _MAX_SEARCH_LIMIT hits, so raise the object ceiling to that recorded cap. The
        # 2 MiB-per-object and 8 MiB-total byte limits remain the real DoS backstop.
        enforce_untrusted_text_limits(
            [obj for _, fenced_objs in shaped_hits for obj in fenced_objs],
            max_objects=_MAX_SEARCH_LIMIT,
        )
        return {
            "query": raw,
            "results": results,
            **page_fields(total=total, returned=len(results), limit=limit, offset=offset),
            **self._version_fields(response_mode),
        }

    # -- get_term --------------------------------------------------------------

    def get_term(
        self,
        term: str,
        response_mode: str = DEFAULT_RESPONSE_MODE,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return the full HPO term record (hierarchy + xrefs) with response-mode projection.

        Raises:
            InvalidInputError: when ``term`` is empty.
            NotFoundError: when nothing matches.
        """
        hpo_id = self._resolve_to_id(term)
        record = self._db.get_term(hpo_id)
        if record is None:  # pragma: no cover - defensive
            raise NotFoundError(f"No HPO term for {hpo_id}.")
        parents = self._db.parents(hpo_id)
        children = self._db.children(hpo_id)
        payload: dict[str, Any] = {
            "hpo_id": hpo_id,
            "name": record["name"],
            "definition": record["definition"],
            "synonyms": record["synonyms"],
            "alt_ids": record["alt_ids"],
            "subsets": record["subsets"],
            "comments": record.get("comments"),
            "obsolete": record["is_obsolete"],
            "replaced_by": record["replaced_by"],
            "parents": parents,
            "children": children,
            **self._version_fields(response_mode),
        }
        shaped, fenced_by_field = shape_term(payload, response_mode)
        projected = select_fields(shaped, fields, known=_TERM_FIELDS)
        # Enforce limits over only the fenced objects that survive sparse-field
        # projection — a projected-out field must not count toward the ceiling.
        emitted = [obj for key, objs in fenced_by_field.items() if key in projected for obj in objs]
        enforce_untrusted_text_limits(emitted)
        return projected

    # -- term_parents / term_children ------------------------------------------

    def term_parents(
        self,
        term: str,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        """Return immediate parents of a term.

        Raises:
            InvalidInputError: when ``term`` is empty.
            NotFoundError: when nothing matches.
        """
        return self._neighbours(term, kind="parents", response_mode=response_mode)

    def term_children(
        self,
        term: str,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        """Return immediate children of a term.

        Raises:
            InvalidInputError: when ``term`` is empty.
            NotFoundError: when nothing matches.
        """
        return self._neighbours(term, kind="children", response_mode=response_mode)

    def _neighbours(
        self, term: str, *, kind: str, response_mode: str = DEFAULT_RESPONSE_MODE
    ) -> dict[str, Any]:
        # response_mode is reserved for future projection of inner term rows
        hpo_id = self._resolve_to_id(term)
        record = self._db.get_term(hpo_id)
        rows = self._db.parents(hpo_id) if kind == "parents" else self._db.children(hpo_id)
        return {
            "hpo_id": hpo_id,
            "name": record["name"] if record else None,
            kind: rows,
            "count": len(rows),
            **self._version_fields(response_mode),
        }

    # -- term_ancestors / term_descendants ------------------------------------

    def term_ancestors(
        self,
        term: str,
        limit: int = 50,
        offset: int = 0,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        """Return paginated transitive ancestors of a term.

        Raises:
            InvalidInputError: when ``term`` is empty.
            NotFoundError: when nothing matches.
        """
        return self._closure(
            term, kind="ancestors", limit=limit, offset=offset, response_mode=response_mode
        )

    def term_descendants(
        self,
        term: str,
        limit: int = 50,
        offset: int = 0,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        """Return paginated transitive descendants of a term.

        Raises:
            InvalidInputError: when ``term`` is empty.
            NotFoundError: when nothing matches.
        """
        return self._closure(
            term, kind="descendants", limit=limit, offset=offset, response_mode=response_mode
        )

    def _closure(
        self,
        term: str,
        *,
        kind: str,
        limit: int,
        offset: int = 0,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        # response_mode is reserved for future projection of inner term rows
        hpo_id = self._resolve_to_id(term)
        record = self._db.get_term(hpo_id)
        limit = max(1, min(limit, _MAX_LIMIT))
        offset = max(0, offset)
        if kind == "ancestors":
            rows = self._db.ancestors(hpo_id, limit=limit, offset=offset)
            total = self._db.count_ancestors(hpo_id)
        else:
            rows = self._db.descendants(hpo_id, limit=limit, offset=offset)
            total = self._db.count_descendants(hpo_id)
        return {
            "hpo_id": hpo_id,
            "name": record["name"] if record else None,
            kind: rows,
            **page_fields(total=total, returned=len(rows), limit=limit, offset=offset),
            **self._version_fields(response_mode),
        }

    # -- resolve_xref ----------------------------------------------------------

    def resolve_xref(
        self,
        xref_id: str,
        limit: int = 25,
        offset: int = 0,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        """Reverse lookup: external xref CURIE -> HPO terms that cross-reference it.

        Raises:
            InvalidInputError: when ``xref_id`` is empty.
        """
        raw = (xref_id or "").strip()
        if not raw:
            raise InvalidInputError(
                "xref_id must be a non-empty CURIE like UMLS:C0151888.", field="xref_id"
            )
        # A CURIE with an UNKNOWN namespace must be rejected, not silently matched on the bare
        # object id across every namespace (issue #28 review: '__NONSENSE__:C0036572' returned
        # the real UMLS:C0036572 term — a fabricated cross-ontology mapping). A bare object id
        # (no ':') is still accepted and matched across namespaces.
        if ":" in raw:
            prefix = raw.split(":", 1)[0]
            if self._db.canonical_xref_prefix(prefix) is None:
                raise InvalidInputError(
                    f"xref_id namespace {prefix!r} is not a known cross-reference vocabulary.",
                    field="xref_id",
                    allowed=self._db.distinct_xref_prefixes(),
                    hint="xref_id is a CURIE PREFIX:local, e.g. UMLS:C0151888.",
                )
        limit = max(1, min(limit, _MAX_LIMIT))
        offset = max(0, offset)
        total = self._db.count_hpo_for_xref(raw)
        matches = self._db.hpo_for_xref(raw, limit=limit, offset=offset)
        results = [{"hpo_id": m["hpo_id"], "name": m["name"]} for m in matches]
        return {
            "xref_id": raw,
            "matches": results,
            **page_fields(total=total, returned=len(results), limit=limit, offset=offset),
            **self._version_fields(response_mode),
        }

    # -- map_cross_ontology ----------------------------------------------------

    def map_cross_ontology(
        self,
        term: str,
        prefixes: list[str] | None = None,
        response_mode: str = DEFAULT_RESPONSE_MODE,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return all cross-ontology mappings for a term, grouped by prefix.

        Raises:
            InvalidInputError: when ``term`` is empty.
            NotFoundError: when nothing matches.
        """
        hpo_id = self._resolve_to_id(term)
        record = self._db.get_term(hpo_id)
        # Validate + canonicalise the prefix filter against the data-derived vocabulary. An
        # unknown prefix is REJECTED (never silently matched to nothing), and a known one is
        # mapped to its actual DB case (no uppercasing — the DB stores 'Fyler', 'ICD-10', ...).
        canonical_prefixes: list[str] | None = None
        if prefixes:
            canonical_prefixes = []
            for prefix in prefixes:
                canonical = self._db.canonical_xref_prefix(prefix)
                if canonical is None:
                    raise InvalidInputError(
                        f"prefix {prefix!r} is not a known cross-reference vocabulary.",
                        field="prefixes",
                        allowed=self._db.distinct_xref_prefixes(),
                        hint="prefixes are xref vocabularies, e.g. ['UMLS', 'SNOMEDCT_US'].",
                    )
                canonical_prefixes.append(canonical)
        xrefs = self._db.xrefs_for(hpo_id, canonical_prefixes)
        mappings: dict[str, list[dict[str, Any]]] = {}
        for xref in xrefs:
            bucket = mappings.setdefault(xref["prefix"], [])
            bucket.append({"object_id": xref["object_id"], "origin": xref.get("origin")})
        payload = {
            "hpo_id": hpo_id,
            "name": record["name"] if record else None,
            "mappings": mappings,
            **self._version_fields(response_mode),
        }
        return select_fields(payload, fields, known=_CROSS_ONTOLOGY_FIELDS)
