-- Atrium platform state. The context vault lives on disk as markdown; everything
-- here is operational state or a rebuildable derived index.

CREATE TABLE module_config (
    module_id   TEXT PRIMARY KEY,
    config_json TEXT NOT NULL DEFAULT '{}',
    enabled     INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE triggers (
    id          TEXT PRIMARY KEY,
    module_id   TEXT NOT NULL,
    type        TEXT NOT NULL CHECK (type IN ('continuous', 'schedule', 'webhook', 'manual')),
    config_json TEXT NOT NULL DEFAULT '{}',   -- sleep_seconds | cron/interval | (webhook opts)
    token       TEXT,                          -- webhook secret token
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_triggers_module ON triggers (module_id);

CREATE TABLE runs (
    id           TEXT PRIMARY KEY,
    module_id    TEXT NOT NULL,
    trigger_id   TEXT,
    trigger_type TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('running', 'ok', 'warning', 'error', 'skipped', 'interrupted')),
    summary      TEXT NOT NULL DEFAULT '',
    data_json    TEXT,
    logs         TEXT NOT NULL DEFAULT '',
    tokens_in    INTEGER NOT NULL DEFAULT 0,
    tokens_out   INTEGER NOT NULL DEFAULT 0,
    started_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at  TEXT,
    duration_ms  INTEGER
);
CREATE INDEX idx_runs_module_started ON runs (module_id, started_at DESC);

CREATE TABLE reports (
    id         TEXT PRIMARY KEY,
    module_id  TEXT NOT NULL,
    run_id     TEXT,
    kind       TEXT NOT NULL DEFAULT 'report',
    title      TEXT NOT NULL,
    body_md    TEXT NOT NULL DEFAULT '',
    data_json  TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_reports_module_created ON reports (module_id, created_at DESC);
CREATE INDEX idx_reports_kind ON reports (kind);

CREATE TABLE kv_state (
    module_id  TEXT NOT NULL,
    key        TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (module_id, key)
);
