# Atrium Web UI

React + Vite + TypeScript management UI for Atrium.

## Develop

```bash
# 1. Run the Atrium API (from the repo root)
uv run atrium serve

# 2. Run the UI (from web/)
npm install
npm run dev          # http://localhost:5173, proxies /api and /ws to :8775
```

`npm run build` type-checks (`tsc -b`) and produces `dist/` (served by FastAPI in Phase 6).

## Architecture

- **State**: TanStack Query (`src/api/hooks.ts`) over a typed fetch client (`src/api/client.ts`).
- **Live updates**: one shared WebSocket to `/ws` (`src/api/useRunEvents.tsx`) invalidates
  caches and tracks in-flight runs as they fire.
- **Config forms**: `src/components/SchemaForm.tsx` renders each module's config form from
  the JSON schema the API exposes — no per-module UI code.
- **Pages**: `src/pages/` — Dashboard, Modules, ModuleDetail, Context, Reports, Settings.

## Theming — the one place to change look & feel

**All visual design lives in `src/theme/tokens.css`.** Components never hardcode colors,
spacing, or fonts — they reference semantic CSS custom properties only. To re-skin Atrium
(e.g. with Claude design), edit that one file:

- **Re-palette**: change the PRIMITIVE tokens (the raw color ramp + accent hues).
- **Re-skin**: change the SEMANTIC tokens (`--bg`, `--surface`, `--text`, `--accent`,
  status colors, radii, shadows, fonts). The whole UI follows.
- **Themes**: dark is the default (`<html data-theme="dark">`); light overrides the semantic
  layer under `[data-theme="light"]`. Add more themes by adding `[data-theme="…"]` blocks.

The other theme files are deliberately thin and shouldn't need touching for a re-skin:
`base.css` (element resets), `components.css` (reusable classes built from tokens),
`markdown.css` (rendered-markdown styling). If a component needs a new color or size,
add a token in `tokens.css` and reference it — never inline a literal value.
