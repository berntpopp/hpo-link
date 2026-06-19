"""Parse HPOA TSV files: phenotype.hpoa and the 3 gene/phenotype TSVs.

Implements the HPOA parsing contract from the design spec §4.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from io import StringIO

csv.field_size_limit(1 << 24)

_HP_FREQ_RE = re.compile(r"^HP:\d{7}$")
_RATIO_RE = re.compile(r"^(\d+)/(\d+)$")
_PERCENT_RE = re.compile(r"^(\d+(?:\.\d+)?)%$")


def parse_frequency(raw: str | None) -> tuple[str | None, str | None, float | None]:
    """Parse a raw frequency string into (frequency_hpo, frequency_ratio, frequency_percent).

    Handles:
    - HPO frequency term (HP:XXXXXXX) -> (hpo_term, None, None)
    - Ratio n/m -> (None, "n/m", 100*n/m)
    - Percentage NN% -> (None, None, float)
    - Dash / empty -> (None, None, None)
    """
    if not raw or raw.strip() in ("-", ""):
        return (None, None, None)
    s = raw.strip()
    if _HP_FREQ_RE.match(s):
        return (s, None, None)
    m_ratio = _RATIO_RE.match(s)
    if m_ratio:
        numerator = float(m_ratio.group(1))
        denominator = float(m_ratio.group(2))
        if not denominator:
            # n/0 is a malformed ratio: drop it rather than emit an unrankable row.
            return (None, None, None)
        pct = round(100.0 * numerator / denominator, 10)
        return (None, s, pct)
    m_pct = _PERCENT_RE.match(s)
    if m_pct:
        return (None, None, float(m_pct.group(1)))
    return (None, None, None)


@dataclass
class DiseasePhenotypeRow:
    database_id: str
    disease_name: str
    qualifier: str
    hpo_id: str
    reference: str
    evidence: str
    onset: str
    frequency: str
    frequency_hpo: str | None
    frequency_ratio: str | None
    frequency_percent: float | None
    sex: str
    modifier: str
    aspect: str
    biocuration: str


@dataclass
class GenePhenotypeRow:
    ncbi_gene_id: str
    gene_symbol: str
    hpo_id: str
    hpo_name: str
    frequency: str
    disease_id: str


@dataclass
class GeneDiseaseRow:
    ncbi_gene_id: str
    gene_symbol: str
    association_type: str
    disease_id: str
    source: str


def parse_phenotype_hpoa(text: str) -> tuple[str, list[DiseasePhenotypeRow]]:
    """Parse phenotype.hpoa text; returns (version, [DiseasePhenotypeRow])."""
    version = ""
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("#version:") or line.startswith("#version: "):
            # Extract date after ":" and strip whitespace
            version = line.split(":", 1)[1].strip()
        if line.startswith("#"):
            continue
        data_lines.append(line)

    if not data_lines:
        return version, []

    reader = csv.DictReader(StringIO("\n".join(data_lines)), delimiter="\t")
    rows: list[DiseasePhenotypeRow] = []
    for row in reader:
        raw_freq = (row.get("frequency") or "").strip()
        fhpo, fratio, fpct = parse_frequency(raw_freq)
        rows.append(
            DiseasePhenotypeRow(
                database_id=(row.get("database_id") or "").strip(),
                disease_name=(row.get("disease_name") or "").strip(),
                qualifier=(row.get("qualifier") or "").strip(),
                hpo_id=(row.get("hpo_id") or "").strip(),
                reference=(row.get("reference") or "").strip(),
                evidence=(row.get("evidence") or "").strip(),
                onset=(row.get("onset") or "").strip(),
                frequency=raw_freq,
                frequency_hpo=fhpo,
                frequency_ratio=fratio,
                frequency_percent=fpct,
                sex=(row.get("sex") or "").strip(),
                modifier=(row.get("modifier") or "").strip(),
                aspect=(row.get("aspect") or "").strip(),
                biocuration=(row.get("biocuration") or "").strip(),
            )
        )
    return version, rows


def parse_genes_to_phenotype(text: str) -> list[GenePhenotypeRow]:
    """Parse genes_to_phenotype.txt; returns [GenePhenotypeRow]."""
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    if not lines:
        return []
    reader = csv.DictReader(StringIO("\n".join(lines)), delimiter="\t")
    rows: list[GenePhenotypeRow] = []
    for row in reader:
        rows.append(
            GenePhenotypeRow(
                ncbi_gene_id=(row.get("ncbi_gene_id") or "").strip(),
                gene_symbol=(row.get("gene_symbol") or "").strip(),
                hpo_id=(row.get("hpo_id") or "").strip(),
                hpo_name=(row.get("hpo_name") or "").strip(),
                frequency=(row.get("frequency") or "").strip(),
                disease_id=(row.get("disease_id") or "").strip(),
            )
        )
    return rows


def parse_genes_to_disease(text: str) -> list[GeneDiseaseRow]:
    """Parse genes_to_disease.txt; returns [GeneDiseaseRow]."""
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    if not lines:
        return []
    reader = csv.DictReader(StringIO("\n".join(lines)), delimiter="\t")
    rows: list[GeneDiseaseRow] = []
    for row in reader:
        rows.append(
            GeneDiseaseRow(
                ncbi_gene_id=(row.get("ncbi_gene_id") or "").strip(),
                gene_symbol=(row.get("gene_symbol") or "").strip(),
                association_type=(row.get("association_type") or "").strip(),
                disease_id=(row.get("disease_id") or "").strip(),
                source=(row.get("source") or "").strip(),
            )
        )
    return rows
