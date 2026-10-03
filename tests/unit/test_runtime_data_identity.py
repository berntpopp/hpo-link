"""Runtime-v1 identity must prove the exact data release served by HPO Link."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from hpo_link.app import create_app
from hpo_link.config import ImmutableDataRequirement, ServerSettings
from hpo_link.exceptions import DataUnavailableError
from hpo_link.immutable_data import canonical_tree_sha256
from hpo_link.runtime_data_identity import verify_runtime_identity


def _fixture(
    tmp_path: Path, *, include_release_tag: bool = True, term_count: int = 1
) -> tuple[Path, ImmutableDataRequirement]:
    compressed_sha256 = hashlib.sha256(b"fixture-bundle").hexdigest()
    root = tmp_path / compressed_sha256
    root.mkdir()
    database = root / "hpo.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE meta (id INTEGER PRIMARY KEY, schema_version INTEGER, "
            "hpo_version TEXT, hpoa_version TEXT, term_count INTEGER)"
        )
        connection.execute(
            "INSERT INTO meta VALUES (1, 1, '2026-09-01', '2026-09-02', ?)",
            (term_count,),
        )
        connection.execute(
            "CREATE TABLE term (hpo_id TEXT PRIMARY KEY, name TEXT, is_obsolete INTEGER)"
        )
        connection.execute("INSERT INTO term VALUES ('HP:0000001', 'All', 0)")
    requirement = ImmutableDataRequirement(
        reference_root=tmp_path,
        release_tag="db-v2026-09-01",
        bundle_url=(
            "https://github.com/berntpopp/hpo-link/releases/download/db-v2026-09-01/"
            "hpo-2026-09-01.sqlite.zst"
        ),
        compressed_sha256=compressed_sha256,
        expanded_tree_sha256=canonical_tree_sha256(database),
        schema_version=1,
        hpo_version="2026-09-01",
        hpoa_version="2026-09-02",
        max_compressed_bytes=1024,
        max_expanded_bytes=1024 * 1024,
    )
    identity = {
        "compressed_sha256": compressed_sha256,
        "expanded_tree_sha256": requirement.expanded_tree_sha256,
        "schema_version": 1,
        "hpo_version": "2026-09-01",
        "hpoa_version": "2026-09-02",
    }
    if include_release_tag:
        identity["release_tag"] = requirement.release_tag
    (root / "identity.json").write_text(json.dumps(identity), encoding="utf-8")
    return root, requirement


def test_runtime_identity_returns_only_the_configured_and_verified_release(
    tmp_path: Path,
) -> None:
    root, requirement = _fixture(tmp_path)

    identity = verify_runtime_identity(root / "hpo.sqlite", requirement)

    assert identity == {
        "release_tag": "db-v2026-09-01",
        "digest": f"sha256:{requirement.compressed_sha256}",
    }


def test_runtime_identity_rejects_a_pre_runtime_v1_materialization(tmp_path: Path) -> None:
    root, requirement = _fixture(tmp_path, include_release_tag=False)

    with pytest.raises(DataUnavailableError):
        verify_runtime_identity(root / "hpo.sqlite", requirement)


def test_runtime_identity_rejects_an_alternate_database_filename(tmp_path: Path) -> None:
    root, requirement = _fixture(tmp_path)
    alternate = root / "alternate.sqlite"
    shutil.copyfile(root / "hpo.sqlite", alternate)

    with pytest.raises(DataUnavailableError):
        verify_runtime_identity(alternate, requirement)


def test_runtime_identity_rejects_a_database_file_symlink(tmp_path: Path) -> None:
    root, requirement = _fixture(tmp_path)
    alias = root / "hpo-alias.sqlite"
    alias.symlink_to(root / "hpo.sqlite")

    with pytest.raises(DataUnavailableError):
        verify_runtime_identity(alias, requirement)


def test_health_publishes_runtime_v1_only_after_identity_verifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requirement = ServerSettings().immutable_data
    expected = {
        "release_tag": requirement.release_tag,
        "digest": f"sha256:{requirement.compressed_sha256}",
    }
    monkeypatch.setattr(
        "hpo_link.app.verify_runtime_identity",
        lambda root, requirement: expected,
    )

    body = TestClient(create_app()).get("/health").json()

    assert body["data_available"] is True
    assert body["release_identity"] == {
        "schema_version": 1,
        "data_identity": {"expected": expected, "actual": expected},
    }


def test_health_fails_closed_without_a_verified_runtime_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_verification(root: object, requirement: object) -> dict[str, str]:
        raise DataUnavailableError("identity mismatch")

    monkeypatch.setattr("hpo_link.app.verify_runtime_identity", fail_verification)

    body = TestClient(create_app()).get("/health").json()

    assert body["data_available"] is False
    assert "release_identity" not in body


def test_health_does_not_claim_the_pinned_identity_for_an_alternate_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, requirement = _fixture(tmp_path)
    shutil.copyfile(root / "hpo.sqlite", root / "alternate.sqlite")
    monkeypatch.setattr(
        "hpo_link.app.settings",
        SimpleNamespace(
            data=SimpleNamespace(data_dir=root, db_filename="alternate.sqlite"),
            immutable_data=requirement,
            cors_origins=[],
        ),
    )

    body = TestClient(create_app()).get("/health").json()

    assert body["data_available"] is False
    assert "release_identity" not in body


def test_controller_probe_returns_fixed_schema_and_semantic_query_digest(
    tmp_path: Path,
) -> None:
    from hpo_link.data_probe import build_probe

    root, requirement = _fixture(tmp_path)

    result = build_probe(root / "hpo.sqlite", requirement)

    assert set(result) == {"data_schema_version", "record_count", "query_result_sha256"}
    assert result["data_schema_version"] == "1"
    assert result["record_count"] == 1
    assert result["query_result_sha256"] == hashlib.sha256(b'["HP:0000001","All",0]').hexdigest()


def test_controller_probe_rejects_a_metadata_count_that_differs_from_actual_rows(
    tmp_path: Path,
) -> None:
    from hpo_link.data_probe import build_probe

    root, requirement = _fixture(tmp_path, term_count=2)

    with pytest.raises(DataUnavailableError):
        build_probe(root / "hpo.sqlite", requirement)
