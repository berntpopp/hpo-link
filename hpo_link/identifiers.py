# hpo_link/identifiers.py
"""HPO / gene / disease identifier normalization and validation."""

from __future__ import annotations

import re

from hpo_link.exceptions import InvalidInputError

_HP_RE = re.compile(r"(?:HP[:_])?0*(\d{1,7})$", re.IGNORECASE)
_IRI_RE = re.compile(r"HP[_:](\d{7})$", re.IGNORECASE)

# Recovery data surfaced on the invalid_input envelope (issue #28 D4: the disease_id/gene
# validators named the field but not what a valid value looks like, unlike the exemplary
# limit error). The classifier severs the message (it can interpolate the rejected value),
# so `allowed_values` + `hint` — both server-authored — carry the actionable guidance.
_DISEASE_ID_ALLOWED = [
    "OMIM:<mim> e.g. OMIM:106210",
    "ORPHA:<id> e.g. ORPHA:550",
    "DECIPHER:<id> e.g. DECIPHER:16",
]
_DISEASE_ID_FORMS = (
    "disease_id is an OMIM, Orphanet or DECIPHER CURIE, e.g. OMIM:106210 or ORPHA:550 "
    "(MIM: and Orphanet: spellings are accepted)."
)
_DISEASE_ID_HINT = (
    f"{_DISEASE_ID_FORMS} Convert a MONDO or other disease-ontology id with "
    "mondo_map_cross_ontology(term=<id>, prefixes=['OMIM', 'ORPHA']) first."
)
#: Namespaces Mondo cross-references (mondo_map_cross_ontology / resolve_xref in the fleet
#: baseline), i.e. the only foreign disease ids that tool converts to OMIM / ORPHA.
_MONDO_CONVERTIBLE = frozenset({"MONDO", "DOID", "UMLS", "MESH", "NCIT", "MEDGEN", "SCTID", "GARD"})
# Spellings of the namespaces HPOA annotates (normalisation, not mapping) -> stored prefix.
_DISEASE_PREFIXES = {
    "OMIM": "OMIM",
    "MIM": "OMIM",
    "ORPHA": "ORPHA",
    "ORPHANET": "ORPHA",
    "DECIPHER": "DECIPHER",
}
_GENE_ALLOWED = ["<symbol> e.g. PAX6", "NCBIGene:<id> e.g. NCBIGene:5080", "<numeric id> e.g. 5080"]
#: hpo-link has no Ensembl/HGNC/RefSeq mapping (HPO ships symbol + NCBI id only), issue #128.
TRANSLATE_GENE_HINT = (
    "Ensembl gene (ENSG), RefSeq and HGNC ids are not mapped here: translate them to gene "
    "symbols first with hgnc_resolve_symbol (one id) or hgnc_resolve_symbols_batch (a list)."
)
_GENE_FORMS = (
    "gene is a symbol (PAX6), an NCBIGene CURIE (NCBIGene:5080), or a bare numeric NCBI id (5080)."
)
_GENE_HINT = f"{_GENE_FORMS} {TRANSLATE_GENE_HINT}"
_TRANSCRIPT_RE = re.compile(r"ENS[A-Z]*T\d", re.IGNORECASE)


def _foreign_gene_hint(s: str) -> str:
    """Name the HGNC converter only for the forms it really converts (never a transcript id)."""
    if hgnc_resolvable(s):
        return _GENE_HINT
    if _TRANSCRIPT_RE.match(s):
        return f"This is an Ensembl transcript id, not a gene id. {_GENE_FORMS}"
    return f"This identifier form is not mapped here. {_GENE_FORMS}"


# Ensembl (any species, optional version), RefSeq and LRG accessions: never a gene symbol.
_FOREIGN_GENE_RE = re.compile(
    r"(ENS[A-Z]*[GTP]\d{6,}|[NX][CGMPR]_\d+|LRG_\d+)(\.\d+)?$", re.IGNORECASE
)


def is_foreign_gene_id(raw: str) -> bool:
    """True for an id of a namespace hpo-link cannot map (ENSG…, NM_…, HGNC:…, any CURIE)."""
    s = (raw or "").strip()
    if ":" in s:
        return not s.lower().startswith("ncbigene:")
    return bool(_FOREIGN_GENE_RE.match(s))


# Forms hgnc_resolve_symbol / hgnc_resolve_symbols_batch convert (hgnc-link >= 2.5.0).
_HGNC_RESOLVABLE_RE = re.compile(r"(HGNC:\d+|ENSG\d{11}|N[MRP]_\d+)(\.\d+)?$", re.IGNORECASE)


def hgnc_resolvable(raw: object) -> bool:
    """True for a foreign gene id the fleet's HGNC resolver converts (safe to reflect)."""
    return isinstance(raw, str) and bool(_HGNC_RESOLVABLE_RE.match(raw.strip()))


def mondo_convertible(raw: object) -> bool:
    """True for a disease id in a namespace Mondo maps to OMIM / ORPHA (MONDO, DOID, ...)."""
    return isinstance(raw, str) and raw.strip().split(":", 1)[0].upper() in _MONDO_CONVERTIBLE


def normalize_hpo_id(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.strip()
    m = _IRI_RE.search(s) or _HP_RE.match(s)
    if not m:
        return None
    return f"HP:{int(m.group(1)):07d}"


def iri_to_curie(iri: str) -> str:
    return normalize_hpo_id(iri) or iri


def is_hpo_id(s: str | None) -> bool:
    return bool(s and re.match(r"^HP:\d{7}$", s.strip(), re.IGNORECASE))


def normalize_gene(raw: str) -> tuple[str, str]:
    s = (raw or "").strip()
    low = s.lower()
    if low.startswith("ncbigene:"):
        return ("ncbi", s.split(":", 1)[1])
    if s.isdigit():
        return ("ncbi", s)
    return ("symbol", s.upper())


def normalize_disease_id(raw: str) -> str:
    s = (raw or "").strip()
    if ":" in s:
        prefix, rest = s.split(":", 1)
        return f"{prefix.upper()}:{rest}"
    return s


def validate_disease_id(raw: str) -> str:
    """Validate and normalize a disease id CURIE.

    Requires a non-empty prefix, a colon separator, and a non-empty body.
    Raises :class:`~hpo_link.exceptions.InvalidInputError` with
    ``field="disease_id"`` when the shape is invalid.

    Returns the normalized id (stored prefix: OMIM / ORPHA / DECIPHER) on success.
    """
    s = (raw or "").strip()
    if not s:
        raise InvalidInputError(
            "disease_id must be a non-empty CURIE (e.g. OMIM:106210).",
            field="disease_id",
            allowed=_DISEASE_ID_ALLOWED,
            hint=_DISEASE_ID_HINT,
        )
    if ":" not in s:
        raise InvalidInputError(
            f"disease_id {s!r} is not a valid CURIE — expected PREFIX:body (e.g. OMIM:106210).",
            field="disease_id",
            allowed=_DISEASE_ID_ALLOWED,
            hint=_DISEASE_ID_HINT,
        )
    prefix, body = s.split(":", 1)
    if not prefix:
        raise InvalidInputError(
            f"disease_id {s!r} has an empty prefix — expected PREFIX:body (e.g. OMIM:106210).",
            field="disease_id",
            allowed=_DISEASE_ID_ALLOWED,
            hint=_DISEASE_ID_HINT,
        )
    if not body:
        raise InvalidInputError(
            f"disease_id {s!r} has an empty body — expected PREFIX:body (e.g. OMIM:106210).",
            field="disease_id",
            allowed=_DISEASE_ID_ALLOWED,
            hint=_DISEASE_ID_HINT,
        )
    canonical = _DISEASE_PREFIXES.get(prefix.upper())
    if canonical is None:  # MONDO/DOID/...: would otherwise match nothing (empty success)
        raise InvalidInputError(
            f"disease_id prefix {prefix!r} is not a namespace HPO annotates.",
            field="disease_id",
            allowed=_DISEASE_ID_ALLOWED,
            # name the converter only for ids it converts (not e.g. a gene id sent here)
            hint=_DISEASE_ID_HINT if mondo_convertible(s) else _DISEASE_ID_FORMS,
        )
    return f"{canonical}:{body}"


def validate_gene(raw: str) -> tuple[str, str]:
    """Validate and normalize a gene identifier.

    Accepts bare symbol (``PAX6``), bare numeric NCBI id (``5080``), or an
    ``NCBIGene:NNNN`` CURIE (case-insensitive prefix). Raises
    :class:`~hpo_link.exceptions.InvalidInputError` with ``field="gene"``
    when the shape is invalid.

    Returns ``(kind, value)`` where ``kind`` is ``"symbol"`` or ``"ncbi"``.
    """
    s = (raw or "").strip()
    if not s:
        raise InvalidInputError(
            "gene must be a non-empty gene symbol or NCBI id (e.g. PAX6 or NCBIGene:5080).",
            field="gene",
            allowed=_GENE_ALLOWED,
            hint=_GENE_HINT,
        )
    if ":" in s:
        prefix, body = s.split(":", 1)
        if prefix.lower() != "ncbigene":
            raise InvalidInputError(
                f"gene CURIE prefix {prefix!r} is not supported; use NCBIGene:NNNN, "
                "a bare symbol, or a bare numeric NCBI id.",
                field="gene",
                allowed=_GENE_ALLOWED,
                hint=_foreign_gene_hint(s),
            )
        if not body or not body.isdigit():
            raise InvalidInputError(
                f"NCBIGene CURIE body {body!r} must be all digits (e.g. NCBIGene:5080).",
                field="gene",
                allowed=_GENE_ALLOWED,
                hint=_GENE_HINT,
            )
        return ("ncbi", body)
    if is_foreign_gene_id(s):  # would otherwise look like an unannotated symbol (empty success)
        raise InvalidInputError(
            f"gene {s!r} is an Ensembl/RefSeq accession, which hpo-link cannot map.",
            field="gene",
            allowed=_GENE_ALLOWED,
            hint=_foreign_gene_hint(s),
        )
    # bare symbol or bare numeric id
    return normalize_gene(s)
