"""Read-only SQLite repository for the built HPO index.

All indexes are pre-computed by the builder, so this layer only reads rows and
decodes the JSON list columns. FTS5 queries are sanitized so raw user text never
reaches ``MATCH`` (which can raise on operator characters like ``( : -``).
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from hpo_link.data.annotations_repository import AnnotationsMixin
from hpo_link.exceptions import DataUnavailableError

_FTS_TOKEN_RE = re.compile(r"[^\s\"]+")

#: The label types whose text, when it equals the query verbatim, marks a term as an
#: EXACT match. issue #28 D1: BM25 doc-length normalisation buries a term with many
#: synonyms + a long definition (e.g. HP:0001250 "Seizure") below its shorter, more
#: specific children — so an exact primary-label / exact-synonym hit is boosted to the
#: top of the ranking (still relevance-ordered within each tier) rather than left to
#: sink. Related/broad/narrow synonyms are deliberately NOT boosted (they are not an
#: exact identity match).
_EXACT_LABEL_TYPES = ("primary", "exact_synonym")


def _exact_boost_sql(id_col: str) -> str:
    """A ``1|0`` SQL expression: does ``id_col`` have an EXACT label equal to the query?

    Binds ONE parameter (the uppercased query, matched against ``term_lookup.lookup_label``,
    which the builder stores uppercased). Placed first in ``ORDER BY`` so exact matches sort
    ahead of partial ones.
    """
    return (
        f"EXISTS (SELECT 1 FROM term_lookup tl WHERE tl.hpo_id = {id_col} "  # noqa: S608
        "AND tl.lookup_label = ? AND tl.label_type IN ('primary', 'exact_synonym'))"
    )


class HpoRepository(AnnotationsMixin):
    """Read-only access to the built HPO SQLite index."""

    def __init__(self, db_path: Path | str) -> None:
        """Open a read-only connection to the HPO database."""
        self._path = Path(db_path)
        # Messages are body-free (no filesystem path / sqlite str(exc)): the SQLite path
        # is deployment-layout detail and the raw sqlite error can carry it too. The
        # actionable hint is a STATIC string; the raw cause is preserved only via
        # ``from exc`` (server-side chained cause), never in the caller-visible message.
        if not self._path.exists():
            raise DataUnavailableError(
                "The local HPO database is not available. Build it with `hpo-link-data build`."
            )
        try:
            self._conn = sqlite3.connect(
                f"file:{self._path}?mode=ro&immutable=1",
                uri=True,
                check_same_thread=False,
            )
        except sqlite3.Error as exc:  # pragma: no cover - rare OS-level failure
            raise DataUnavailableError("The local HPO database could not be opened.") from exc
        self._conn.row_factory = sqlite3.Row
        # Caches for the xref-prefix vocabulary (the DB is read-only, so it never changes).
        self._xref_prefixes: list[str] | None = None
        self._xref_prefix_map: dict[str, str] | None = None

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _fts_query(text: str) -> str:
        """Build a safe FTS5 ``MATCH`` string (token AND, last token prefixed).

        Each token is wrapped in double quotes (escaping embedded quotes) so any
        punctuation a user types (``(``, ``:``, ``-``) is treated as literal text
        rather than FTS5 syntax. Returns ``'""'`` for empty/blank input.
        """
        tokens = _FTS_TOKEN_RE.findall(text or "")
        if not tokens:
            return '""'
        quoted: list[str] = []
        for tok in tokens[:-1]:
            quoted.append('"' + tok.replace('"', '""') + '"')
        last = tokens[-1].replace('"', '""')
        quoted.append('"' + last + '"*')
        return " ".join(quoted)

    @staticmethod
    def _term_from_row(row: sqlite3.Row) -> dict[str, Any]:
        """Decode a ``term`` row, parsing the JSON list/object columns."""
        return {
            "hpo_id": row["hpo_id"],
            "name": row["name"],
            "definition": row["definition"],
            "is_obsolete": bool(row["is_obsolete"]),
            "replaced_by": row["replaced_by"],
            "consider": _json_or(row["consider"], []),
            "alt_ids": _json_or(row["alt_ids"], []),
            "synonyms": _json_or(row["synonyms"], []),
            "subsets": _json_or(row["subsets"], []),
            "comments": _json_or(row["comments"], []),
        }

    # -- provenance ------------------------------------------------------------

    def read_meta(self) -> dict[str, Any]:
        """Return build provenance from the ``meta`` table."""
        try:
            row = self._conn.execute("SELECT * FROM meta WHERE id = 1").fetchone()
        except sqlite3.Error as exc:
            raise DataUnavailableError("The local HPO database could not be read.") from exc
        return dict(row) if row is not None else {}

    # -- term records ----------------------------------------------------------

    def get_term(self, hpo_id: str) -> dict[str, Any] | None:
        """Return the ``term`` row for a canonical HP id, or ``None``."""
        row = self._conn.execute("SELECT * FROM term WHERE hpo_id = ?", (hpo_id,)).fetchone()
        return self._term_from_row(row) if row is not None else None

    def resolve_label(self, label: str) -> list[dict[str, Any]]:
        """Resolve a label/synonym to candidate ``(hpo_id, label_type)`` rows."""
        rows = self._conn.execute(
            "SELECT hpo_id, label_type FROM term_lookup WHERE lookup_label = ?",
            (label.upper(),),
        ).fetchall()
        return [{"hpo_id": r["hpo_id"], "label_type": r["label_type"]} for r in rows]

    def search(
        self, query: str, *, limit: int, include_obsolete: bool, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        """Full-text search over name/synonyms/definition; returns ``(rows, total)``."""
        match = self._fts_query(query)
        exact_label = (query or "").strip().upper()
        where = "term_fts MATCH ?"
        if not include_obsolete:
            where += " AND t.is_obsolete = 0"
        # Exact primary-label / exact-synonym matches sort ahead of partial ones (D1); within
        # each tier the bm25 relevance order is preserved. The boost subquery's `?` is bound
        # FIRST (it appears in the SELECT, before the WHERE MATCH `?`).
        sql = (
            f"SELECT f.hpo_id, t.name, t.definition, bm25(term_fts) AS score, "  # noqa: S608
            f"{_exact_boost_sql('f.hpo_id')} AS exact_boost "
            "FROM term_fts f JOIN term t ON t.hpo_id = f.hpo_id "
            f"WHERE {where} ORDER BY exact_boost DESC, score LIMIT ? OFFSET ?"
        )
        count_sql = (
            "SELECT COUNT(*) AS n FROM term_fts f "  # noqa: S608
            "JOIN term t ON t.hpo_id = f.hpo_id "
            f"WHERE {where}"
        )
        try:
            rows = self._conn.execute(sql, (exact_label, match, limit, offset)).fetchall()
            total = int(self._conn.execute(count_sql, (match,)).fetchone()["n"])
        except sqlite3.Error:
            return self._search_like(
                query, limit=limit, include_obsolete=include_obsolete, offset=offset
            )
        hits = [
            {
                "hpo_id": r["hpo_id"],
                "name": r["name"],
                "definition": r["definition"],
                "score": round(-r["score"], 4) if r["score"] else 0.0,
            }
            for r in rows
        ]
        return hits, total

    def _search_like(
        self, query: str, *, limit: int, include_obsolete: bool, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        """``LIKE`` fallback for pathological FTS input."""
        pattern = "%" + query.upper().replace("%", "").replace("_", "") + "%"
        exact_label = (query or "").strip().upper()
        where = "name_upper LIKE ?"
        if not include_obsolete:
            where += " AND is_obsolete = 0"
        # Same exact-match boost as the FTS path (D1): the boost `?` is bound first (SELECT),
        # then the LIKE pattern (WHERE). Keeps the two search paths consistent.
        rows = self._conn.execute(
            f"SELECT hpo_id, name, definition, {_exact_boost_sql('term.hpo_id')} "  # noqa: S608
            f"AS exact_boost FROM term WHERE {where} "
            "ORDER BY exact_boost DESC, name LIMIT ? OFFSET ?",
            (exact_label, pattern, limit, offset),
        ).fetchall()
        total = int(
            self._conn.execute(
                f"SELECT COUNT(*) AS n FROM term WHERE {where}",  # noqa: S608
                (pattern,),
            ).fetchone()["n"]
        )
        hits = [
            {
                "hpo_id": r["hpo_id"],
                "name": r["name"],
                "definition": r["definition"],
                "score": 0.0,
            }
            for r in rows
        ]
        return hits, total

    # -- hierarchy -------------------------------------------------------------

    def parents(self, hpo_id: str) -> list[dict[str, Any]]:
        """Immediate parent terms of ``hpo_id``."""
        rows = self._conn.execute(
            "SELECT p.parent_id AS hpo_id, t.name FROM hpo_parent p "
            "LEFT JOIN term t ON t.hpo_id = p.parent_id WHERE p.hpo_id = ? ORDER BY t.name",
            (hpo_id,),
        ).fetchall()
        return [{"hpo_id": r["hpo_id"], "name": r["name"]} for r in rows]

    def children(self, hpo_id: str) -> list[dict[str, Any]]:
        """Immediate child terms of ``hpo_id``."""
        rows = self._conn.execute(
            "SELECT p.hpo_id AS hpo_id, t.name FROM hpo_parent p "
            "LEFT JOIN term t ON t.hpo_id = p.hpo_id WHERE p.parent_id = ? ORDER BY t.name",
            (hpo_id,),
        ).fetchall()
        return [{"hpo_id": r["hpo_id"], "name": r["name"]} for r in rows]

    def ancestors(self, hpo_id: str, *, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        """Transitive ancestors of ``hpo_id`` (via the closure table)."""
        rows = self._conn.execute(
            "SELECT t.hpo_id, t.name FROM hpo_closure c "
            "JOIN term t ON t.hpo_id = c.ancestor_id "
            "WHERE c.hpo_id = ? AND c.ancestor_id != ? ORDER BY t.name LIMIT ? OFFSET ?",
            (hpo_id, hpo_id, limit, offset),
        ).fetchall()
        return [{"hpo_id": r["hpo_id"], "name": r["name"]} for r in rows]

    def descendants(self, hpo_id: str, *, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        """Transitive descendants of ``hpo_id`` (via the closure table)."""
        rows = self._conn.execute(
            "SELECT t.hpo_id, t.name FROM hpo_closure c "
            "JOIN term t ON t.hpo_id = c.hpo_id "
            "WHERE c.ancestor_id = ? AND c.hpo_id != ? ORDER BY t.name LIMIT ? OFFSET ?",
            (hpo_id, hpo_id, limit, offset),
        ).fetchall()
        return [{"hpo_id": r["hpo_id"], "name": r["name"]} for r in rows]

    def count_ancestors(self, hpo_id: str) -> int:
        """Total transitive ancestors of ``hpo_id`` (excluding self)."""
        return int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM hpo_closure WHERE hpo_id = ? AND ancestor_id != ?",
                (hpo_id, hpo_id),
            ).fetchone()["n"]
        )

    def count_descendants(self, hpo_id: str) -> int:
        """Total transitive descendants of ``hpo_id`` (excluding self)."""
        return int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM hpo_closure WHERE ancestor_id = ? AND hpo_id != ?",
                (hpo_id, hpo_id),
            ).fetchone()["n"]
        )

    # -- cross-references ------------------------------------------------------

    def distinct_xref_prefixes(self) -> list[str]:
        """The xref namespace prefixes present in the DB, in their ACTUAL case.

        The vocabulary is release-dependent but closed and knowable (issue #28 review): it
        is derived from the data, never hardcoded, so it stays correct across HPO releases.
        Cached — the DB is read-only.
        """
        if self._xref_prefixes is None:
            rows = self._conn.execute("SELECT DISTINCT prefix FROM xref ORDER BY prefix").fetchall()
            self._xref_prefixes = [r["prefix"] for r in rows]
        return self._xref_prefixes

    def canonical_xref_prefix(self, prefix: str) -> str | None:
        """Map a caller-supplied prefix to the DB's actual-case prefix, or ``None`` if unknown.

        Case-insensitive on input (accepts ``umls``/``UMLS``/``Umls``) but returns the DB's
        stored case (e.g. ``Fyler``, ``SNOMEDCT_US``) — the ``xref`` table stores mixed-case
        prefixes, so uppercasing the filter (the old bug) matched none of ``Fyler``/``ICD-10``.
        """
        if self._xref_prefix_map is None:
            self._xref_prefix_map = {p.upper(): p for p in self.distinct_xref_prefixes()}
        return self._xref_prefix_map.get((prefix or "").strip().upper())

    def xrefs_for(self, hpo_id: str, prefixes: list[str] | None = None) -> list[dict[str, Any]]:
        """Cross-references for ``hpo_id``, optionally filtered by prefix.

        ``prefixes`` are matched in their ACTUAL DB case (the caller is expected to have
        canonicalised them via :meth:`canonical_xref_prefix`); they are NOT uppercased here.
        """
        sql = "SELECT x.prefix, x.object_id, x.origin FROM xref x WHERE x.hpo_id = ?"
        params: list[Any] = [hpo_id]
        if prefixes:
            placeholders = ", ".join("?" for _ in prefixes)
            sql += f" AND x.prefix IN ({placeholders})"
            params.extend(prefixes)
        sql += " ORDER BY x.prefix, x.object_id"
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [
            {"prefix": r["prefix"], "object_id": r["object_id"], "origin": r["origin"]}
            for r in rows
        ]

    def _xref_match(self, xref_id: str) -> tuple[str, list[Any]] | None:
        """Return ``(WHERE-fragment, params)`` matching an xref by object id, namespace-aware.

        A CURIE (``PREFIX:body``) matches ONLY within that namespace (canonicalised
        case-insensitively). An UNKNOWN namespace returns ``None`` — the object id alone must
        never span namespaces, which would fabricate a mapping (issue #28 review: a foreign
        prefix on a real UMLS object id returned the UMLS term). A bare object id (no ``:``)
        matches across all namespaces.
        """
        if ":" in xref_id:
            prefix, obj = xref_id.split(":", 1)
            canonical = self.canonical_xref_prefix(prefix)
            if canonical is None:
                return None
            return "x.object_id_upper = ? AND x.prefix = ?", [obj.upper(), canonical]
        return "x.object_id_upper = ?", [xref_id.upper()]

    def hpo_for_xref(self, xref_id: str, *, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        """HPO terms cross-referencing ``xref_id`` (one row per distinct HP id).

        ``xref_id`` may be a bare object id (``C0151888``) or a CURIE (``UMLS:C0151888``). A
        CURIE is matched WITHIN its namespace; an unrecognised namespace matches nothing.
        """
        match = self._xref_match(xref_id)
        if match is None:
            return []
        where, params = match
        rows = self._conn.execute(
            "SELECT DISTINCT x.hpo_id, t.name FROM xref x "  # noqa: S608 - fixed fragment
            f"JOIN term t ON t.hpo_id = x.hpo_id WHERE {where} "
            "ORDER BY t.name LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [{"hpo_id": r["hpo_id"], "name": r["name"]} for r in rows]

    def count_hpo_for_xref(self, xref_id: str) -> int:
        """Total distinct HPO terms mapping to ``xref_id`` (for pagination totals)."""
        match = self._xref_match(xref_id)
        if match is None:
            return 0
        where, params = match
        return int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM "  # noqa: S608 - fixed fragment
                f"(SELECT DISTINCT x.hpo_id FROM xref x WHERE {where})",
                tuple(params),
            ).fetchone()["n"]
        )

    def counts(self) -> dict[str, int]:
        """Return row counts for all principal tables (for diagnostics fallback).

        Keys exactly match the diagnostics counts dict:
        ``terms, obsolete, closure, xref, disease_phenotype, gene_phenotype, gene_disease``.
        """
        return {
            "terms": self._count("term"),
            "obsolete": int(
                self._conn.execute(
                    "SELECT COUNT(*) AS n FROM term WHERE is_obsolete = 1"
                ).fetchone()["n"]
            ),
            "closure": self._count("hpo_closure"),
            "xref": self._count("xref"),
            "disease_phenotype": self._count("disease_phenotype"),
            "gene_phenotype": self._count("gene_phenotype"),
            "gene_disease": self._count("gene_disease"),
        }

    def _count(self, table: str) -> int:
        return int(
            self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]  # noqa: S608
        )


def _json_or(value: Any, default: Any) -> Any:
    """Decode a JSON column, returning ``default`` when null/empty/invalid."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):  # pragma: no cover - defensive
        return default
