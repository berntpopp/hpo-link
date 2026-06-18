"""Static string resources for MCP instructions and discovery resources."""

from __future__ import annotations

from hpo_link.constants import MONDO_LICENSE

RESEARCH_USE_NOTICE = (
    "Research use only; not for clinical decision support, diagnosis, "
    "treatment, or patient management."
)

MONDO_SERVER_INSTRUCTIONS = (
    "Mondo-Link grounds disease work in the Mondo Disease Ontology "
    "(mondo.monarchinitiative.org). It is backed by a local index built from the "
    "Mondo OBO + SSSOM releases (Monarch PURLs), so lookups are fast and offline.\n"
    "- Resolve first: resolve_disease(query=) maps a disease label, synonym, a "
    "MONDO id (MONDO:0008426 or 0008426), or a cross-reference CURIE "
    "(OMIM:182212, Orphanet:2462, DOID:..., ...) to the canonical "
    "{mondo_id, name, match_type}. An ambiguous label returns an ambiguous_query "
    "error with candidates.\n"
    "- Record: get_disease(term=) returns the term with definition, synonyms, "
    "xrefs, and obsolescence status. search_diseases(query=) is FTS over "
    "name/synonyms/definition.\n"
    "- Hierarchy: get_parents / get_children for the immediate neighbours and "
    "get_ancestors / get_descendants for the transitive closure.\n"
    "- Cross-ontology: resolve_xref(xref_id=) maps an external CURIE back to "
    "Mondo; map_cross_ontology(term=, prefixes=) lists a term's mappings to "
    "OMIM / Orphanet / DOID / NCIT / UMLS / MeSH / MedGen / SNOMED / GARD.\n"
    "- Workflow: resolve_disease -> get_disease -> get_disease_ancestors / "
    "get_disease_descendants / get_disease_parents / get_disease_children -> "
    "resolve_xref / map_cross_ontology. Follow _meta.next_commands rather than "
    "guessing the next tool.\n"
    "- Verbosity: most tools take response_mode (minimal | compact | standard | "
    "full, default compact). Discovery: get_server_capabilities or "
    "get_diagnostics, or read mondo://capabilities / mondo://tools.\n"
    "- Citation: always cite the MONDO id AND the Mondo release version "
    "(get_diagnostics / capabilities report it). Mondo is CC BY 4.0. "
    f"{RESEARCH_USE_NOTICE}"
)

MONDO_USAGE_NOTES = (
    "Start with resolve_disease to normalise any label/synonym/MONDO id/xref CURIE "
    "to its canonical term, then get_disease for the record. Navigate the DAG with "
    "get_parents/get_children (immediate) and get_ancestors/get_descendants "
    "(transitive). Map across ontologies with resolve_xref (external -> Mondo) and "
    "map_cross_ontology (Mondo -> external prefixes). Follow _meta.next_commands to "
    "advance without guessing the next tool."
)

MONDO_REFERENCE_NOTES = (
    "Error codes (7): invalid_input, not_found, ambiguous_query, data_unavailable, "
    "rate_limited, upstream_unavailable, internal_error. match_type on "
    "resolve_disease is one of mondo_id | primary | exact_synonym | "
    "related_synonym | xref (strongest first). Cross-references are ranked by "
    "mapping predicate, strongest first: exactMatch > equivalentTo > closeMatch > "
    "narrowMatch > broadMatch > xref. First-class xref prefixes: OMIM, ORPHA, "
    "DOID, NCIT, UMLS, MESH, MEDGEN, SCTID, GARD. The local index is built from "
    "the Mondo OBO + SSSOM releases (Monarch PURLs, data source = Mondo / Monarch "
    "Initiative) and refreshed by an external cron job; get_diagnostics reports "
    f"the loaded release and counts. {MONDO_LICENSE}"
)
