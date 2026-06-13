# Atrium — Architecture

> A personal platform for custom agents and automations: modular by design, with a unified
> context layer for personalization and a React web management layer.

**Status:** Draft v0.1 (POC architecture)
**Decisions locked:** Python plugin modules · FastAPI core · React UI · local-first, containerized for later always-on hosting

---

## 1. System Overview

```
┌────────────────────────────────────────────────────────────────────┐
│                         React Management UI                        │
│   Modules · Configuration · Triggers · Context Browser · Reports   │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ REST + WebSocket (FastAPI)
┌──────────────────────────────┴─────────────────────────────────────┐
│                          Atrium Core (Python)                      │
│                                                                    │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  ┌───────────┐  │
│  │   Module    │  │   Trigger    │  │  Reporting │  │   Run     │  │
│  │   Registry  │  │   Engine     │  │   Store    │  │  History  │  │
│  └──────┬──────┘  └──────┬───────┘  └────────────┘  └───────────┘  │
│         │                │                                         │
│  ┌──────┴────────────────┴──────────────────────────────────────┐  │
│  │                       Module Runner                          │  │
│  │     (executes module runs, injects ModuleContext)            │  │
│  └──────┬───────────────────────────────────────────────────────┘  │
│         │ ModuleContext                                            │
│  ┌──────┴──────────┐   ┌──────────────────┐   ┌─────────────────┐  │
│  │  Context Layer  │   │   LLM Service    │   │  Secrets/Config │  │
│  │  ("Librarian")  │   │ (Anthropic SDK)  │   │                 │  │
│  └─────────────────┘   └──────────────────┘   └─────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
         │                                  │
   markdown vault                     SQLite (platform state:
   (context docs, graph)              configs, runs, reports, triggers)
```

Two storage planes, deliberately separate:

- **Context vault** — a directory of markdown documents (human-readable, git-friendly,
  editable outside Atrium). Source of truth for *knowledge*.
- **SQLite** — platform state: module configs, trigger definitions, run history, reports,
  derived indexes. Source of truth for *operations*. Disposable/rebuildable where it caches
  vault-derived data (embeddings, link graph).

## 2. The Module Contract

A module is a **Python package implementing a defined interface**, discovered from a
`modules/` directory (and later via the `atrium.modules` entry-point group for pip-installed
modules). The contract is intentionally serializable-at-the-boundary so an out-of-process
adapter (any-language modules speaking JSON-RPC over stdio, MCP-server style) can be added
later without changing the core.

### 2.1 Layout

```
modules/
  inbox_triager/
    module.toml          # manifest (static metadata — readable without importing code)
    __init__.py          # exports a Module subclass
    main.py
    pyproject.toml       # optional: module-local deps (uv-managed)
```

### 2.2 Manifest (`module.toml`)

```toml
[module]
id = "inbox_triager"
name = "Inbox Triager"
version = "0.1.0"
description = "Labels and summarizes incoming mail"
kind = "agent"                  # agent | automation
[module.triggers]
supported = ["continuous", "schedule", "webhook", "manual"]
default = { type = "schedule", cron = "*/30 * * * *" }
[module.context]
# Vault paths/tags this module may read or write — enforced by the librarian
read = ["people/", "projects/", "preferences/"]
write = ["logs/inbox/"]
```

The manifest is static so the registry can list/validate modules without executing their code.

### 2.3 Python interface

```python
class Module(ABC):
    """Base class every Atrium module implements."""

    # Pydantic model defining the module's settings; the UI renders a config
    # form from its JSON schema, and the core validates before every run.
    ConfigModel: ClassVar[type[BaseModel]]

    async def setup(self, ctx: ModuleContext) -> None: ...      # optional
    @abstractmethod
    async def run(self, ctx: ModuleContext) -> RunResult: ...
    async def teardown(self, ctx: ModuleContext) -> None: ...   # optional
    async def handle_webhook(self, ctx: ModuleContext, payload: WebhookPayload) -> RunResult: ...
```

```python
class ModuleContext:
    config: BaseModel            # validated instance of ConfigModel
    librarian: LibrarianClient   # context layer: query / read / write (scoped by manifest)
    llm: LLMService              # Anthropic SDK wrapper (model defaults, usage tracking)
    report: Reporter             # emit reports surfaced in the UI
    state: KVStore               # per-module persistent key-value scratch state
    logger: Logger               # structured logs, streamed to UI via WebSocket
    secrets: SecretsView         # read-only, name-scoped secrets
    run_id: str
    trigger: TriggerInfo         # what fired this run (type + payload)
```

```python
class RunResult(BaseModel):
    status: Literal["ok", "warning", "error"]
    summary: str                      # one-liner shown in run history
    data: dict | None = None          # structured output, kept in run history
```

### 2.4 Isolation model

- **POC:** each run executes as an `asyncio` task inside the core process, wrapped with
  timeout + exception capture so a crashing module cannot take down the platform, and a
  per-module concurrency lock (one run at a time per module).
- **Phase 2:** runs move to **subprocess workers** (`uv run` in the module's own
  environment), communicating over the same serializable contract. This gives dependency
  isolation (each module may pin its own deps) and crash isolation without changing any
  module code.
- The contract never passes live Python objects across the boundary that couldn't be
  serialized — that's the rule that keeps the out-of-process door open.

### 2.5 What modules get from the platform (and shouldn't build themselves)

| Concern | Provided by |
|---|---|
| LLM access (Claude), model defaults, retries, usage metering | `ctx.llm` |
| Personal knowledge lookup/write | `ctx.librarian` |
| Scheduling, webhooks, always-on loops | Trigger Engine |
| Config UI + validation | `ConfigModel` JSON schema |
| Secrets | `ctx.secrets` (env/file-backed; never in module config) |
| Surfacing results | `ctx.report` + run history |

## 3. Trigger Engine

Trigger definitions live in SQLite and are editable per module from the UI. A module may
have multiple triggers of different types.

| Type | Semantics | Implementation |
|---|---|---|
| `continuous` | Always running; core calls `run()` in a loop with a configurable `sleep_seconds` between iterations | Supervisor task per module; restarts with exponential backoff on error |
| `schedule` | Cron expression or interval | APScheduler (`AsyncIOScheduler`), persisted job store |
| `webhook` | HTTP POST to `/api/hooks/{module_id}/{token}` | FastAPI route; per-trigger secret token; payload handed to `handle_webhook()` |
| `manual` | "Run now" button | Direct dispatch to Module Runner |

Engine guarantees: no overlapping runs per module (configurable), every fire recorded in run
history with trigger provenance, pause/resume per trigger from the UI.

## 4. Reporting

Modules emit reports through `ctx.report`:

```python
await ctx.report.emit(
    title="Weekly inbox summary",
    body_md="...markdown...",      # rendered in the UI
    kind="digest",                 # module-defined kinds, filterable
    data={...},                    # optional structured payload
)
```

Reports are stored in SQLite, listed and rendered (markdown) in the UI, filterable by
module/kind/date. Run history is separate: every run (any trigger) records status, summary,
duration, logs, and token usage.

## 5. Context Layer ("the Library + the Librarian")

### 5.1 Decision: build a thin custom layer from permissive building blocks

An open-source survey (see `docs/CONTEXT_LAYER_RESEARCH.md`) evaluated basic-memory, Letta,
mem0, Zep/Graphiti, Cognee, LlamaIndex, Microsoft GraphRAG, txtai, Khoj, LightRAG, and the
embedded vector stores. Conclusion:

- **Only basic-memory treats markdown-on-disk as the source of truth** — every other system
  ingests markdown into its own database/graph, violating the core requirement. But
  basic-memory is AGPL-3.0, MCP-first rather than library-first, and ships keyword search
  only (no semantic routing).
- **The librarian doesn't exist off the shelf anywhere.** Whatever we adopt, we write the
  routing layer ourselves — so we write it against our own clean document model.
- **The markdown/graph/sync substrate is small** (~500 LOC across parser, watcher, graph,
  index) and building it removes the AGPL question entirely.

**We therefore build the layer ourselves, adopting basic-memory's file conventions**
(frontmatter + `- relation_type [[Target]]` typed links) so the vault stays compatible with
Obsidian, basic-memory, Khoj, or LightRAG pointed at the same folder later — the escape
hatch is the file format itself.

| Component | Choice | Notes |
|---|---|---|
| Frontmatter parse/serialize | `python-frontmatter` | tiny, stable, MIT |
| Markdown + wikilink parsing | `markdown-it-py` + wikilink plugin | (obsidiantools is dormant — skip) |
| Link graph | `NetworkX` in-memory digraph | personal scale needs no graph DB; JSON-serialized for the UI graph view |
| File sync | `watchfiles` | reindex on change; vault in git for history |
| Lexical index | SQLite **FTS5** (BM25) | already have SQLite |
| Semantic index | local embeddings (`fastembed` or Ollama `nomic-embed-text`), brute-force NumPy at POC scale | swap to LanceDB if/when scale demands; sqlite-vec stalled as of research date |
| Librarian routing | two-stage: hybrid retrieval → LLM router (see 5.3) | ~200 LOC we control |
| Agent exposure | FastMCP server (`search`, `get_context`, `write_note`, `link_notes`) | same librarian usable from Claude Code / any MCP client |

### 5.2 Design (locked)

- **The Library:** a vault of markdown documents with YAML frontmatter (id, title, tags,
  type, updated) and `[[wikilinks]]` forming the graph. Files on disk are the source of
  truth; everything else (link graph, search index, embeddings) is derived and rebuildable.
- **The Librarian:** a routing service that, given a task/query from a module, returns the
  most relevant documents — not a dump of the whole vault. Likely hybrid retrieval
  (lexical + embeddings + graph-neighborhood expansion), with an optional LLM re-rank/route
  step for ambiguous queries.
- **Scoping:** modules declare read/write paths in their manifest; the librarian enforces it.
- **Editing:** full CRUD via API so the React UI can browse, read, edit, and add documents;
  the vault remains simultaneously editable with any text editor/Obsidian without breaking
  Atrium (a file watcher reindexes on change).

### 5.3 The Librarian: two-stage routing

1. **Cheap candidate generation** — hybrid search (FTS5 BM25 + embedding similarity, RRF
   fusion) over chunks, **plus the card catalog**: every doc's frontmatter `summary` line.
   At personal scale, the full catalog fits in a single prompt.
2. **LLM route** — one tool-calling request: task + card catalog + top hybrid hits → ranked
   doc IDs, optionally requesting 1-hop wikilink expansion. Context assembled as selected
   docs + linked-neighbor summaries.

Cheap queries can stop after stage 1; agentic modules use both. This mirrors the
hybrid+rerank architecture of Graphiti and LlamaIndex's RouterQueryEngine in a fraction of
the dependency surface.

### 5.4 Module-facing contract

```python
class LibrarianClient(Protocol):
    async def ask(self, query: str, k: int = 5, scope: list[str] | None = None) -> list[ContextDoc]
    async def get(self, doc_id: str) -> ContextDoc
    async def put(self, path: str, frontmatter: dict, body_md: str) -> ContextDoc
    async def append(self, doc_id: str, body_md: str) -> ContextDoc
    async def neighbors(self, doc_id: str, depth: int = 1) -> list[ContextDoc]
```

## 6. LLM Service

Thin wrapper over the official `anthropic` Python SDK:

- Default model `claude-opus-4-8`, adaptive thinking (`thinking={"type": "adaptive"}`),
  streaming for long outputs; per-module model/effort overrides in module config.
- Agent-style modules use Claude API tool use (the SDK tool runner) with tools the platform
  provides (librarian lookup as a tool, module-declared custom tools).
- Centralized: API-key handling, retries (SDK defaults), per-run token usage recorded into
  run history, prompt-caching hygiene (stable system prefixes).

## 7. Web Management Layer (React)

Vite + React + TypeScript, talking to FastAPI (`/api/*` REST, `/ws` for live run logs/status).

| Area | Capabilities |
|---|---|
| **Dashboard** | Module health at a glance, recent runs, recent reports |
| **Modules** | List installed modules (from registry), enable/disable, view manifest |
| **Module detail** | Config form auto-generated from the module's `ConfigModel` JSON schema; trigger management (add/edit/pause continuous/schedule/webhook); run history with logs; "Run now" |
| **Context** | Browse the vault (tree + search), read rendered markdown, edit/create documents, see backlinks/graph neighbors; later: graph visualization |
| **Reports** | Filterable feed of module-emitted reports, rendered markdown |
| **Settings** | API keys/secrets references, vault path, platform options |

## 8. API Surface (FastAPI)

```
GET    /api/modules                      list + manifests + status
GET    /api/modules/{id}                 detail, config schema, current config
PUT    /api/modules/{id}/config          validate + save config
POST   /api/modules/{id}/run             manual trigger
GET    /api/modules/{id}/runs            run history
GET    /api/triggers?module={id}         list triggers
POST   /api/triggers                     create (continuous/schedule/webhook)
PUT    /api/triggers/{id}                update / pause / resume
POST   /api/hooks/{module_id}/{token}    inbound webhook (public surface)
GET    /api/context/tree                 vault tree
GET    /api/context/doc?path=...         read document
PUT    /api/context/doc                  create/update document
POST   /api/context/ask                  librarian query (used by UI search + modules)
GET    /api/reports                      filterable report feed
WS     /ws                               run status + log streaming
```

## 9. Project Layout

```
atrium/
  pyproject.toml            # uv-managed
  atrium/
    core/                   # registry, runner, trigger engine, run history
    context/                # vault, indexer, librarian
    llm/                    # Anthropic SDK wrapper
    api/                    # FastAPI app, routes, websocket
    models/                 # shared pydantic models (manifest, results, reports)
  modules/                  # user modules live here (each its own package)
  vault/                    # the context layer's markdown documents
  web/                      # React app (Vite + TS)
  docs/
  docker-compose.yml        # core + web; volume-mounts vault/ and modules/
```

## 10. Deployment Posture

- **Now:** runs on the Windows dev machine — `uv run atrium serve` (single process: API +
  trigger engine), `npm run dev` for the UI.
- **From day one:** Dockerfile + compose so the same artifact moves to an always-on host
  later. Vault and modules are volume mounts; SQLite file lives in a data volume.
- **Later:** reverse proxy + auth (single-user token at minimum) before exposing webhooks
  beyond the LAN; optionally a tunnel (Cloudflare/Tailscale) for external webhook sources.

## 11. Key Risks / Open Questions

1. **Research freshness** — the context-layer survey was built from knowledge current to
   ~Jan 2026 (live web access unavailable at research time). Phase 0 of the POC plan
   includes a verification pass on the chosen libraries (see CONTEXT_LAYER_RESEARCH.md
   checklist). Risk is low because the chosen stack is all boring, mature, permissive deps.
2. **Module dependency conflicts** — POC shares one venv; subprocess-per-module (Phase 2)
   is the real fix. Keep module deps minimal until then.
3. **Continuous modules on a non-always-on machine** — acceptable for POC; the compose
   target exists precisely so this can move to an always-on box.
4. **Webhook exposure** — local-only for POC; security posture revisited before any tunnel.
