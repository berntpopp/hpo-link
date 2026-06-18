"""Domain constants for hpo-link: schema version, roots, xref prefixes, ranks."""

from __future__ import annotations

#: Bumped whenever the on-disk SQLite schema changes. v2 added xref.object_label
#: (the target term's human-readable name, from SSSOM); a rebuild populates it.
SCHEMA_VERSION = 2

#: The Mondo ontology root term ("disease or disorder").
MONDO_ROOT = "MONDO:0000001"

#: Root of Mondo's non-human-animal disease branch. Its descendants are veterinary
#: terms (e.g. "Marfan syndrome, FBN1-related, pig"); the resolver demotes them below
#: human terms in the fuzzy fallback so a human-disease query is not led by livestock.
NON_HUMAN_ANIMAL_ROOT = "MONDO:0005583"

#: Hard cap on items accepted by a single batch tool call (bounds token blowup /
#: abuse). Surfaced in capabilities.limits and enforced by the batch tools.
MAX_BATCH_ITEMS = 50

#: Cross-ontology prefixes surfaced as first-class xref sources.
XREF_PREFIXES = ("OMIM", "ORPHA", "DOID", "NCIT", "UMLS", "MESH", "MEDGEN", "SCTID", "GARD")

#: Mapping predicate -> rank for ordering cross-references (lower is stronger).
PREDICATE_RANK = {
    "exactMatch": 0,
    "equivalentTo": 1,
    "closeMatch": 2,
    "narrowMatch": 3,
    "broadMatch": 4,
    "xref": 5,
}

#: How a resolve match was made, strongest first. ``fuzzy`` is a conservative
#: FTS fallback used only when no exact id/xref/label match exists.
MATCH_TYPES = ("mondo_id", "primary", "exact_synonym", "related_synonym", "fuzzy", "xref")

#: Canonical citation pasted verbatim into capability/_meta payloads.
RECOMMENDED_CITATION = (
    "Vasilevsky NA, Matentzoglu NA, Toro S, et al. Mondo: Unifying diseases for the "
    "world, by the world. medRxiv 2022.04.13.22273750. "
    "doi:10.1101/2022.04.13.22273750. Mondo Disease Ontology, Monarch Initiative, "
    "https://mondo.monarchinitiative.org/."
)

#: License attribution surfaced in capability/reference notes.
MONDO_LICENSE = (
    "The Mondo Disease Ontology is distributed under CC BY 4.0 "
    "(https://creativecommons.org/licenses/by/4.0/). Cite Mondo / the Monarch Initiative."
)
