-- Context-layer derived index. The vault's markdown files are the source of truth;
-- everything in these tables is rebuildable via a full reindex.

CREATE TABLE context_docs (
    path         TEXT PRIMARY KEY,   -- vault-relative posix path, e.g. 'people/jane.md'
    title        TEXT NOT NULL,
    tags_json    TEXT NOT NULL DEFAULT '[]',
    type         TEXT,
    summary      TEXT,
    updated      TEXT,
    links_json   TEXT NOT NULL DEFAULT '[]',  -- [{target, relation}] (resolved paths)
    content_hash TEXT NOT NULL,
    indexed_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Lexical index: one row per chunk. BM25 via FTS5 'rank'.
CREATE VIRTUAL TABLE context_chunks USING fts5(
    path UNINDEXED,
    chunk_idx UNINDEXED,
    heading,
    content
);

-- Embedding cache: keyed by chunk content hash so unchanged chunks never re-embed.
CREATE TABLE context_embeddings (
    path         TEXT NOT NULL,
    chunk_idx    INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    model        TEXT NOT NULL,
    dim          INTEGER NOT NULL,
    vector       BLOB NOT NULL,      -- float32 little-endian
    PRIMARY KEY (path, chunk_idx)
);
CREATE INDEX idx_context_embeddings_hash ON context_embeddings (content_hash, model);
