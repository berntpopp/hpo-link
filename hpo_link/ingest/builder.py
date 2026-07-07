"""Atomic SQLite builder for the HPO hp.json + HPOA releases.

Parses the HPO OBOGraphs JSON (terms, synonyms, OBO xrefs, the is_a graph,
transitive closure) and the HPOA annotation files into a temporary database,
then atomically swaps the finished file into place.
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

import structlog

from hpo_link.constants import SCHEMA_VERSION
from hpo_link.ingest.downloader import _validators_from_results, download_bulk
from hpo_link.ingest.lock import build_lock
from hpo_link.ingest.parser_hpoa import (
    parse_genes_to_disease,
    parse_genes_to_phenotype,
    parse_phenotype_hpoa,
)
from hpo_link.ingest.parser_obo import ParsedOntology, compute_closure, parse_hp_json
from hpo_link.ingest.schema import load_schema_sql

if TYPE_CHECKING:
    from hpo_link.config import ServerSettings

logger = structlog.get_logger()

_BATCH = 5000

_SCOPE_TO_LABEL_TYPE: dict[str, str] = {
    "exact": "exact_synonym",
    "related": "related_synonym",
    "broad": "broad_synonym",
    "narrow": "narrow_synonym",
}


@dataclass
class BuildMeta:
    """Provenance for a built HPO index database (one ``meta`` row)."""

    schema_version: int
    hpo_version: str
    hpoa_version: str
    source_purls: str
    source_validators: str
    term_count: int
    obsolete_count: int
    closure_count: int
    xref_count: int
    disease_phenotype_count: int
    gene_phenotype_count: int
    gene_disease_count: int
    build_utc: str
    build_duration_s: float


@dataclass
class RebuildResult:
    """Outcome of a conditional refresh/rebuild."""

    changed: bool
    not_modified: bool
    meta: BuildMeta | None


def _executemany(conn: sqlite3.Connection, sql: str, rows: list[tuple[Any, ...]]) -> None:
    if rows:
        conn.executemany(sql, rows)


def _load_terms(conn: sqlite3.Connection, parsed: ParsedOntology) -> tuple[int, int]:
    """Insert term / term_lookup / term_fts rows. Returns ``(term_count, obsolete_count)``."""
    term_sql = (
        "INSERT OR REPLACE INTO term "
        "(hpo_id, name, name_upper, definition, is_obsolete, replaced_by, "
        "consider, alt_ids, synonyms, subsets, comments) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    lookup_sql = "INSERT INTO term_lookup (lookup_label, hpo_id, label_type) VALUES (?, ?, ?)"
    fts_sql = "INSERT INTO term_fts (hpo_id, name, synonyms, definition) VALUES (?, ?, ?, ?)"

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

    for hpo_id, rec in parsed.terms.items():
        name = rec.name or ""
        syn_text = " ".join(s["text"] for s in rec.synonyms)
        term_rows.append(
            (
                hpo_id,
                name,
                name.upper(),
                rec.definition,
                1 if rec.is_obsolete else 0,
                rec.replaced_by,
                json.dumps([]),  # consider not in TermRecord
                json.dumps(rec.alt_ids),
                json.dumps(rec.synonyms),
                json.dumps(rec.subsets),
                json.dumps(rec.comments),
            )
        )
        if name:
            lookups.append((name.upper(), hpo_id, "primary"))
        for syn in rec.synonyms:
            label_type = _SCOPE_TO_LABEL_TYPE[syn["scope"]]
            lookups.append((syn["text"].upper(), hpo_id, label_type))
        for alt_id in rec.alt_ids:
            lookups.append((alt_id.upper(), hpo_id, "alt_id"))
        fts_rows.append((hpo_id, name, syn_text, rec.definition or ""))
        count += 1
        if rec.is_obsolete:
            obsolete += 1
        if len(term_rows) >= _BATCH:
            flush()
    flush()
    return count, obsolete


def _load_graph(conn: sqlite3.Connection, parsed: ParsedOntology) -> int:
    """Insert hpo_parent / hpo_closure. Returns closure_count."""
    parent_sql = "INSERT INTO hpo_parent (hpo_id, parent_id) VALUES (?, ?)"
    parent_rows: list[tuple[str, str]] = [
        (hpo_id, parent) for hpo_id, parents in parsed.parents.items() for parent in parents
    ]
    _executemany(conn, parent_sql, parent_rows)

    closure_sql = "INSERT INTO hpo_closure (hpo_id, ancestor_id) VALUES (?, ?)"
    batch: list[tuple[str, str]] = []
    closure_count = 0
    for pair in compute_closure(parsed.parents):
        batch.append(pair)
        closure_count += 1
        if len(batch) >= _BATCH:
            _executemany(conn, closure_sql, batch)
            batch.clear()
    _executemany(conn, closure_sql, batch)
    return closure_count


def _load_xrefs(conn: sqlite3.Connection, parsed: ParsedOntology) -> int:
    """Insert xref rows from OBO xref lines. Returns xref_count."""
    xref_sql = (
        "INSERT INTO xref (hpo_id, prefix, object_id, object_id_upper, origin) "
        "VALUES (?, ?, ?, ?, ?)"
    )
    batch: list[tuple[str, str, str, str, str]] = []
    count = 0
    for hpo_id, rec in parsed.terms.items():
        for x in rec.xrefs:
            obj_id = x["object_id"]
            batch.append((hpo_id, x["prefix"], obj_id, obj_id.upper(), "obo_xref"))
            count += 1
            if len(batch) >= _BATCH:
                _executemany(conn, xref_sql, batch)
                batch.clear()
    _executemany(conn, xref_sql, batch)
    return count


def _load_disease_phenotype(conn: sqlite3.Connection, path: Path | None) -> tuple[int, str]:
    """Insert disease_phenotype rows. Returns (count, hpoa_version)."""
    if path is None or not path.exists():
        return 0, ""
    text = path.read_text(encoding="utf-8", errors="replace")
    version, rows = parse_phenotype_hpoa(text)
    sql = (
        "INSERT INTO disease_phenotype "
        "(database_id, disease_name, hpo_id, qualifier, reference, evidence, "
        "onset, frequency, frequency_hpo, frequency_ratio, frequency_percent, "
        "sex, modifier, aspect, biocuration) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    batch: list[tuple[Any, ...]] = []
    for row in rows:
        batch.append(
            (
                row.database_id,
                row.disease_name,
                row.hpo_id,
                row.qualifier,
                row.reference,
                row.evidence,
                row.onset,
                row.frequency,
                row.frequency_hpo,
                row.frequency_ratio,
                row.frequency_percent,
                row.sex,
                row.modifier,
                row.aspect,
                row.biocuration,
            )
        )
        if len(batch) >= _BATCH:
            _executemany(conn, sql, batch)
            batch.clear()
    _executemany(conn, sql, batch)
    return len(rows), version


def _load_gene_phenotype(conn: sqlite3.Connection, path: Path | None) -> int:
    """Insert gene_phenotype rows. Returns count."""
    if path is None or not path.exists():
        return 0
    text = path.read_text(encoding="utf-8", errors="replace")
    rows = parse_genes_to_phenotype(text)
    sql = (
        "INSERT INTO gene_phenotype "
        "(ncbi_gene_id, gene_symbol, gene_symbol_upper, hpo_id, frequency, disease_id) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    )
    batch: list[tuple[Any, ...]] = []
    for row in rows:
        batch.append(
            (
                row.ncbi_gene_id,
                row.gene_symbol,
                row.gene_symbol.upper(),
                row.hpo_id,
                row.frequency,
                row.disease_id,
            )
        )
        if len(batch) >= _BATCH:
            _executemany(conn, sql, batch)
            batch.clear()
    _executemany(conn, sql, batch)
    return len(rows)


def _load_gene_disease(conn: sqlite3.Connection, path: Path | None) -> int:
    """Insert gene_disease rows. Returns count."""
    if path is None or not path.exists():
        return 0
    text = path.read_text(encoding="utf-8", errors="replace")
    rows = parse_genes_to_disease(text)
    sql = (
        "INSERT INTO gene_disease "
        "(ncbi_gene_id, gene_symbol, gene_symbol_upper, association_type, disease_id, source) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    )
    batch: list[tuple[Any, ...]] = []
    for row in rows:
        batch.append(
            (
                row.ncbi_gene_id,
                row.gene_symbol,
                row.gene_symbol.upper(),
                row.association_type,
                row.disease_id,
                row.source,
            )
        )
        if len(batch) >= _BATCH:
            _executemany(conn, sql, batch)
            batch.clear()
    _executemany(conn, sql, batch)
    return len(rows)


def _insert_meta(conn: sqlite3.Connection, meta: BuildMeta) -> None:
    values = asdict(meta)
    columns = list(values.keys())
    placeholders = ", ".join("?" for _ in columns)
    col_list = ", ".join(columns)
    conn.execute(
        f"INSERT INTO meta (id, {col_list}) VALUES (1, {placeholders})",  # noqa: S608
        tuple(values[col] for col in columns),
    )


def build_database(
    config: ServerSettings,
    *,
    paths: dict[str, Path | None],
    validators: dict[str, dict[str, str | None]],
) -> BuildMeta:
    """Build the HPO SQLite index from the release files, atomically, under the lock."""
    start = time.perf_counter()
    data_dir = config.data.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    ontology_path = paths.get("ontology")
    if ontology_path is None or not ontology_path.exists():
        from hpo_link.exceptions import DataUnavailableError

        raise DataUnavailableError("Required HPO ontology file missing; cannot build index.")

    with build_lock(data_dir, timeout=config.data.build_lock_timeout):
        fd, tmp_name = tempfile.mkstemp(dir=data_dir, suffix=".sqlite.tmp")
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            text = ontology_path.read_text(encoding="utf-8", errors="replace")
            parsed = parse_hp_json(text)
            logger.info("parsed_ontology", terms=len(parsed.terms), version=parsed.version)

            with sqlite3.connect(tmp_path) as conn:
                conn.executescript(load_schema_sql())
                term_count, obsolete_count = _load_terms(conn, parsed)
                closure_count = _load_graph(conn, parsed)
                xref_count = _load_xrefs(conn, parsed)
                dp_count, hpoa_version = _load_disease_phenotype(conn, paths.get("phenotype_hpoa"))
                gp_count = _load_gene_phenotype(conn, paths.get("genes_to_phenotype"))
                gd_count = _load_gene_disease(conn, paths.get("genes_to_disease"))
                conn.execute("INSERT INTO term_fts(term_fts) VALUES ('optimize')")

                source_purls = json.dumps({k: str(v) for k, v in paths.items() if v is not None})
                meta = BuildMeta(
                    schema_version=SCHEMA_VERSION,
                    hpo_version=parsed.version,
                    hpoa_version=hpoa_version,
                    source_purls=source_purls,
                    source_validators=json.dumps(validators),
                    term_count=term_count,
                    obsolete_count=obsolete_count,
                    closure_count=closure_count,
                    xref_count=xref_count,
                    disease_phenotype_count=dp_count,
                    gene_phenotype_count=gp_count,
                    gene_disease_count=gd_count,
                    build_utc=datetime.now(tz=UTC).isoformat(),
                    build_duration_s=round(time.perf_counter() - start, 3),
                )
                _insert_meta(conn, meta)
                conn.commit()
            conn.close()
            os.replace(tmp_path, config.data.db_path)
            logger.info(
                "database_built",
                db=config.data.db_path.name,
                terms=meta.term_count,
                duration_s=meta.build_duration_s,
            )
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
        hpo_version=row["hpo_version"],
        hpoa_version=row["hpoa_version"],
        source_purls=row["source_purls"],
        source_validators=row["source_validators"],
        term_count=row["term_count"],
        obsolete_count=row["obsolete_count"],
        closure_count=row["closure_count"],
        xref_count=row["xref_count"],
        disease_phenotype_count=row["disease_phenotype_count"],
        gene_phenotype_count=row["gene_phenotype_count"],
        gene_disease_count=row["gene_disease_count"],
        build_utc=row["build_utc"],
        build_duration_s=row["build_duration_s"],
    )


def _try_prebuilt(config: ServerSettings) -> Path | None:
    """Try to fetch the prebuilt database artifact.  Returns the db path or ``None``."""
    import httpx

    from hpo_link.ingest.release import fetch_prebuilt_db, find_prebuilt_asset

    db_path = config.data.db_path
    try:
        with httpx.Client(follow_redirects=True, timeout=config.data.download_timeout) as client:
            asset = find_prebuilt_asset(client)
            if asset is None:
                logger.info("no_prebuilt_asset_available")
                return None
            fetch_prebuilt_db(client, asset, db_path)
            logger.info(
                "prebuilt_db_installed",
                hpo_version=asset.hpo_version,
                dest=db_path.name,
            )
            return db_path
    except Exception as exc:
        logger.warning("prebuilt_fetch_failed", error=str(exc))
        return None


def ensure_database(config: ServerSettings) -> Path:
    """Return the database path, building it on first use if configured."""
    db_path = config.data.db_path

    # (1) Already present — return immediately.
    if db_path.exists():
        return db_path

    if not config.data.auto_bootstrap:
        from hpo_link.exceptions import DataUnavailableError

        raise DataUnavailableError(
            "HPO database not built. Run `hpo-link-data build` (or `make data`)."
        )

    # (2) Try prebuilt artifact if preferred.
    if config.data.prefer_prebuilt:
        result = _try_prebuilt(config)
        if result is not None:
            return result

    # (3) Fall back to local download + build.
    if db_path.exists():  # re-check before the (lock-holding) build
        return db_path
    results = download_bulk(config, force=False)
    paths: dict[str, Path | None] = {k: r.path for k, r in results.items()}
    validators = _validators_from_results(results)
    build_database(config, paths=paths, validators=validators)
    return db_path


def rebuild(config: ServerSettings, *, force: bool) -> RebuildResult:
    """Download (conditionally) and rebuild the database, reusing an unchanged build."""
    results = download_bulk(config, force=force)
    all_not_modified = bool(results) and all(r.not_modified for r in results.values())
    if all_not_modified and config.data.db_path.exists():
        existing = read_meta(config.data.db_path)
        if existing is not None:
            return RebuildResult(changed=False, not_modified=True, meta=existing)
    paths: dict[str, Path | None] = {k: r.path for k, r in results.items()}
    validators = _validators_from_results(results)
    meta = build_database(config, paths=paths, validators=validators)
    return RebuildResult(changed=True, not_modified=False, meta=meta)
