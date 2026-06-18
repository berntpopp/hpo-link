PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = OFF;

CREATE TABLE term (
    mondo_id     TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    name_upper   TEXT NOT NULL,
    definition   TEXT,
    is_obsolete  INTEGER NOT NULL DEFAULT 0,
    replaced_by  TEXT,
    consider     TEXT,
    synonyms     TEXT,
    subsets      TEXT
);
CREATE INDEX idx_term_name_upper ON term (name_upper);

CREATE TABLE term_lookup (
    lookup_label TEXT NOT NULL,
    mondo_id     TEXT NOT NULL,
    label_type   TEXT NOT NULL
);
CREATE INDEX idx_term_lookup ON term_lookup (lookup_label);

CREATE VIRTUAL TABLE term_fts USING fts5 (
    mondo_id UNINDEXED, name, synonyms, definition,
    tokenize = 'porter unicode61'
);

CREATE TABLE mondo_parent (
    mondo_id  TEXT NOT NULL,
    parent_id TEXT NOT NULL
);
CREATE INDEX idx_mondo_parent ON mondo_parent (mondo_id);
CREATE INDEX idx_mondo_parent_rev ON mondo_parent (parent_id);

CREATE TABLE mondo_closure (
    mondo_id    TEXT NOT NULL,
    ancestor_id TEXT NOT NULL
);
CREATE INDEX idx_mondo_closure ON mondo_closure (mondo_id);
CREATE INDEX idx_mondo_closure_anc ON mondo_closure (ancestor_id);

CREATE TABLE mondo_top_grouping (
    mondo_id      TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    display_order INTEGER
);

CREATE TABLE xref (
    mondo_id        TEXT NOT NULL,
    prefix          TEXT NOT NULL,
    object_id       TEXT NOT NULL,
    object_id_upper TEXT NOT NULL,
    predicate       TEXT NOT NULL,
    origin          TEXT NOT NULL,
    source          TEXT,
    object_label    TEXT
);
CREATE INDEX idx_xref_mondo ON xref (mondo_id);
CREATE INDEX idx_xref_obj ON xref (prefix, object_id_upper);

CREATE TABLE meta (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    schema_version    INTEGER,
    mondo_version     TEXT,
    source_purls      TEXT,
    source_validators TEXT,
    term_count        INTEGER,
    obsolete_count    INTEGER,
    closure_count     INTEGER,
    xref_count        INTEGER,
    mapping_count     INTEGER,
    build_utc         TEXT,
    build_duration_s  REAL
);
