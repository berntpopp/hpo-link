"""Shared annotated argument types for the HPO MCP tools."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

ResponseMode = Annotated[
    Literal["minimal", "compact", "standard", "full"],
    Field(description="Verbosity: minimal|compact|standard|full (default compact)."),
]

QueryStr = Annotated[
    str,
    Field(
        description=(
            "A phenotype label, synonym, HP id (HP:0000118), or external xref CURIE "
            "(UMLS:C0036572, SNOMEDCT_US:193046000, ...)."
        ),
        examples=["Phenotypic abnormality", "HP:0000118", "Seizure"],
    ),
]

TermStr = Annotated[
    str,
    Field(
        description=(
            "An HP id (HP:0000118), a phenotype label/synonym, or an external xref CURIE "
            "that resolves to a single HPO term."
        ),
        examples=["HP:0000118", "Seizure", "UMLS:C0036572"],
    ),
]

XrefIdStr = Annotated[
    str,
    Field(
        description=(
            "An external cross-reference CURIE (prefix:local), e.g. UMLS/SNOMED/NCIT/MEDDRA, "
            "to resolve back to the HPO term(s) that cross-reference it."
        ),
        examples=["UMLS:C0036572", "SNOMEDCT_US:193046000", "NCIT:C4890"],
    ),
]

FieldsArg = Annotated[
    list[str] | None,
    Field(
        description=(
            "Sparse fieldset: return ONLY these top-level keys (dot into a grouped "
            "object, e.g. 'xrefs.UMLS'). Identity anchors (hpo_id, name, hpo_version) are "
            "always included. Omit for the full payload."
        ),
        examples=[["synonyms", "definition"], ["parents"]],
    ),
]

GeneStr = Annotated[
    str,
    Field(
        description=(
            "A gene symbol (e.g. 'PAX6') or NCBI gene CURIE (e.g. 'NCBIGene:5080'). "
            "Bare NCBI numeric ids (e.g. '5080') are also accepted."
        ),
        examples=["PAX6", "NCBIGene:5080", "5080"],
    ),
]

DiseaseIdStr = Annotated[
    str,
    Field(
        description=(
            "A disease CURIE, e.g. 'OMIM:106210' (MIM Morbid) or 'ORPHA:550' (Orphanet). "
            "The prefix is case-sensitive."
        ),
        examples=["OMIM:106210", "ORPHA:550"],
    ),
]
