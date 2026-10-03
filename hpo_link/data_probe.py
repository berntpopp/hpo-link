"""Read-only semantic proof of the materialized HPO release for fleet admission."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from hpo_link.config import ImmutableDataRequirement, ServerSettings
from hpo_link.exceptions import DataUnavailableError
from hpo_link.runtime_data_identity import verified_database_path


def build_probe(database: Path, requirement: ImmutableDataRequirement) -> dict[str, Any]:
    """Return the fixed controller probe after proving release and queryable SQLite data."""
    database = verified_database_path(database, requirement)
    try:
        connection = sqlite3.connect(f"file:{database}?mode=ro&immutable=1", uri=True)
        try:
            schema_version, declared_record_count = connection.execute(
                "SELECT schema_version, term_count FROM meta WHERE id = 1"
            ).fetchone()
            record_count = connection.execute("SELECT COUNT(*) FROM term").fetchone()[0]
            first_term = connection.execute(
                "SELECT hpo_id, name, is_obsolete FROM term ORDER BY hpo_id LIMIT 1"
            ).fetchone()
        finally:
            connection.close()
    except (sqlite3.Error, TypeError, ValueError) as exc:
        raise DataUnavailableError("The selected HPO data query probe failed.") from exc
    if (
        schema_version != requirement.schema_version
        or not isinstance(record_count, int)
        or record_count <= 0
        or record_count != declared_record_count
        or first_term is None
    ):
        raise DataUnavailableError("The selected HPO data query probe is inconsistent.")
    query_bytes = json.dumps(first_term, ensure_ascii=False, separators=(",", ":")).encode()
    return {
        "data_schema_version": str(schema_version),
        "record_count": record_count,
        "query_result_sha256": hashlib.sha256(query_bytes).hexdigest(),
    }


def main() -> int:
    """Print the exact controller probe JSON, or fail without exposing data paths."""
    settings = ServerSettings()
    database = settings.data.data_dir / settings.data.db_filename
    try:
        payload = build_probe(database, settings.immutable_data)
    except (DataUnavailableError, OSError, RuntimeError):
        sys.stderr.write("HPO runtime data probe failed\n")
        return 1
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
