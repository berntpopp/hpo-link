# hpo_link/identifiers.py
"""HPO / gene / disease identifier normalization and validation."""

from __future__ import annotations

import re

from hpo_link.exceptions import InvalidInputError

_HP_RE = re.compile(r"(?:HP[:_])?0*(\d{1,7})$", re.IGNORECASE)
_IRI_RE = re.compile(r"HP[_:](\d{7})$", re.IGNORECASE)


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

    Returns the normalized id (prefix uppercased) on success.
    """
    s = (raw or "").strip()
    if not s:
        raise InvalidInputError(
            "disease_id must be a non-empty CURIE (e.g. OMIM:106210).",
            field="disease_id",
        )
    if ":" not in s:
        raise InvalidInputError(
            f"disease_id {s!r} is not a valid CURIE — expected PREFIX:body (e.g. OMIM:106210).",
            field="disease_id",
        )
    prefix, body = s.split(":", 1)
    if not prefix:
        raise InvalidInputError(
            f"disease_id {s!r} has an empty prefix — expected PREFIX:body (e.g. OMIM:106210).",
            field="disease_id",
        )
    if not body:
        raise InvalidInputError(
            f"disease_id {s!r} has an empty body — expected PREFIX:body (e.g. OMIM:106210).",
            field="disease_id",
        )
    return f"{prefix.upper()}:{body}"


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
        )
    if ":" in s:
        prefix, body = s.split(":", 1)
        if prefix.lower() != "ncbigene":
            raise InvalidInputError(
                f"gene CURIE prefix {prefix!r} is not supported; use NCBIGene:NNNN, "
                "a bare symbol, or a bare numeric NCBI id.",
                field="gene",
            )
        if not body or not body.isdigit():
            raise InvalidInputError(
                f"NCBIGene CURIE body {body!r} must be all digits (e.g. NCBIGene:5080).",
                field="gene",
            )
        return ("ncbi", body)
    # bare symbol or bare numeric id
    return normalize_gene(s)
