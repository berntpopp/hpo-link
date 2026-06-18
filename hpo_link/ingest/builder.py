"""Atomic SQLite builder for the Mondo OBO + SSSOM releases.

Parses the Mondo OBO (terms, synonyms, OBO xrefs, the is_a graph, transitive
closure, top-level groupings) and the SSSOM cross-ontology mappings into a
temporary database, then atomically swaps the finished file into place. Callers
get back a typed :class:`BuildMeta`.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hpo_link.constants import SCHEMA_VERSION
from hpo_link.identifiers import xref_prefix
from hpo_link.ingest.downloader import BulkDownload, download_bulk
from hpo_link.ingest.lock import build_lock
from hpo_link.ingest.parser import (
    mondo_closure_pairs,
    mondo_top_groupings,
    parse_mondo_obo,
    parse_mondo_sssom,
    parse_obo_header,
)
from hpo_link.ingest.schema import load_schema_sql

if TYPE_CHECKING:
    from hpo_link.config import ServerSettings

_BATCH = 5000

_SCOPE_TO_LABEL_TYPE = {
    "EXACT": "exact_synonym",
    "RELATED": "related_synonym",
    "BROAD": "broad_synonym",
    "NARROW": "narrow_synonym",
}


@dataclass
class BuildMeta:
    """Provenance for a built Mondo index database (one ``meta`` row)."""

    schema_version: int
    mondo_version: str | None
    source_purls: str
    source_validators: str
    term_count: int
    obsolete_count: int
    closure_count: int
    xref_count: int
    mapping_count: int
    build_utc: str
    build_duration_s: float | None


@dataclass
class RebuildResult:
    """Outcome of a conditional refresh/rebuild."""

    changed: bool
    not_modified: bool
    meta: BuildMeta | None


def _executemany(conn: sqlite3.Connection, sql: str, rows: list[tuple[Any, ...]]) -> None:
    if rows:
        conn.executemany(sql, rows)


def _load_terms(conn: sqlite3.Connection, terms: dict[str, dict[str, Any]]) -> tuple[int, int]:
    """Insert term / term_lookup / term_fts rows. Returns ``(term_count, obsolete)``."""
    term_sql = (
        "INSERT OR REPLACE INTO term (mondo_id, name, name_upper, definition, is_obsolete, "
        "replaced_by, consider, synonyms, subsets) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    lookup_sql = "INSERT INTO term_lookup (lookup_label, mondo_id, label_type) VALUES (?, ?, ?)"
    fts_sql = "INSERT INTO term_fts (mondo_id, name, synonyms, definition) VALUES (?, ?, ?, ?)"

    term_rows: list[tuple[Any, ...]] = []
    lookups: list[tuple[str, str, str]] = []
    fts_rows: list[tuple[Any, ...]] = []
    count = 0
    obsolete = 0

    def flush() -> None:
        _executemany(conn, term_sql, term_rows)
        _executemany(conn, lookup_sql, lookups)
        _executemany(conn, fts_sql, fts_rows)
        term_rows.clear()
        lookups.clear()
        fts_rows.clear()

    for mondo_id, term in terms.items():
        name = term.get("name") or ""
        synonyms = term.get("synonyms", [])
        syn_text = " ".join(s["text"] for s in synonyms)
        term_rows.append(
            (
                mondo_id,
                name,
                name.upper(),
                term.get("definition"),
                1 if term.get("obsolete") else 0,
                term.get("replaced_by"),
                json.dumps(term.get("consider", [])),
                json.dumps(synonyms),
                json.dumps(term.get("subsets", [])),
            )
        )
        if name:
            lookups.append((name.upper(), mondo_id, "primary"))
        for syn in synonyms:
            label_type = _SCOPE_TO_LABEL_TYPE.get(syn["scope"])
            if label_type:
                lookups.append((syn["text"].upper(), mondo_id, label_type))
        fts_rows.append((mondo_id, name, syn_text, term.get("definition") or ""))
        count += 1
        if term.get("obsolete"):
            obsolete += 1
        if len(term_rows) >= _BATCH:
            flush()
    flush()
    return count, obsolete


def _load_graph(conn: sqlite3.Connection, terms: dict[str, dict[str, Any]]) -> int:
    """Insert mondo_parent / mondo_closure / mondo_top_grouping. Returns closure count."""
    parent_sql = "INSERT INTO mondo_parent (mondo_id, parent_id) VALUES (?, ?)"
    parent_rows = [
        (mondo_id, parent) for mondo_id, term in terms.items() for parent in term.get("parents", [])
    ]
    _executemany(conn, parent_sql, parent_rows)

    closure_sql = "INSERT INTO mondo_closure (mondo_id, ancestor_id) VALUES (?, ?)"
    batch: list[tuple[str, str]] = []
    closure_count = 0
    for pair in mondo_closure_pairs(terms):
        batch.append(pair)
        closure_count += 1
        if len(batch) >= _BATCH:
            _executemany(conn, closure_sql, batch)
            batch.clear()
    _executemany(conn, closure_sql, batch)

    grouping_sql = (
        "INSERT OR REPLACE INTO mondo_top_grouping (mondo_id, name, display_order) VALUES (?, ?, ?)"
    )
    _executemany(
        conn,
        grouping_sql,
        [(mondo_id, name, order) for mondo_id, name, order in mondo_top_groupings(terms)],
    )
    return closure_count


def _load_obo_xrefs(conn: sqlite3.Connection, terms: dict[str, dict[str, Any]]) -> int:
    """Insert xref rows from the OBO ``xref:`` lines (origin ``obo_xref``)."""
    xref_sql = (
        "INSERT INTO xref (mondo_id, prefix, object_id, object_id_upper, predicate, origin, "
        "source, object_label) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    batch: list[tuple[Any, ...]] = []
    count = 0
    for mondo_id, term in terms.items():
        for x in term.get("xrefs", []):
            object_id = x["object_id"]
            batch.append(
                (
                    mondo_id,
                    x["prefix"],
                    object_id,
                    object_id.upper(),
                    x["predicate"],
                    "obo_xref",
                    x.get("source"),
                    None,  # OBO xrefs carry no target label
                )
            )
            count += 1
            if len(batch) >= _BATCH:
                _executemany(conn, xref_sql, batch)
                batch.clear()
    _executemany(conn, xref_sql, batch)
    return count


def _load_sssom(conn: sqlite3.Connection, path: Path | None) -> int:
    """Insert xref rows from the SSSOM table (origin ``sssom``). Returns mapping count."""
    if path is None or not path.exists():
        return 0
    xref_sql = (
        "INSERT INTO xref (mondo_id, prefix, object_id, object_id_upper, predicate, origin, "
        "source, object_label) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    batch: list[tuple[Any, ...]] = []
    count = 0
    for row in parse_mondo_sssom(path.read_text(encoding="utf-8", errors="replace")):
        object_id = row["object_id"]
        batch.append(
            (
                row["subject_id"],
                xref_prefix(object_id),
                object_id,
                object_id.upper(),
                row["predicate"],
                "sssom",
                row.get("source"),
                row.get("object_label"),
            )
        )
        count += 1
        if len(batch) >= _BATCH:
            _executemany(conn, xref_sql, batch)
            batch.clear()
    _executemany(conn, xref_sql, batch)
    return count


def _insert_meta(conn: sqlite3.Connection, meta: BuildMeta) -> None:
    values = asdict(meta)
    columns = list(values.keys())  # dataclass field names, not user input
    placeholders = ", ".join("?" for _ in columns)
    col_list = ", ".join(columns)
    conn.execute(
        f"INSERT INTO meta (id, {col_list}) VALUES (1, {placeholders})",  # noqa: S608
        tuple(values[col] for col in columns),
    )


def _need_obo(paths: dict[str, Path | None]) -> Path:
    obo = paths.get("obo")
    if obo is None or not obo.exists():
        from hpo_link.exceptions import DataUnavailableError

        raise DataUnavailableError("Required Mondo OBO release missing; cannot build index.")
    return obo


def build_database(
    config: ServerSettings,
    *,
    paths: dict[str, Path | None],
    validators: dict[str, dict[str, str | None]],
) -> BuildMeta:
    """Build the Mondo SQLite index from the release files, atomically, under the lock."""
    start = time.perf_counter()
    data_dir = config.data.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    obo_path = _need_obo(paths)
    sssom_path = paths.get("sssom")

    with build_lock(data_dir, timeout=config.data.build_lock_timeout):
        fd, tmp_name = tempfile.mkstemp(dir=data_dir, suffix=".sqlite.tmp")
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            obo_text = obo_path.read_text(encoding="utf-8", errors="replace")
            terms = parse_mondo_obo(obo_text)
            mondo_version = parse_obo_header(obo_text).get("data_version")

            conn = sqlite3.connect(tmp_path)
            try:
                conn.executescript(load_schema_sql())
                term_count, obsolete_count = _load_terms(conn, terms)
                closure_count = _load_graph(conn, terms)
                xref_count = _load_obo_xrefs(conn, terms)
                mapping_count = _load_sssom(conn, sssom_path)
                xref_count += mapping_count
                conn.execute("INSERT INTO term_fts(term_fts) VALUES ('optimize')")

                meta = BuildMeta(
                    schema_version=SCHEMA_VERSION,
                    mondo_version=mondo_version,
                    source_purls=json.dumps(
                        {"obo": config.data.obo_url, "sssom": config.data.sssom_url}
                    ),
                    source_validators=json.dumps(validators),
                    term_count=term_count,
                    obsolete_count=obsolete_count,
                    closure_count=closure_count,
                    xref_count=xref_count,
                    mapping_count=mapping_count,
                    build_utc=datetime.now(tz=UTC).isoformat(),
                    build_duration_s=round(time.perf_counter() - start, 3),
                )
                _insert_meta(conn, meta)
                conn.commit()
            finally:
                conn.close()
            os.replace(tmp_path, config.data.db_path)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise
    return meta


def read_meta(db_path: Path) -> BuildMeta | None:
    """Read provenance from an existing database, or ``None`` if absent."""
    if not db_path.exists():
        return None
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM meta WHERE id = 1").fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return BuildMeta(
        schema_version=row["schema_version"],
        mondo_version=row["mondo_version"],
        source_purls=row["source_purls"],
        source_validators=row["source_validators"],
        term_count=row["term_count"],
        obsolete_count=row["obsolete_count"],
        closure_count=row["closure_count"],
        xref_count=row["xref_count"],
        mapping_count=row["mapping_count"],
        build_utc=row["build_utc"],
        build_duration_s=row["build_duration_s"],
    )


def _build_from_download(config: ServerSettings, download: BulkDownload) -> BuildMeta:
    paths = {key: download.path(key) for key in download.results}
    return build_database(config, paths=paths, validators=download.validators())


def ensure_database(config: ServerSettings) -> Path:
    """Return the database path, building it on first use if configured."""
    db_path = config.data.db_path
    if db_path.exists():
        return db_path
    if not config.data.auto_bootstrap:
        from hpo_link.exceptions import DataUnavailableError

        raise DataUnavailableError(
            "Mondo database not built. Run `hpo-link-data build` (or `make data`)."
        )
    if db_path.exists():  # re-check before the (lock-holding) build
        return db_path
    download = download_bulk(config, force=False)
    _build_from_download(config, download)
    return db_path


def rebuild(config: ServerSettings, *, force: bool) -> RebuildResult:
    """Download (conditionally) and rebuild the database, reusing an unchanged build."""
    download = download_bulk(config, force=force)
    if download.not_modified and config.data.db_path.exists():
        existing = read_meta(config.data.db_path)
        if existing is not None:
            return RebuildResult(changed=False, not_modified=True, meta=existing)
    meta = _build_from_download(config, download)
    return RebuildResult(changed=True, not_modified=False, meta=meta)
