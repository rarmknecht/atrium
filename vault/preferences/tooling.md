---
title: Tooling preferences
tags: [preferences, development]
type: preference
summary: Development tooling defaults — Python via uv, TypeScript via Vite, local-first services.
---

# Tooling preferences

- Python projects are managed with **uv** (`uv sync`, `uv run`, `pyproject.toml`, `uv.lock`).
  Never pip-install into the system Python.
- Frontends are React + Vite + TypeScript.
- Prefer local-first services with permissive licenses; avoid mandatory cloud dependencies.
- relates_to [[atrium]]
