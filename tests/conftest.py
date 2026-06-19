"""Shared pytest fixtures for hpo-link. Extended by data/service tasks."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from hpo_link.data.repository import HpoRepository
    from hpo_link.services.annotation_service import AnnotationService
    from hpo_link.services.hpo_service import HpoService

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def mini_paths() -> dict[str, Path | None]:
    """Return paths dict pointing at the mini_* test fixtures."""
    return {
        "ontology": FIXTURES_DIR / "mini_hp.json",
        "phenotype_hpoa": FIXTURES_DIR / "mini_phenotype.hpoa",
        "genes_to_phenotype": FIXTURES_DIR / "mini_genes_to_phenotype.txt",
        "genes_to_disease": FIXTURES_DIR / "mini_genes_to_disease.txt",
    }


@pytest.fixture(scope="session")
def built_test_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a test SQLite database from mini fixtures; session-scoped for speed."""
    from hpo_link.config import HPODataConfig, ServerSettings
    from hpo_link.ingest.builder import build_database

    data_dir = tmp_path_factory.mktemp("hpo_data")
    # Copy fixtures into a data dir so the builder can use them
    for fixture in FIXTURES_DIR.glob("mini_*"):
        shutil.copy(fixture, data_dir / fixture.name)

    paths: dict[str, Path | None] = {
        "ontology": data_dir / "mini_hp.json",
        "phenotype_hpoa": data_dir / "mini_phenotype.hpoa",
        "genes_to_phenotype": data_dir / "mini_genes_to_phenotype.txt",
        "genes_to_disease": data_dir / "mini_genes_to_disease.txt",
    }
    data_cfg = HPODataConfig(data_dir=data_dir)
    config = ServerSettings.model_construct(data=data_cfg)
    build_database(config, paths=paths, validators={})
    return data_dir / "hpo.sqlite"


@pytest.fixture(scope="session")
def repo(built_test_db: Path) -> HpoRepository:  # type: ignore[return]
    """Open a read-only HpoRepository over the fixture DB."""
    from hpo_link.data.repository import HpoRepository

    r = HpoRepository(built_test_db)
    yield r  # type: ignore[misc]
    r.close()


@pytest.fixture(scope="session")
def hpo_service(repo: HpoRepository) -> HpoService:
    """Return an HpoService bound to the fixture repository."""
    from hpo_link.services.hpo_service import HpoService

    return HpoService(repo)


@pytest.fixture(scope="session")
def annotation_service(repo: HpoRepository) -> AnnotationService:
    """Return an AnnotationService bound to the fixture repository."""
    from hpo_link.services.annotation_service import AnnotationService

    return AnnotationService(repo)
