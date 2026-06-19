# hpo_link/identifiers.py
"""HPO / gene / disease identifier normalization."""

from __future__ import annotations

import re

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
