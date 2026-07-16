"""Regression tests for the exact immutable HPO reference-data materializer."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
import respx
import zstandard
from pydantic import ValidationError

from hpo_link.config import ImmutableDataRequirement, ServerSettings
from hpo_link.data.repository import HpoRepository
from hpo_link.exceptions import DataUnavailableError
from hpo_link.immutable_data import materialize_immutable_data


def test_default_requirement_matches_the_reviewed_published_hpo_bundle() -> None:
    """The production default binds the exact bundle that the init sidecar fetches."""
    requirement = ServerSettings().immutable_data

    assert requirement.release_tag == "db-v2026-06-23"
    assert requirement.compressed_sha256 == (
        "d677a96efd8c274045241934c33b25dfb6fc9a6414c27bed7ae3334d05d4c9f6"
    )
    assert requirement.expanded_tree_sha256 == (
        "f98176204ac9b70d4451efab7fcafa4756e1aac2f14b64a5f2c5ec0d574ebee3"
    )


def _tree_sha256(path: Path) -> str:
    file_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    record = f"hpo.sqlite\0{0o444:o}\0{path.stat().st_size}\0{file_sha256}"
    return hashlib.sha256(record.encode()).hexdigest()


def _requirement_and_bundle(
    tmp_path: Path, *, version: str = "2026-06-23"
) -> tuple[ImmutableDataRequirement, bytes]:
    source = tmp_path / f"hpo-{version}.sqlite"
    connection = sqlite3.connect(source)
    try:
        connection.execute(
            "CREATE TABLE meta (id INTEGER PRIMARY KEY, schema_version INTEGER, "
            "hpo_version TEXT, hpoa_version TEXT)"
        )
        connection.execute(
            "INSERT INTO meta VALUES (1, 1, ?, ?)",
            (version, version),
        )
        connection.commit()
    finally:
        connection.close()
    bundle = zstandard.ZstdCompressor().compress(source.read_bytes())
    return (
        ImmutableDataRequirement(
            reference_root=tmp_path / "reference",
            release_tag=f"db-v{version}",
            bundle_url=(
                "https://github.com/berntpopp/hpo-link/releases/download/"
                f"db-v{version}/hpo-{version}.sqlite.zst"
            ),
            compressed_sha256=hashlib.sha256(bundle).hexdigest(),
            expanded_tree_sha256=_tree_sha256(source),
            schema_version=1,
            hpo_version=version,
            hpoa_version=version,
            max_compressed_bytes=len(bundle) + 1,
            max_expanded_bytes=source.stat().st_size + 1,
        ),
        bundle,
    )


@respx.mock
def test_materialize_verifies_and_selects_atomically(tmp_path: Path) -> None:
    """A checked digest selects a read-only snapshot through ``current``."""
    requirement, bundle = _requirement_and_bundle(tmp_path)
    respx.get(str(requirement.bundle_url)).mock(return_value=httpx.Response(200, content=bundle))

    selected = materialize_immutable_data(requirement)

    assert selected == tmp_path / "reference" / requirement.compressed_sha256 / "hpo.sqlite"
    assert (tmp_path / "reference" / "current").resolve() == selected.parent
    assert selected.stat().st_mode & 0o777 == 0o444
    assert json.loads(selected.with_name("identity.json").read_text()) == {
        "compressed_sha256": requirement.compressed_sha256,
        "expanded_tree_sha256": requirement.expanded_tree_sha256,
        "schema_version": 1,
        "hpo_version": "2026-06-23",
        "hpoa_version": "2026-06-23",
    }


@pytest.mark.parametrize("field,value", [("release_tag", "latest"), ("compressed_sha256", "bad")])
def test_requirement_rejects_mutable_or_incomplete_pins(
    tmp_path: Path, field: str, value: str
) -> None:
    """Production requirements must name an immutable release and full digest."""
    requirement, _ = _requirement_and_bundle(tmp_path)
    values = requirement.model_dump()
    values[field] = value

    with pytest.raises(ValidationError):
        ImmutableDataRequirement(**values)


@respx.mock
def test_tree_mismatch_preserves_existing_current(tmp_path: Path) -> None:
    """A failed replacement never makes a partial or unverified bundle current."""
    old_requirement, old_bundle = _requirement_and_bundle(tmp_path, version="2026-06-22")
    respx.get(str(old_requirement.bundle_url)).mock(
        return_value=httpx.Response(200, content=old_bundle)
    )
    old_selected = materialize_immutable_data(old_requirement)

    requirement, bundle = _requirement_and_bundle(tmp_path, version="2026-06-23")
    invalid = requirement.model_copy(update={"expanded_tree_sha256": "0" * 64})
    respx.get(str(invalid.bundle_url)).mock(return_value=httpx.Response(200, content=bundle))

    with pytest.raises(DataUnavailableError, match="expanded-tree"):
        materialize_immutable_data(invalid)

    assert (tmp_path / "reference" / "current").resolve() == old_selected.parent
    assert not list((tmp_path / "reference").glob(".*.staging-*"))


def test_repository_opens_the_selected_snapshot_immutably(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reader requires SQLite immutable mode after the init sidecar selects data."""
    database = tmp_path / "hpo.sqlite"
    sqlite3.connect(database).close()
    called: dict[str, object] = {}
    original_connect = sqlite3.connect

    def spy_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        called["uri"] = args[0]
        return original_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", spy_connect)
    repository = HpoRepository(database)
    repository.close()

    assert called["uri"] == f"file:{database}?mode=ro&immutable=1"
