"""Loader for the frozen SQLite DDL (``schema.sql``)."""

from __future__ import annotations

from pathlib import Path


def load_schema_sql() -> str:
    """Return the frozen ``schema.sql`` DDL as a string."""
    return (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
