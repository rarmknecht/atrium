# Atrium — post-POC backlog

The POC (Phases 0–6) is a working, single-user platform. These are the deliberate
deferrals and natural next steps, roughly in priority order.

## Isolation & robustness
- **Per-module dependency isolation** — run modules in subprocess workers (`uv run` in
  each module's own environment) over the existing serializable contract, so modules can
  pin conflicting deps and a crash can't touch the platform process. The boundary was
  designed for this; no module code should need to change.
- **Out-of-process / any-language modules** — same contract over stdio JSON-RPC (MCP-style),
  enabling non-Python modules.
- **Router token accounting** — the librarian's stage-2 LLM call uses its own client; fold
  its usage into run accounting (currently only `ctx.llm` calls are metered).

## Context layer
- **Graph visualization** in the UI (the `/api/context/graph` data is already served).
- **Scale path for embeddings** — swap NumPy brute-force for LanceDB (or sqlite-vec once it
  hits stable) when the vault outgrows a few thousand docs.
- **Entity layer (optional)** — LightRAG-style LLM-extracted entity graph alongside the
  wikilink graph, if richer retrieval is ever needed.

## Reach & delivery
- **External webhooks** — a tunnel (Cloudflare/Tailscale) and hardening pass before exposing
  `/api/hooks/*` beyond the LAN.
- **Report notifications** — email/push when modules emit reports of a given kind.
- **Always-on host** — deploy the container to a NAS/VPS; the compose file already targets this.

## Platform polish
- **Multi-user / richer auth** — the current single bearer token is sufficient for personal
  use; real accounts + per-user vaults if ever shared.
- **Per-token log streaming** — the WebSocket streams run lifecycle events; live in-flight
  log tailing would need the runner to publish log lines incrementally.
- **Module hot-reload** — re-scan `modules/` without a restart.
- **Secrets management** — a first-class `ctx.secrets` backend (currently env-only).
- **JS dependency audit** — review `npm audit` advisories before any public deployment.
