PRAGMA journal_mode = WAL;

-- Ontology -----------------------------------------------------------------
CREATE TABLE term (
  hpo_id      TEXT PRIMARY KEY,      -- HP:0000118
  name        TEXT NOT NULL,
  name_upper  TEXT NOT NULL,
  definition  TEXT,
  is_obsolete INTEGER NOT NULL DEFAULT 0,
  replaced_by TEXT,
  consider    TEXT,                  -- JSON list
  alt_ids     TEXT,                  -- JSON list
  synonyms    TEXT,                  -- JSON [{text, scope}]
  subsets     TEXT,                  -- JSON list
  comments    TEXT                   -- JSON list
);
CREATE INDEX idx_term_name_upper ON term(name_upper);

CREATE TABLE term_lookup (           -- resolve(): label/synonym/alt_id -> hpo_id
  lookup_label TEXT NOT NULL,        -- uppercased
  hpo_id       TEXT NOT NULL,
  label_type   TEXT NOT NULL         -- primary|exact_synonym|related_synonym|broad_synonym|narrow_synonym|alt_id
);
CREATE INDEX idx_term_lookup ON term_lookup(lookup_label);

CREATE VIRTUAL TABLE term_fts USING fts5(
  hpo_id UNINDEXED, name, synonyms, definition,
  tokenize = 'porter unicode61'
);

CREATE TABLE hpo_parent (hpo_id TEXT NOT NULL, parent_id TEXT NOT NULL);
CREATE INDEX idx_hpo_parent     ON hpo_parent(hpo_id);
CREATE INDEX idx_hpo_parent_rev ON hpo_parent(parent_id);

CREATE TABLE hpo_closure (hpo_id TEXT NOT NULL, ancestor_id TEXT NOT NULL); -- incl. self
CREATE INDEX idx_hpo_closure     ON hpo_closure(hpo_id);
CREATE INDEX idx_hpo_closure_anc ON hpo_closure(ancestor_id);

CREATE TABLE xref (
  hpo_id          TEXT NOT NULL,
  prefix          TEXT NOT NULL,     -- UMLS, SNOMEDCT_US, NCIT, MEDDRA, ICD-10, MONDO, ...
  object_id       TEXT NOT NULL,
  object_id_upper TEXT NOT NULL,
  origin          TEXT NOT NULL      -- 'obo_xref'
);
CREATE INDEX idx_xref_hpo ON xref(hpo_id);
CREATE INDEX idx_xref_obj ON xref(prefix, object_id_upper);

-- Annotations (HPOA) -------------------------------------------------------
CREATE TABLE disease_phenotype (
  database_id  TEXT NOT NULL,        -- OMIM:619340 / ORPHA:.. / DECIPHER:..
  disease_name TEXT,
  hpo_id       TEXT NOT NULL,
  qualifier    TEXT,                 -- '' or 'NOT'
  reference    TEXT,
  evidence     TEXT,
  onset        TEXT,
  frequency    TEXT,                 -- raw
  frequency_hpo     TEXT,
  frequency_ratio   TEXT,
  frequency_percent REAL,
  sex          TEXT,
  modifier     TEXT,
  aspect       TEXT,                 -- P|C|I|M
  biocuration  TEXT
);
CREATE INDEX idx_dp_hpo     ON disease_phenotype(hpo_id);
CREATE INDEX idx_dp_disease ON disease_phenotype(database_id);

CREATE TABLE gene_phenotype (
  ncbi_gene_id     TEXT NOT NULL,
  gene_symbol      TEXT NOT NULL,
  gene_symbol_upper TEXT NOT NULL,
  hpo_id           TEXT NOT NULL,
  frequency        TEXT,
  disease_id       TEXT
);
CREATE INDEX idx_gp_gene ON gene_phenotype(gene_symbol_upper);
CREATE INDEX idx_gp_ncbi ON gene_phenotype(ncbi_gene_id);
CREATE INDEX idx_gp_hpo  ON gene_phenotype(hpo_id);

CREATE TABLE gene_disease (
  ncbi_gene_id      TEXT NOT NULL,
  gene_symbol       TEXT NOT NULL,
  gene_symbol_upper TEXT NOT NULL,
  association_type  TEXT,            -- MENDELIAN|...
  disease_id        TEXT NOT NULL,
  source            TEXT
);
CREATE INDEX idx_gd_gene    ON gene_disease(gene_symbol_upper);
CREATE INDEX idx_gd_ncbi    ON gene_disease(ncbi_gene_id);
CREATE INDEX idx_gd_disease ON gene_disease(disease_id);

-- Provenance ---------------------------------------------------------------
CREATE TABLE meta (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  schema_version INTEGER,
  hpo_version    TEXT,               -- e.g. 2026-06-06
  hpoa_version   TEXT,
  source_purls       TEXT,           -- JSON
  source_validators  TEXT,           -- JSON {etag,last_modified} per file
  term_count INTEGER, obsolete_count INTEGER, closure_count INTEGER, xref_count INTEGER,
  disease_phenotype_count INTEGER, gene_phenotype_count INTEGER, gene_disease_count INTEGER,
  build_utc TEXT, build_duration_s REAL
);
