from __future__ import annotations

import re

_MONDO_ID_RE = re.compile(r"^MONDO:(\d{7})$", re.IGNORECASE)
_BARE_ID_RE = re.compile(r"^\d{7}$")
_XREF_PREFIX_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*):(.+)$")
_KNOWN_PREFIX_ALIASES = {
    "ORPHANET": "ORPHA",
    "ORPHA": "ORPHA",
    "OMIM": "OMIM",
    "MIM": "OMIM",
    "DOID": "DOID",
    "NCIT": "NCIT",
    "UMLS": "UMLS",
    "MESH": "MESH",
    "MSH": "MESH",
    "MEDGEN": "MEDGEN",
    "SCTID": "SCTID",
    "SNOMEDCT": "SCTID",
    "GARD": "GARD",
    "ICD10CM": "ICD10CM",
    "ICD10": "ICD10",
    "EFO": "EFO",
}


def normalize_mondo_id(value: str) -> str | None:
    text = (value or "").strip()
    m = _MONDO_ID_RE.match(text)
    if m:
        return f"MONDO:{m.group(1)}"
    if _BARE_ID_RE.match(text):
        return f"MONDO:{text}"
    return None


def looks_like_mondo_id(value: str) -> bool:
    return normalize_mondo_id(value) is not None


def normalize_xref(value: str) -> str | None:
    text = (value or "").strip()
    m = _XREF_PREFIX_RE.match(text)
    if not m:
        return None
    prefix, local = m.group(1).upper(), m.group(2).strip()
    prefix = _KNOWN_PREFIX_ALIASES.get(prefix, prefix)
    if not local:
        return None
    return f"{prefix}:{local}"


def xref_prefix(value: str) -> str | None:
    norm = normalize_xref(value)
    return norm.split(":", 1)[0] if norm else None


def infer_xref_source(value: str) -> str | None:
    if looks_like_mondo_id(value):
        return None
    return xref_prefix(value)
