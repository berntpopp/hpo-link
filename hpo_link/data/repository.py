"""Read-only SQLite repository for the built Mondo index (CONTRACT BARRIER).

Wave 0 freezes the constructor (read-only connection, ``DataUnavailableError`` on
a missing file) and the method-signature surface downstream depends on. Wave 1B
fills the query bodies against the frozen ``schema.sql``.

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

from hpo_link.constants import NON_HUMAN_ANIMAL_ROOT, PREDICATE_RANK
from hpo_link.exceptions import DataUnavailableError

_FTS_TOKEN_RE = re.compile(r"[^\s\"]+")

#: Stable ``CASE`` expression ranking predicates for ORDER BY (lower = stronger).
_PREDICATE_CASE = (
    "CASE x.predicate "
    + " ".join(f"WHEN '{pred}' THEN {rank}" for pred, rank in PREDICATE_RANK.items())
    + " ELSE 99 END"
)


class MondoRepository:
    """Read-only access to the built Mondo SQLite index."""

    def __init__(self, db_path: Path | str) -> None:
        """Open a read-only connection to the Mondo database."""
        self._path = Path(db_path)
        if not self._path.exists():
            raise DataUnavailableError(
                f"Mondo database not found at {self._path}. Build it with `hpo-link-data build`."
            )
        try:
            self._conn = sqlite3.connect(
                f"file:{self._path}?mode=ro",
                uri=True,
                check_same_thread=False,
            )
        except sqlite3.Error as exc:  # pragma: no cover - rare OS-level failure
            raise DataUnavailableError(
                f"Cannot open Mondo database at {self._path}: {exc}."
            ) from exc
        self._conn.row_factory = sqlite3.Row
        self._xref_label_col: bool | None = None

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
        record: dict[str, Any] = {
            "mondo_id": row["mondo_id"],
            "name": row["name"],
            "definition": row["definition"],
            "is_obsolete": bool(row["is_obsolete"]),
            "replaced_by": row["replaced_by"],
            "consider": _json_or(row["consider"], []),
            "synonyms": _json_or(row["synonyms"], []),
            "subsets": _json_or(row["subsets"], []),
        }
        return record

    # -- provenance ------------------------------------------------------------

    def read_meta(self) -> dict[str, Any]:
        """Return build provenance from the ``meta`` table."""
        try:
            row = self._conn.execute("SELECT * FROM meta WHERE id = 1").fetchone()
        except sqlite3.Error as exc:
            raise DataUnavailableError(
                f"Mondo database at {self._path} is unreadable: {exc}."
            ) from exc
        return dict(row) if row is not None else {}

    # -- term records ----------------------------------------------------------

    def get_term(self, mondo_id: str) -> dict[str, Any] | None:
        """Return the ``term`` row for a canonical MONDO id, or ``None``."""
        row = self._conn.execute("SELECT * FROM term WHERE mondo_id = ?", (mondo_id,)).fetchone()
        return self._term_from_row(row) if row is not None else None

    def resolve_label(self, label: str) -> list[dict[str, Any]]:
        """Resolve a label/synonym to candidate ``(mondo_id, label_type)`` rows."""
        rows = self._conn.execute(
            "SELECT mondo_id, label_type FROM term_lookup WHERE lookup_label = ?",
            (label.upper(),),
        ).fetchall()
        return [{"mondo_id": r["mondo_id"], "label_type": r["label_type"]} for r in rows]

    def search(
        self, query: str, *, limit: int, include_obsolete: bool, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        """Full-text search over name/synonyms/definition; returns ``(rows, total)``."""
        match = self._fts_query(query)
        where = "term_fts MATCH ?"
        if not include_obsolete:
            where += " AND t.is_obsolete = 0"
        sql = (
            "SELECT f.mondo_id, t.name, t.definition, bm25(term_fts) AS score "  # noqa: S608
            "FROM term_fts f JOIN term t ON t.mondo_id = f.mondo_id "
            f"WHERE {where} ORDER BY score LIMIT ? OFFSET ?"
        )
        count_sql = (
            "SELECT COUNT(*) AS n FROM term_fts f JOIN term t ON t.mondo_id = f.mondo_id "  # noqa: S608
            f"WHERE {where}"
        )
        try:
            rows = self._conn.execute(sql, (match, limit, offset)).fetchall()
            total = int(self._conn.execute(count_sql, (match,)).fetchone()["n"])
        except sqlite3.Error:
            return self._search_like(
                query, limit=limit, include_obsolete=include_obsolete, offset=offset
            )
        hits = [
            {
                "mondo_id": r["mondo_id"],
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
        where = "name_upper LIKE ?"
        if not include_obsolete:
            where += " AND is_obsolete = 0"
        rows = self._conn.execute(
            f"SELECT mondo_id, name, definition FROM term WHERE {where} "  # noqa: S608
            "ORDER BY name LIMIT ? OFFSET ?",
            (pattern, limit, offset),
        ).fetchall()
        total = int(
            self._conn.execute(
                f"SELECT COUNT(*) AS n FROM term WHERE {where}",  # noqa: S608
                (pattern,),
            ).fetchone()["n"]
        )
        hits = [
            {
                "mondo_id": r["mondo_id"],
                "name": r["name"],
                "definition": r["definition"],
                "score": 0.0,
            }
            for r in rows
        ]
        return hits, total

    # -- hierarchy -------------------------------------------------------------

    def parents(self, mondo_id: str) -> list[dict[str, Any]]:
        """Immediate parent terms of ``mondo_id``."""
        rows = self._conn.execute(
            "SELECT p.parent_id AS mondo_id, t.name FROM mondo_parent p "
            "LEFT JOIN term t ON t.mondo_id = p.parent_id WHERE p.mondo_id = ? ORDER BY t.name",
            (mondo_id,),
        ).fetchall()
        return [{"mondo_id": r["mondo_id"], "name": r["name"]} for r in rows]

    def children(self, mondo_id: str) -> list[dict[str, Any]]:
        """Immediate child terms of ``mondo_id``."""
        rows = self._conn.execute(
            "SELECT p.mondo_id AS mondo_id, t.name FROM mondo_parent p "
            "LEFT JOIN term t ON t.mondo_id = p.mondo_id WHERE p.parent_id = ? ORDER BY t.name",
            (mondo_id,),
        ).fetchall()
        return [{"mondo_id": r["mondo_id"], "name": r["name"]} for r in rows]

    def ancestors(self, mondo_id: str, *, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        """Transitive ancestors of ``mondo_id`` (via the closure table)."""
        rows = self._conn.execute(
            "SELECT t.mondo_id, t.name FROM mondo_closure c JOIN term t ON t.mondo_id = c.ancestor_id "
            "WHERE c.mondo_id = ? AND c.ancestor_id != ? ORDER BY t.name LIMIT ? OFFSET ?",
            (mondo_id, mondo_id, limit, offset),
        ).fetchall()
        return [{"mondo_id": r["mondo_id"], "name": r["name"]} for r in rows]

    def descendants(self, mondo_id: str, *, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        """Transitive descendants of ``mondo_id`` (via the closure table)."""
        rows = self._conn.execute(
            "SELECT t.mondo_id, t.name FROM mondo_closure c JOIN term t ON t.mondo_id = c.mondo_id "
            "WHERE c.ancestor_id = ? AND c.mondo_id != ? ORDER BY t.name LIMIT ? OFFSET ?",
            (mondo_id, mondo_id, limit, offset),
        ).fetchall()
        return [{"mondo_id": r["mondo_id"], "name": r["name"]} for r in rows]

    def count_ancestors(self, mondo_id: str) -> int:
        """Total transitive ancestors of ``mondo_id`` (excluding self)."""
        return int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM mondo_closure WHERE mondo_id = ? AND ancestor_id != ?",
                (mondo_id, mondo_id),
            ).fetchone()["n"]
        )

    def count_descendants(self, mondo_id: str) -> int:
        """Total transitive descendants of ``mondo_id`` (excluding self)."""
        return int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM mondo_closure WHERE ancestor_id = ? AND mondo_id != ?",
                (mondo_id, mondo_id),
            ).fetchone()["n"]
        )

    def top_groupings(self, mondo_id: str) -> list[dict[str, Any]]:
        """Top-level disease groupings that are ancestors of ``mondo_id``."""
        rows = self._conn.execute(
            "SELECT g.mondo_id, g.name FROM mondo_top_grouping g "
            "JOIN mondo_closure c ON c.ancestor_id = g.mondo_id "
            "WHERE c.mondo_id = ? ORDER BY g.name",
            (mondo_id,),
        ).fetchall()
        return [{"mondo_id": r["mondo_id"], "name": r["name"]} for r in rows]

    def non_human_animal_ids(self, mondo_ids: list[str]) -> set[str]:
        """Subset of ``mondo_ids`` that are the non-human-animal disease root or descend
        from it (Mondo's veterinary branch). One closure query for the whole batch.

        Relies on the closure carrying self-pairs (so the root itself is caught). Used
        by the resolver's human-disease prior to demote livestock terms in fuzzy resolve.
        """
        ids = [m for m in mondo_ids if m]
        if not ids:
            return set()
        placeholders = ", ".join("?" for _ in ids)
        rows = self._conn.execute(
            "SELECT DISTINCT c.mondo_id FROM mondo_closure c "  # noqa: S608
            f"WHERE c.ancestor_id = ? AND c.mondo_id IN ({placeholders})",
            (NON_HUMAN_ANIMAL_ROOT, *ids),
        ).fetchall()
        return {r["mondo_id"] for r in rows}

    # -- cross-references ------------------------------------------------------

    def _has_xref_label(self) -> bool:
        """Whether the xref table carries ``object_label`` (absent on a pre-v2 index).

        Cached so an old volume (built before the column existed) keeps working --
        the query substitutes ``NULL`` rather than raising ``no such column``.
        """
        if self._xref_label_col is None:
            cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(xref)")}
            self._xref_label_col = "object_label" in cols
        return self._xref_label_col

    def xrefs_for(self, mondo_id: str, prefixes: list[str] | None = None) -> list[dict[str, Any]]:
        """Cross-references for ``mondo_id``, optionally filtered by prefix.

        ``object_label`` is the target term's human-readable name (SSSOM only); it is
        ``None`` for OBO xrefs and for any index built before the column existed.
        """
        label_expr = "x.object_label" if self._has_xref_label() else "NULL"
        sql = (
            f"SELECT x.prefix, x.object_id, x.object_id_upper, x.predicate, x.origin, "  # noqa: S608
            f"x.source, {label_expr} AS object_label FROM xref x WHERE x.mondo_id = ?"
        )
        params: list[Any] = [mondo_id]
        if prefixes:
            placeholders = ", ".join("?" for _ in prefixes)
            sql += f" AND x.prefix IN ({placeholders})"
            params.extend(p.upper() for p in prefixes)
        sql += f" ORDER BY {_PREDICATE_CASE}, x.prefix, x.object_id"
        rows = self._conn.execute(sql, tuple(params)).fetchall()
        return [
            {
                "prefix": r["prefix"],
                "object_id": r["object_id"],
                "predicate": r["predicate"],
                "origin": r["origin"],
                "source": r["source"],
                "object_label": r["object_label"],
            }
            for r in rows
        ]

    def mondo_for_xref(self, xref_id: str, *, limit: int, offset: int = 0) -> list[dict[str, Any]]:
        """MONDO terms cross-referencing ``xref_id`` -- ONE row per term (strongest predicate).

        A term can map to the same external id via several rows (e.g. an OBO xref plus
        an SSSOM mapping, or two predicates). ``GROUP BY mondo_id`` with a single
        ``MIN(predicate_rank)`` keeps each term once, and -- per SQLite's bare-column
        rule -- the predicate/origin/object_id come from that strongest-predicate row.
        Collapsing here keeps the row count equal to :meth:`count_mondo_for_xref`, so the
        truncation contract holds (``returned <= total``) and offset-paging advances by
        whole terms rather than by mapping rows.
        """
        rows = self._conn.execute(
            "SELECT x.mondo_id, t.name, x.prefix, x.object_id, x.predicate, x.origin, "  # noqa: S608
            f"MIN({_PREDICATE_CASE}) AS prank "
            "FROM xref x JOIN term t ON t.mondo_id = x.mondo_id "
            "WHERE x.object_id_upper = ? "
            "GROUP BY x.mondo_id ORDER BY prank, t.name LIMIT ? OFFSET ?",
            (xref_id.upper(), limit, offset),
        ).fetchall()
        return [
            {
                "mondo_id": r["mondo_id"],
                "name": r["name"],
                "prefix": r["prefix"],
                "object_id": r["object_id"],
                "predicate": r["predicate"],
                "origin": r["origin"],
            }
            for r in rows
        ]

    def count_mondo_for_xref(self, xref_id: str) -> int:
        """Total distinct MONDO terms mapping to ``xref_id`` (for pagination totals)."""
        return int(
            self._conn.execute(
                "SELECT COUNT(*) AS n FROM "
                "(SELECT DISTINCT x.mondo_id FROM xref x WHERE x.object_id_upper = ?)",
                (xref_id.upper(),),
            ).fetchone()["n"]
        )

    def counts(self) -> dict[str, int]:
        """Return row counts for the principal tables (for diagnostics)."""
        return {
            "terms": self._count("term"),
            "obsolete": int(
                self._conn.execute(
                    "SELECT COUNT(*) AS n FROM term WHERE is_obsolete = 1"
                ).fetchone()["n"]
            ),
            "xrefs": self._count("xref"),
            "closure": self._count("mondo_closure"),
            "top_groupings": self._count("mondo_top_grouping"),
        }

    def _count(self, table: str) -> int:
        return int(self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])  # noqa: S608


def _json_or(value: Any, default: Any) -> Any:
    """Decode a JSON column, returning ``default`` when null/empty/invalid."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):  # pragma: no cover - defensive
        return default
