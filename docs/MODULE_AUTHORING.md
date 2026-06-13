# Authoring an Atrium module

A module is a Python package in `modules/` with a `module.toml` manifest and one
`Module` subclass. The platform discovers it, renders its config form, fires it on
triggers, scopes its vault access, and records every run — you just write `run()`.

## Layout

```
modules/
  my_module/
    module.toml      # static manifest (parsed without importing your code)
    __init__.py      # exports exactly one Module subclass
```

## 1. Manifest — `module.toml`

```toml
[module]
id = "my_module"            # must match [a-z][a-z0-9_]*, and the directory name
name = "My Module"
version = "0.1.0"
description = "What it does — shown in the UI"
kind = "automation"         # "automation" | "agent"
timeout_seconds = 120       # a run exceeding this is killed and recorded as error

[module.triggers]
supported = ["schedule", "manual"]   # "manual" is always allowed
default = { type = "schedule", cron = "0 7 * * *" }   # optional suggestion

[module.context]            # vault access, enforced by the librarian
read = []                   # path prefixes; [] = read the whole vault
write = ["logs/my_module/"] # path prefixes; [] = no writes
```

## 2. Code — `__init__.py`

```python
from pydantic import BaseModel, Field

from atrium.core.module import Module, ModuleContext
from atrium.models import RunResult


class Config(BaseModel):
    # Every field becomes a form control in the UI, validated on save and per run.
    greeting: str = Field(default="Hello", description="Shown as the field hint")
    limit: int = Field(default=10, ge=1, le=100)


class MyModule(Module):
    ConfigModel = Config           # omit for a config-less module

    async def run(self, ctx: ModuleContext) -> RunResult:
        cfg: Config = ctx.config
        ctx.logger.info("running with limit=%d", cfg.limit)      # captured into run logs

        # persistent per-module scratch state
        count = await ctx.state.get("count", 0) + 1
        await ctx.state.set("count", count)

        await ctx.report.emit(                                   # surfaced in the report feed
            title=f"{cfg.greeting} #{count}",
            body_md="## Result\n\n- did the thing",
            kind="result",
        )
        return RunResult(status="ok", summary=f"run #{count}", data={"count": count})
```

That's a complete, working module. Drop the folder in `modules/`, restart Atrium
(module discovery runs at startup), and it appears in the UI.

## What `ctx` gives you

| Field | Purpose |
|---|---|
| `ctx.config` | Validated instance of your `ConfigModel` |
| `ctx.logger` | Structured logging; captured into the run's logs (visible in the UI) |
| `ctx.state` | Per-module persistent KV: `await get(key, default)`, `set`, `delete` |
| `ctx.report.emit(...)` | Emit a report (title, body_md, kind, data) into the feed |
| `ctx.librarian` | Context vault — scope-enforced (see below) |
| `ctx.llm` | Claude access (agent modules) — needs `ANTHROPIC_API_KEY` |
| `ctx.trigger` | What fired this run (`type`, `trigger_id`, `payload`) |
| `ctx.run_id` | This run's id |

## Using the context vault

The librarian is scoped to your manifest's `read`/`write` prefixes — out-of-scope
access raises and the run is recorded as an error.

```python
hits = await ctx.librarian.ask("project status", k=5)        # hybrid search
bundle = await ctx.librarian.route("context for a brief", k=4) # LLM-routed selection
doc = await ctx.librarian.get("projects/atrium.md")
await ctx.librarian.append("logs/my_module/notes.md", "- a note")  # write scope enforced
```

## Calling Claude (agent modules)

```python
text = await ctx.llm.complete("Summarize this.", system="Be terse.")           # one-shot
result = await ctx.llm.parse("Extract fields.", output_format=MyPydanticModel)  # structured
# Tool-use loop with the librarian exposed as tools:
from atrium.llm.tools import librarian_tools
answer = await ctx.llm.agent("Explore the vault and answer.", tools=librarian_tools(ctx.librarian))
```

Token usage from any `ctx.llm` call is recorded on the run automatically.

## Triggers

A module declares which trigger types it supports; you create/configure actual
triggers per module in the UI (or via `POST /api/triggers`):

- **manual** — the "Run now" button (always available)
- **schedule** — cron expression or fixed interval (APScheduler)
- **continuous** — loops `run()` with a configurable sleep; backs off on errors
- **webhook** — `POST /api/hooks/{module_id}/{token}`; payload goes to `handle_webhook()`

For webhooks, override `handle_webhook(self, ctx, payload)` (it defaults to `run()`).

## Behavior contract

- Runs never overlap per module; a fire while busy is recorded as `skipped`.
- An exception, timeout, or out-of-scope vault access becomes an `error` run with the
  traceback in the logs — it never crashes the platform.
- A module whose code fails to import is listed with an `error` status; other modules
  are unaffected.
- Keep module dependencies minimal for now: the POC shares one virtualenv. Per-module
  dependency isolation (subprocess workers) is on the roadmap — see `docs/BACKLOG.md`.
