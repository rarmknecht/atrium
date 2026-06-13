# Atrium

A personal platform for custom agents and automations — modular by design, with a unified
markdown-based context layer ("the Library + the Librarian") for personalization, and a
React web management layer.

**Status:** planning complete, build not started.

| Doc | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design: module contract, trigger engine, context layer, LLM service, UI, API |
| [docs/POC_PLAN.md](docs/POC_PLAN.md) | Phased build plan (Phases 0–6) with steps and exit criteria |
| [docs/CONTEXT_LAYER_RESEARCH.md](docs/CONTEXT_LAYER_RESEARCH.md) | Open-source survey behind the context-layer build-vs-adopt decision |

## Decisions at a glance

- **Modules** are Python plugin packages (`modules/<id>/` with `module.toml` + a `Module`
  subclass); serializable contract keeps the door open for subprocess / out-of-process
  isolation later.
- **Triggers**: continuous (configurable sleep), cron schedule, webhook, manual.
- **Context layer**: markdown vault on disk is the source of truth (Obsidian-compatible
  wikilinks, basic-memory conventions); a two-stage librarian (hybrid search → LLM router)
  serves relevant docs to modules; all indexes are derived and rebuildable.
- **Stack**: Python 3.12 + FastAPI + APScheduler + SQLite (uv-managed); Anthropic SDK
  (`claude-opus-4-8`) for agent modules; React + Vite + TypeScript UI; Docker from day one,
  local-first now, always-on host later.
