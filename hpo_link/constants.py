# hpo_link/constants.py
"""Project-wide constants for hpo-link."""

from __future__ import annotations

SCHEMA_VERSION = 1
HPO_ROOT = "HP:0000001"
PHENOTYPIC_ABNORMALITY = "HP:0000118"

#: Published latency SLO for local in-process queries (Speed observability target).
#: Surfaced in get_server_capabilities + get_diagnostics; guarded by a CI benchmark
#: (tests/unit/test_latency_slo.py). Local SQLite lookups are sub-millisecond today;
#: the SLO makes the guarantee explicit and regression-gated against DB growth.
LATENCY_SLO_P99_MS = 5

#: Data-freshness threshold: a built index older than this many days is flagged
#: ``stale`` by get_diagnostics so an operator sees a stale index without external
#: tooling. HPO ships roughly monthly; ~3 releases of slack before flagging.
STALE_AFTER_DAYS = 90

GITHUB_OWNER_REPO = "obophenotype/human-phenotype-ontology"
GITHUB_RELEASES_LATEST_URL = f"https://api.github.com/repos/{GITHUB_OWNER_REPO}/releases/latest"

GITHUB_DB_OWNER_REPO = "berntpopp/hpo-link"


def obo_purl(date: str, filename: str) -> str:
    """Version-pinned OBO PURL, e.g. obo_purl('2026-06-06','hp.json')."""
    return f"http://purl.obolibrary.org/obo/hp/releases/{date}/{filename}"


ONTOLOGY_FILES = ("hp.json", "hp-base.json")
HPOA_FILES = (
    "phenotype.hpoa",
    "genes_to_phenotype.txt",
    "phenotype_to_genes.txt",
    "genes_to_disease.txt",
)

# xref namespaces HPO terms carry (UMLS/SNOMED dominant)
XREF_PREFIXES = (
    "UMLS",
    "SNOMEDCT_US",
    "NCIT",
    "MEDDRA",
    "ICD-10",
    "ICD-9",
    "ORPHA",
    "MONDO",
    "DOID",
    "EFO",
    "MP",
    "MSH",
    "MESH",
)

RECOMMENDED_CITATION = (
    "Köhler S, Gargano M, Matentzoglu N, et al. The Human Phenotype Ontology in 2024: "
    "phenotypes around the world. Nucleic Acids Res. 2024;52(D1):D1333-D1346. "
    "Human Phenotype Ontology, https://hpo.jax.org/."
)
HPO_LICENSE_URL = "https://hpo.jax.org/app/license"
HPO_LICENSE = (
    "The Human Phenotype Ontology is distributed under the custom HPO license "
    f"({HPO_LICENSE_URL}). Acknowledge the HPO Consortium, display the release version, "
    "and do not alter term relationships."
)
