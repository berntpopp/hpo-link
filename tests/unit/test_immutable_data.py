"""Regression tests for the exact immutable HPO reference-data materializer."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import yaml
import zstandard
from pydantic import ValidationError

from hpo_link.config import ImmutableDataRequirement, ServerSettings
from hpo_link.data.repository import HpoRepository
from hpo_link.exceptions import DataUnavailableError
from hpo_link.immutable_data import materialize_immutable_data


def test_default_requirement_matches_the_reviewed_published_hpo_bundle() -> None:
    """The production default binds the exact bundle that the init sidecar fetches."""
    requirement = ServerSettings().immutable_data

    assert requirement.release_tag == "db-v2026-09-01"
    assert requirement.compressed_sha256 == (
        "be9e693abf9eabb06ad501e360084cc3fb039eef90ffe02912bfe83256af3999"
    )
    assert requirement.expanded_tree_sha256 == (
        "e2d0f59dcc4cc3438d57e73e9cdd472582b0517301dc5eae167d2ad61b4387b1"
    )


def test_runtime_and_container_release_bind_the_same_september_data_identity() -> None:
    requirement = ServerSettings().immutable_data
    release = json.loads((Path(__file__).parents[2] / "container-release.json").read_text())
    assert release["data_identity_contract"] == "runtime-v1"
    assert release["data"]["release_tag"] == requirement.release_tag
    assert release["data"]["digest"] == f"sha256:{requirement.compressed_sha256}"
    assert release["data"]["schema_compatibility"] == ["1"]


def _compose(path: str) -> dict[str, Any]:
    class ComposeLoader(yaml.SafeLoader):
        pass

    ComposeLoader.add_multi_constructor(
        "!", lambda loader, _tag, node: loader.construct_object(node)
    )
    return yaml.load(
        (Path(__file__).parents[2] / path).read_text(encoding="utf-8"),
        Loader=ComposeLoader,  # noqa: S506 - subclass is SafeLoader.
    )


def test_init_service_pins_match_data_manifest_in_base_and_npm_compose() -> None:
    release = json.loads((Path(__file__).parents[2] / "container-release.json").read_text())
    for path in ("docker/docker-compose.yml", "docker/docker-compose.npm.yml"):
        init = _compose(path)["services"]["hpo-data-init"]
        environment = init["environment"]
        assert environment["HPO_LINK_IMMUTABLE_DATA__RELEASE_TAG"] == release["data"]["release_tag"]
        assert environment["HPO_LINK_IMMUTABLE_DATA__COMPRESSED_SHA256"] == (
            release["data"]["digest"].removeprefix("sha256:")
        )
        assert environment["HPO_LINK_IMMUTABLE_DATA__EXPANDED_TREE_SHA256"] == (
            ServerSettings().immutable_data.expanded_tree_sha256
        )
        assert environment["HPO_LINK_IMMUTABLE_DATA__SCHEMA_VERSION"] == "1"
        assert environment["HPO_LINK_IMMUTABLE_DATA__HPO_VERSION"] == "2026-09-01"
        assert environment["HPO_LINK_IMMUTABLE_DATA__HPOA_VERSION"] == "2026-09-02"


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
        "release_tag": requirement.release_tag,
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


@respx.mock
def test_materialize_upgrades_legacy_identity_only_after_exact_bundle_verification(
    tmp_path: Path,
) -> None:
    requirement, bundle = _requirement_and_bundle(tmp_path)
    root = requirement.reference_root
    target = root / requirement.compressed_sha256
    target.mkdir(parents=True)
    database = target / "hpo.sqlite"
    decompressor = zstandard.ZstdDecompressor()
    database.write_bytes(decompressor.decompress(bundle))
    database.chmod(0o444)
    identity = {
        "compressed_sha256": requirement.compressed_sha256,
        "expanded_tree_sha256": requirement.expanded_tree_sha256,
        "schema_version": requirement.schema_version,
        "hpo_version": requirement.hpo_version,
        "hpoa_version": requirement.hpoa_version,
    }
    (target / "identity.json").write_text(json.dumps(identity), encoding="utf-8")
    (root / "current").symlink_to(target.name)
    previous_bytes = database.read_bytes()
    respx.get(str(requirement.bundle_url)).mock(return_value=httpx.Response(200, content=bundle))

    selected = materialize_immutable_data(requirement)

    assert selected == database
    assert database.read_bytes() == previous_bytes
    assert json.loads((target / "identity.json").read_text()) == {
        "release_tag": requirement.release_tag,
        **identity,
    }
    assert (root / "current").resolve() == target
