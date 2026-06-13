# Atrium — POC Build Plan

Companion to [ARCHITECTURE.md](ARCHITECTURE.md). Phases are ordered so that **every phase
ends with something runnable and demonstrable**; later phases never require rework of
earlier ones (contracts are defined up front).

**POC definition of done:** two modules (one automation, one Claude-powered agent) running
on real triggers, reading/writing a personal context vault through the librarian, with all
management — config, triggers, context editing, reports — done through the React UI.

---

## Phase 0 — Foundations & verification (≈ a day)

Goal: empty-but-running skeleton; library choices confirmed.

1. Init repo `atrium/` with the layout from ARCHITECTURE.md §9; `git init`.
2. `uv init` the Python project (Python 3.12+); add core deps: `fastapi`, `uvicorn`,
   `pydantic`, `apscheduler`, `aiosqlite`, `python-frontmatter`, `markdown-it-py`,
   `networkx`, `watchfiles`, `anthropic`.
3. Run the **research verification checklist** (CONTEXT_LAYER_RESEARCH.md) with live web
   access; adjust embedding/index choices if anything moved (expected outcome: no change,
   the stack is deliberately boring).
4. FastAPI app skeleton: `/api/health`, settings via pydantic-settings (`.env`: vault path,
   DB path, `ANTHROPIC_API_KEY`).
5. SQLite bootstrap + migrations approach (plain versioned SQL scripts is fine at this
   scale): tables for `module_config`, `triggers`, `runs`, `reports`, `kv_state`.
6. Dockerfile + `docker-compose.yml` stubs (core service; vault + data volumes) so the
   containerized path exists from day one.

**Exit criteria:** `uv run atrium serve` answers `/api/health`; `docker compose up` does the
same; deps locked in `uv.lock`.

## Phase 1 — Module system core (≈ 2–3 days)

Goal: the module contract is real; a hello-world module runs.

1. Define shared models in `atrium/models/`: `ModuleManifest` (parsed from `module.toml`),
   `RunResult`, `Report`, `TriggerInfo`, `WebhookPayload`.
2. Implement `Module` base class + `ModuleContext` (logger, `state` KV, `report` stubbed to
   DB writes; `librarian`/`llm` raise `NotImplemented` until Phases 3–4).
3. **Registry**: scan `modules/`, parse manifests *without importing code*, validate, then
   import each module's `Module` subclass; surface load errors as module status (a broken
   module must never break the platform).
4. **Runner**: execute `run()` as a supervised asyncio task — timeout, exception capture,
   per-module concurrency lock, structured log capture; persist a `runs` row (status,
   summary, duration, logs, trigger provenance).
5. Config plumbing: store per-module config JSON in SQLite; validate against the module's
   `ConfigModel` on save and before every run; expose the JSON schema for the future UI.
6. Write `modules/hello_world/`: manifest + `ConfigModel` (e.g. `greeting: str`) + `run()`
   that logs, sleeps, reports, returns a `RunResult`.
7. API: `GET /api/modules`, `GET /api/modules/{id}`, `PUT /api/modules/{id}/config`,
   `POST /api/modules/{id}/run`, `GET /api/modules/{id}/runs`.

**Exit criteria:** `POST /api/modules/hello_world/run` executes the module, run history shows
status/logs/summary, invalid config is rejected with field-level errors, and a deliberately
crashing module shows `error` status without affecting the server.

## Phase 2 — Trigger engine (≈ 2 days)

Goal: all four trigger types fire real runs.

1. Trigger CRUD: `GET/POST /api/triggers`, `PUT /api/triggers/{id}` (incl. pause/resume);
   persisted in SQLite; validated against the module manifest's `triggers.supported`.
2. **Schedule**: APScheduler `AsyncIOScheduler`; cron + interval; jobs rebuilt from DB on
   startup; misfire policy = skip (don't pile up).
3. **Continuous**: supervisor task per enabled trigger — loop `run()` → sleep
   `sleep_seconds` → repeat; exponential backoff on consecutive errors; clean cancel on
   pause/shutdown.
4. **Webhook**: `POST /api/hooks/{module_id}/{token}` — per-trigger random token, payload
   capture (headers subset + body), dispatch to `handle_webhook()`; 404 on bad token.
5. No-overlap guarantee: a fire that arrives while the module is running is skipped and
   recorded as `skipped` (visible in run history).
6. Extend hello_world (or add `modules/heartbeat/`) to exercise continuous + schedule;
   test webhook with `curl`.

**Exit criteria:** a cron trigger fires on time across a server restart; a continuous module
survives an induced exception (backoff visible in logs); a webhook POST produces a run with
the payload available to the module.

## Phase 3 — Context layer: vault + librarian (≈ 3–4 days)

Goal: the vault is queryable and editable; modules get `ctx.librarian`.

1. **Vault parser**: walk `vault/`, parse frontmatter (`id`, `title`, `tags`, `type`,
   `summary`, `updated`) + extract `[[wikilinks]]` (and basic-memory-style
   `- relation_type [[Target]]` typed relations); normalize into `ContextDoc`.
2. **Graph**: NetworkX digraph (docs = nodes, links = typed edges); backlinks +
   `neighbors(depth)`; JSON export endpoint for the future UI graph view.
3. **Indexer**: SQLite FTS5 table over title/summary/body chunks; `watchfiles` watcher
   reindexes incrementally on file change (hash-based change detection). Files remain
   source of truth — the index is rebuildable via a `reindex` command.
4. **Embeddings**: chunk docs (heading-aware), embed with fastembed (or Ollama
   `nomic-embed-text`), cache vectors in SQLite keyed by content hash; brute-force NumPy
   cosine at query time.
5. **Librarian stage 1**: hybrid query — BM25 + vector, RRF fusion → top-k chunks → parent
   docs. Expose as `librarian.ask(query, k, scope)`.
6. **Librarian stage 2 (route)**: one Claude tool-call — task + card catalog (all doc
   summaries) + stage-1 hits → ranked doc IDs (+ optional 1-hop expansion request);
   assemble context bundle. Used by agent modules; UI search uses stage 1 only.
7. Manifest **scope enforcement**: `read`/`write` path prefixes checked in
   `LibrarianClient` per module.
8. API: `GET /api/context/tree`, `GET/PUT /api/context/doc`, `POST /api/context/ask`,
   `GET /api/context/graph`. Writes go **file-first** (write markdown → watcher reindexes),
   never DB-first.
9. Seed a real starter vault: `preferences/`, `people/`, `projects/`, `logs/`.

**Exit criteria:** editing a file in any external editor is reflected in search within
seconds; `POST /api/context/ask` returns sensibly-ranked docs for natural-language queries;
a module writing outside its manifest scope is rejected.

## Phase 4 — LLM service + first real agent module (≈ 2–3 days)

Goal: prove the personalization loop — an agent that's better *because* of the vault.

1. **LLMService**: wrapper over the `anthropic` SDK — default `claude-opus-4-8`,
   `thinking={"type": "adaptive"}`, streaming for long outputs, per-module model/effort
   overrides, token usage recorded onto the run row; stable system-prefix construction for
   prompt-cache hygiene.
2. Agent loop support: SDK tool runner with platform-provided tools — `librarian_ask` /
   `librarian_get` / `vault_write` (scope-enforced) — plus module-declared custom tools.
3. Build the first real module — **`daily_brief`** (agent): on a morning cron, pulls
   today's calendar/weather/whatever sources are configured, routes through the librarian
   for relevant projects/people/preferences context, and emits a personalized markdown
   brief as a report (optionally appends to `logs/briefs/`).
4. Build a second, non-LLM module — e.g. **`vault_janitor`** (automation): scheduled scan
   for orphan docs / missing frontmatter / dead links; emits a findings report. Proves the
   modularity claim: two modules, zero coupling.
5. Reporting polish: `GET /api/reports` with module/kind/date filters.

**Exit criteria:** `daily_brief` runs off its cron, demonstrably uses vault content (change
a preference doc → next brief reflects it), token usage visible in run history; both modules
coexist with independent configs/triggers.

## Phase 5 — React management UI (≈ 4–5 days)

Goal: everything manageable from the browser; no more curl.

1. Scaffold `web/`: Vite + React + TypeScript; TanStack Query for API state; Tailwind (or
   similar) for speed; generated API client from FastAPI's OpenAPI schema.
2. **Dashboard**: module cards (status, last run, next fire), recent runs, recent reports.
3. **Module detail**: config form auto-rendered from `ConfigModel` JSON schema
   (`@rjsf/core` or a thin custom renderer); save with server-side validation errors
   surfaced per field; enable/disable; "Run now".
4. **Triggers UI**: per-module list; create/edit continuous (sleep seconds), schedule
   (cron with human-readable preview), webhook (show URL + token, regenerate token);
   pause/resume.
5. **Run history**: table with status filters; run detail with logs; live status/log
   streaming over `/ws` for in-flight runs.
6. **Context browser**: vault tree + stage-1 search; rendered markdown view with backlinks
   panel; edit/create with a markdown editor (CodeMirror); delete with confirm.
7. **Reports feed**: filterable, rendered markdown.
8. **Settings**: vault path, API key status (set via env; UI shows presence only).

**Exit criteria:** a full workflow — install a new module by dropping a folder, configure
it, add a schedule, watch it run live, read its report, and edit the context doc it used —
entirely in the browser.

## Phase 6 — Hardening & packaging (≈ 2 days)

Goal: POC is honest about being software.

1. Finish Docker: multi-stage build (web build → static files served by FastAPI), compose
   with vault/data volumes; verify parity with local dev.
2. Single-user auth: bearer token on `/api/*` (webhooks keep their own per-trigger tokens);
   UI login.
3. Lifecycle correctness: graceful shutdown (drain continuous loops, persist scheduler
   state), startup recovery (mark orphaned `running` runs as `interrupted`).
4. FastMCP server exposing librarian tools (`search`, `get_context`, `write_note`) so
   Claude Code / other MCP clients can use the same context layer.
5. `README.md` (quickstart) + `docs/MODULE_AUTHORING.md` (how to write a module, with
   hello_world as the worked example).
6. Backlog triage for post-POC: subprocess module isolation, graph visualization, tunnel +
   external webhooks, report notifications (email/push), module marketplace-of-one.

**Exit criteria:** `docker compose up` on a clean machine + a `.env` gives a working,
token-protected Atrium; a new module can be authored from the docs alone.

---

## Sequencing notes

- Phases 1–2 (module system + triggers) deliberately precede the context layer: they're the
  platform's spine and testable without any LLM spend.
- Phase 3 is the largest novel-engineering chunk; its contract (`LibrarianClient`) is
  already frozen in ARCHITECTURE.md §5.4, so Phases 1–2 code against the interface.
- UI is one phase late on purpose — every API it needs already exists and has been exercised
  by curl/tests, so Phase 5 is purely presentational.
- Total: roughly **15–20 focused days** end to end; each phase leaves a usable system, so
  it parallelizes/pauses cleanly.
