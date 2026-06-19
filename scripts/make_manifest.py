#!/usr/bin/env python3
"""Generate manifest.json for a prebuilt HPO database artifact.

Usage:
    uv run python scripts/make_manifest.py <DATE>

where DATE is the HPO release date, e.g. ``2026-06-06``.  The script reads
``data/hpo.sqlite`` (``meta`` table) and ``hpo-<DATE>.sqlite.zst`` from the
current directory, then writes ``manifest.json``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    if len(sys.argv) != 2:  # noqa: PLR2004
        print(f"Usage: {sys.argv[0]} <DATE>", file=sys.stderr)
        sys.exit(1)

    date = sys.argv[1]
    zst_name = f"hpo-{date}.sqlite.zst"
    db_path = Path("data/hpo.sqlite")
    zst_path = Path(zst_name)

    if not db_path.exists():
        print(f"ERROR: {db_path} not found. Run `uv run hpo-link-data build` first.", file=sys.stderr)
        sys.exit(2)
    if not zst_path.exists():
        print(f"ERROR: {zst_path} not found. Run `zstd -19 -f {db_path} -o {zst_name}` first.", file=sys.stderr)
        sys.exit(2)

    # Read meta row from the SQLite database
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM meta WHERE id = 1").fetchone()
    finally:
        conn.close()

    if row is None:
        print("ERROR: meta table row not found in database.", file=sys.stderr)
        sys.exit(3)

    hpo_version = row["hpo_version"]
    hpoa_version = row["hpoa_version"]
    schema_version = row["schema_version"]
    counts = {
        "term_count": row["term_count"],
        "obsolete_count": row["obsolete_count"],
        "closure_count": row["closure_count"],
        "xref_count": row["xref_count"],
        "disease_phenotype_count": row["disease_phenotype_count"],
        "gene_phenotype_count": row["gene_phenotype_count"],
        "gene_disease_count": row["gene_disease_count"],
    }

    sqlite_bytes = db_path.stat().st_size
    zst_bytes = zst_path.stat().st_size
    sha256 = _sha256_file(zst_path)

    manifest = {
        "hpo_version": hpo_version,
        "hpoa_version": hpoa_version,
        "schema_version": schema_version,
        "sqlite_zst": zst_name,
        "sha256": sha256,
        "sqlite_bytes": sqlite_bytes,
        "zst_bytes": zst_bytes,
        "counts": counts,
        "built_utc": datetime.now(tz=UTC).isoformat(),
    }

    out_path = Path("manifest.json")
    out_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"  hpo_version={hpo_version}  sha256={sha256[:16]}...  zst_bytes={zst_bytes}")


if __name__ == "__main__":
    main()
