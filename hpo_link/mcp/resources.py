"""Static string resources for HPO MCP instructions and discovery resources."""

from __future__ import annotations

from hpo_link.constants import HPO_LICENSE

RESEARCH_USE_NOTICE = (
    "Research use only; not for clinical decision support, diagnosis, "
    "treatment, or patient management."
)

HPO_SERVER_INSTRUCTIONS = (
    "HPO-Link grounds phenotype work in the Human Phenotype Ontology (HPO, "
    "https://hpo.jax.org/). It is backed by a local index built from the HPO OBO "
    "release and HPOA annotation files, so lookups are fast and offline.\n"
    "- Resolve first: hpo_resolve_term(query=) maps a phenotype label, synonym, "
    "HP id (HP:0000118), or external xref CURIE (UMLS:C0036572, "
    "SNOMEDCT_US:193046000, ...) to the canonical {hpo_id, name, match_type}. "
    "An ambiguous label returns ambiguous_query with candidates.\n"
    "- Record: hpo_get_term(term=) returns the term with definition, synonyms, "
    "alt_ids, xrefs, and obsolescence status. hpo_search_terms(query=) is FTS "
    "over name/synonyms/definition.\n"
    "- Hierarchy: hpo_get_term_parents / hpo_get_term_children for immediate "
    "neighbours; hpo_get_term_ancestors / hpo_get_term_descendants for transitive "
    "closure.\n"
    "- Cross-ontology: hpo_resolve_xref(xref_id=) maps an external CURIE back to "
    "HPO; hpo_map_cross_ontology(term=, prefixes=) lists a term's mappings to "
    "UMLS / SNOMED / NCIT / MEDDRA / ICD-10 / ICD-9 / MONDO / DOID / ORPHA.\n"
    "- Workflow: hpo_resolve_term -> hpo_get_term -> hpo_get_term_ancestors / "
    "hpo_get_term_descendants / hpo_get_term_parents / hpo_get_term_children -> "
    "hpo_resolve_xref / hpo_map_cross_ontology. Follow _meta.next_commands "
    "rather than guessing the next tool.\n"
    "- Verbosity: most tools take response_mode (minimal | compact | standard | "
    "full, default compact). Discovery: get_server_capabilities, "
    "or read hpo://capabilities / hpo://tools.\n"
    "- Citation: always cite the HP id AND the HPO release version "
    "(capabilities report it). HPO has a custom license (https://hpo.jax.org/app/license). "
    f"{RESEARCH_USE_NOTICE}"
)

HPO_USAGE_NOTES = (
    "Start with hpo_resolve_term to normalise any label/synonym/HP id/xref CURIE "
    "to its canonical term, then hpo_get_term for the full record. Navigate the "
    "DAG with hpo_get_term_parents/hpo_get_term_children (immediate) and "
    "hpo_get_term_ancestors/hpo_get_term_descendants (transitive). Map across "
    "ontologies with hpo_resolve_xref (external -> HPO) and hpo_map_cross_ontology "
    "(HPO -> external prefixes). Follow _meta.next_commands to advance without "
    "guessing the next tool."
)

HPO_REFERENCE_NOTES = (
    "Error codes (7): invalid_input, not_found, ambiguous_query, data_unavailable, "
    "rate_limited, upstream_unavailable, internal_error. match_type on "
    "hpo_resolve_term is one of hpo_id | primary | exact_synonym | "
    "related_synonym | xref (strongest first). First-class xref prefixes: UMLS, "
    "SNOMEDCT_US, NCIT, MEDDRA, ICD-10, ICD-9, ORPHA, MONDO, DOID, EFO, MSH, "
    "MESH. The local index is built from the HPO OBO and HPOA annotation releases "
    f"(https://hpo.jax.org/) and refreshed by an external cron job. {HPO_LICENSE}"
)
