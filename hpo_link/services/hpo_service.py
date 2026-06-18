"""Orchestration over the read-only HPO repository.

Returns plain dicts (no envelope); the MCP layer owns ``success``/``_meta``.
Every record payload carries ``hpo_version`` (from build provenance) for
grounding. The resolution cascade (HP id -> primary/synonym label -> external
xref CURIE) returns the match provenance and raises typed exceptions instead of
silently collapsing ambiguity.
"""

from __future__ import annotations

from typing import Any

import structlog

from hpo_link.constants import RECOMMENDED_CITATION
from hpo_link.data.repository import HpoRepository
from hpo_link.exceptions import InvalidInputError, NotFoundError
from hpo_link.services.pagination import page_fields
from hpo_link.services.resolution import Resolver
from hpo_link.services.shaping import (
    DEFAULT_RESPONSE_MODE,
    select_fields,
    shape_search_hit,
    shape_term,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_MAX_LIMIT = 1000


class HpoService:
    """Service layer over the read-only HPO SQLite index."""

    def __init__(self, repo: HpoRepository) -> None:
        """Bind the service to a pre-opened HPO repository."""
        self._repo = repo
        self._hpo_version: str | None = None

    # -- provenance ------------------------------------------------------------

    @property
    def _version(self) -> str | None:
        """Return the built HPO release string (lazily cached)."""
        if self._hpo_version is None:
            meta = self._repo.read_meta()
            self._hpo_version = meta.get("hpo_version") if meta else None
        return self._hpo_version

    @property
    def _resolution(self) -> Resolver:
        """Resolver bound to the repository."""
        return Resolver(self._repo)

    # -- internal helpers ------------------------------------------------------

    def _resolve_to_id(self, query: str) -> str:
        """Resolve any HP id / label / xref to a canonical HP id, raise NotFoundError on miss."""
        raw = (query or "").strip()
        if not raw:
            raise InvalidInputError(
                "term must be a non-empty HP id, label, or xref.", field="term"
            )
        return self._resolution.resolve_term_id(raw)

    def _version_fields(self) -> dict[str, Any]:
        """Return version + citation anchors appended to every response."""
        return {
            "hpo_version": self._version,
            "recommended_citation": RECOMMENDED_CITATION,
        }

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
        record = self._repo.get_term(hpo_id)
        if record is None:  # pragma: no cover - defensive
            raise NotFoundError(f"No HPO term for {hpo_id}.")
        out: dict[str, Any] = {
            "query": raw,
            "hpo_id": hpo_id,
            "name": record["name"],
            "match_type": match_type,
            "obsolete": record["is_obsolete"],
            **self._version_fields(),
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
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        hits, total = self._repo.search(
            raw, limit=limit, offset=offset, include_obsolete=include_obsolete
        )
        results = [shape_search_hit(hit, response_mode) for hit in hits]
        return {
            "query": raw,
            "results": results,
            **page_fields(total=total, returned=len(results), limit=limit, offset=offset),
            **self._version_fields(),
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
        record = self._repo.get_term(hpo_id)
        if record is None:  # pragma: no cover - defensive
            raise NotFoundError(f"No HPO term for {hpo_id}.")
        parents = self._repo.parents(hpo_id)
        children = self._repo.children(hpo_id)
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
            **self._version_fields(),
        }
        shaped = shape_term(payload, response_mode)
        return select_fields(shaped, fields)

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
        return self._neighbours(term, kind="parents")

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
        return self._neighbours(term, kind="children")

    def _neighbours(self, term: str, *, kind: str) -> dict[str, Any]:
        hpo_id = self._resolve_to_id(term)
        record = self._repo.get_term(hpo_id)
        rows = self._repo.parents(hpo_id) if kind == "parents" else self._repo.children(hpo_id)
        return {
            "hpo_id": hpo_id,
            "name": record["name"] if record else None,
            kind: rows,
            "count": len(rows),
            **self._version_fields(),
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
        return self._closure(term, kind="ancestors", limit=limit, offset=offset)

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
        return self._closure(term, kind="descendants", limit=limit, offset=offset)

    def _closure(self, term: str, *, kind: str, limit: int, offset: int = 0) -> dict[str, Any]:
        hpo_id = self._resolve_to_id(term)
        record = self._repo.get_term(hpo_id)
        limit = max(1, min(limit, _MAX_LIMIT))
        offset = max(0, offset)
        if kind == "ancestors":
            rows = self._repo.ancestors(hpo_id, limit=limit, offset=offset)
            total = self._repo.count_ancestors(hpo_id)
        else:
            rows = self._repo.descendants(hpo_id, limit=limit, offset=offset)
            total = self._repo.count_descendants(hpo_id)
        return {
            "hpo_id": hpo_id,
            "name": record["name"] if record else None,
            kind: rows,
            **page_fields(total=total, returned=len(rows), limit=limit, offset=offset),
            **self._version_fields(),
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
        limit = max(1, min(limit, _MAX_LIMIT))
        offset = max(0, offset)
        total = self._repo.count_hpo_for_xref(raw)
        matches = self._repo.hpo_for_xref(raw, limit=limit, offset=offset)
        results = [{"hpo_id": m["hpo_id"], "name": m["name"]} for m in matches]
        return {
            "xref_id": raw,
            "matches": results,
            **page_fields(total=total, returned=len(results), limit=limit, offset=offset),
            **self._version_fields(),
        }

    # -- map_cross_ontology ----------------------------------------------------

    def map_cross_ontology(
        self,
        term: str,
        prefixes: list[str] | None = None,
        response_mode: str = DEFAULT_RESPONSE_MODE,
    ) -> dict[str, Any]:
        """Return all cross-ontology mappings for a term, grouped by prefix.

        Raises:
            InvalidInputError: when ``term`` is empty.
            NotFoundError: when nothing matches.
        """
        hpo_id = self._resolve_to_id(term)
        record = self._repo.get_term(hpo_id)
        normalized = [p.strip().upper() for p in prefixes if p.strip()] if prefixes else None
        xrefs = self._repo.xrefs_for(hpo_id, normalized)
        mappings: dict[str, list[dict[str, Any]]] = {}
        for xref in xrefs:
            bucket = mappings.setdefault(xref["prefix"], [])
            bucket.append({"object_id": xref["object_id"], "origin": xref.get("origin")})
        return {
            "hpo_id": hpo_id,
            "name": record["name"] if record else None,
            "mappings": mappings,
            **self._version_fields(),
        }
