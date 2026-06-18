"""Shared annotated argument types for the Mondo MCP tools."""

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
        description="A disease label, synonym, a MONDO id (MONDO:0008426 or 0008426), or a "
        "cross-reference CURIE (OMIM:182212, Orphanet:2462, DOID:...).",
        examples=["Shprintzen-Goldberg syndrome", "MONDO:0008426", "OMIM:182212"],
    ),
]

TermStr = Annotated[
    str,
    Field(
        description="A MONDO id (MONDO:0008426 or 0008426), a disease label/synonym, or an "
        "external xref CURIE that resolves to a single Mondo term.",
        examples=["MONDO:0008426", "Marfan syndrome", "OMIM:182212"],
    ),
]

XrefIdStr = Annotated[
    str,
    Field(
        description="An external cross-reference CURIE (prefix:local), e.g. OMIM/Orphanet/DOID, "
        "to resolve back to the Mondo term(s) that map to it.",
        examples=["OMIM:182212", "Orphanet:2462", "DOID:0050776"],
    ),
]

FieldsArg = Annotated[
    list[str] | None,
    Field(
        description="Sparse fieldset: return ONLY these top-level keys (dot into a grouped "
        "object, e.g. 'xrefs.OMIM'). Identity anchors (mondo_id, name, mondo_version) are "
        "always included. Omit for the full payload.",
        examples=[["xrefs.OMIM"], ["definition", "parents"]],
    ),
]
