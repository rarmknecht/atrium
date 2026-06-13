---
title: Atrium
tags: [projects, active]
type: project
summary: Personal platform for custom agents and automations — modular, with a markdown context layer and React management UI.
---

# Atrium

A personal platform that hosts agents and automations as plug-in modules, gives them a
unified context layer (this vault), and is managed from a React web UI.

## Conventions

- Modules live in `modules/`, each with a `module.toml` manifest.
- This vault is the context layer's source of truth — markdown + wikilinks.
- Reports modules emit land in the platform's report feed.

## Relations

- built_with [[tooling]]
- reports_follow [[communication]]
