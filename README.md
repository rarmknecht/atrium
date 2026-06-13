# Atrium

A personal platform for custom agents and automations — modular by design, with a unified
markdown-based context layer ("the Library + the Librarian") for personalization, and a
React web management layer.

**Status:** working POC (Phases 0–6 complete) — modules, triggers, context layer, agent
modules, management UI, auth, and packaging.

## Quickstart

### Local (two processes, hot-reloading UI)

```bash
# 1. API + trigger engine (repo root)
uv sync
cp .env.example .env            # add ANTHROPIC_API_KEY for agent modules
uv run atrium serve             # http://127.0.0.1:8775

# 2. Management UI (web/)
cd web && npm install && npm run dev   # http://localhost:5173 (proxies to the API)
```

### Docker (single container, UI served by the API)

```bash
# build bundles the React UI and serves it from FastAPI on one port
docker compose up --build       # http://localhost:8775
# optional: require a token
ATRIUM_AUTH_TOKEN=$(openssl rand -hex 16) docker compose up --build
```

### Context vault over MCP

Expose the vault's librarian to Claude Code / Claude Desktop over stdio:

```bash
uv run atrium mcp               # tools: search/read/write/append context
```

## Configuration

Settings use the `ATRIUM_` env prefix (or `.env`). Common ones:

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required for agent modules and the librarian's LLM router |
| `ATRIUM_AUTH_TOKEN` | — | When set, UI/API require this bearer token (webhooks use their own) |
| `ATRIUM_VAULT_PATH` | `vault` | The markdown context vault |
| `ATRIUM_MODULES_PATH` | `modules` | Where module packages live |
| `ATRIUM_DATA_DIR` | `data` | Operational state (the SQLite DB) |
| `ATRIUM_EMBEDDINGS_PROVIDER` | `fastembed` | `fastembed` (local) or `off` (BM25-only search) |
| `ATRIUM_LLM_MODEL` | `claude-opus-4-8` | Default model for agent modules |

All three path settings accept absolute paths, which is the key to running your own
instance without entangling personal data with the repo — see below.

## Running your own instance

The repo ships a small **demo vault** (`vault/`) and **demo modules** (`modules/`) so the
platform runs out of the box. Both are tracked in git. For real day-to-day use you'll want
your own notes, modules, and database to live **outside the working tree**, so that
`git pull` only ever updates code and your private data is never at risk of being committed.

The clean pattern is one checkout for running plus a separate, un-tracked data directory:

```
atrium/                      # this clone — git pull for updates
atrium-data/                 # YOUR data — not a git repo, never touched by pull
├── vault/                   #   your real notes
├── modules/                 #   your personal modules
└── state/                   #   the sqlite db
```

Point Atrium at it via `.env` (which is gitignored, so it stays local). Use absolute paths:

```ini
# .env  (in your atrium clone)
ATRIUM_VAULT_PATH=/abs/path/to/atrium-data/vault
ATRIUM_MODULES_PATH=/abs/path/to/atrium-data/modules
ATRIUM_DATA_DIR=/abs/path/to/atrium-data/state
ANTHROPIC_API_KEY=sk-ant-...        # for agent modules + the librarian
ATRIUM_AUTH_TOKEN=...               # optional: require a bearer token for the UI/API
```

First-time setup:

1. **Create your data directory** and seed it from the demo content (a good starting point):
   ```bash
   mkdir -p ../atrium-data
   cp -r vault    ../atrium-data/vault      # or start empty
   cp -r modules  ../atrium-data/modules    # keeps the demo modules; delete what you don't want
   mkdir -p ../atrium-data/state
   ```
2. **Personalize.** Edit `../atrium-data/vault/preferences/communication.md` and replace
   `[YourName]` with the name you want agents to address you by. Adjust the other preference
   files to taste — they are read by the context layer and shape every brief and report.
3. **Configure** `.env` with the absolute paths above (copy `.env.example` as a starting point).
4. **Run:** `uv sync && uv run atrium serve` → http://127.0.0.1:8775

Now your vault, modules, and database live in `atrium-data/` while the clone stays clean;
`git pull` updates the code without ever colliding with your data. Back up `atrium-data/`
however you like (its own private git repo, cloud sync, etc.).

## Docs

| Doc | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design: module contract, trigger engine, context layer, LLM service, UI, API |
| [docs/MODULE_AUTHORING.md](docs/MODULE_AUTHORING.md) | How to write a module (worked example + the `ctx` contract) |
| [docs/POC_PLAN.md](docs/POC_PLAN.md) | The phased build plan with exit criteria |
| [docs/CONTEXT_LAYER_RESEARCH.md](docs/CONTEXT_LAYER_RESEARCH.md) | Survey behind the context-layer build-vs-adopt decision |
| [docs/BACKLOG.md](docs/BACKLOG.md) | Post-POC deferrals and next steps |
| [web/README.md](web/README.md) | UI architecture and the theming surface (one file to re-skin) |

## How it fits together

- **Modules** are Python plugin packages (`modules/<id>/` with `module.toml` + a `Module`
  subclass); the serializable contract keeps the door open for subprocess / out-of-process
  isolation later.
- **Triggers**: continuous (configurable sleep), cron schedule, webhook, manual.
- **Context layer**: the markdown vault on disk is the source of truth (Obsidian-compatible
  wikilinks, basic-memory conventions); a two-stage librarian (hybrid search → LLM router)
  serves relevant docs to modules; all indexes are derived and rebuildable.
- **Stack**: Python 3.12 + FastAPI + APScheduler + SQLite (uv-managed); Anthropic SDK
  for agent modules; React + Vite + TypeScript UI; Docker for the always-on host.

## License

[MIT-0](LICENSE) (MIT No Attribution) — do anything you like; no attribution required.
