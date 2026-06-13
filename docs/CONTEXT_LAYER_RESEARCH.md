# Context-Layer Research: Markdown Knowledge Graph + "Librarian" Routing

> **Freshness caveat:** live web verification was unavailable when this survey was produced
> (June 2026); findings reflect project state as of ~January 2026. Items flagged ⚠️ are
> fast-moving — the verification checklist at the bottom is folded into POC Phase 0.

## Requirements (scoring lens)

1. Markdown files **on disk as source of truth** (human-editable, wiki-links)
2. Graph structure over documents (links/backlinks, optionally entities)
3. A "librarian": given an agent's task/query, route to the most relevant documents
4. Embeddable in a Python/FastAPI backend, fully local-capable
5. API surface for read/edit/add from a React management UI

## Comparison table

| Candidate | MD = truth? | Doc/link graph | Semantic search | LLM routing | Embeddable lib | MCP | License | Fit |
|---|---|---|---|---|---|---|---|---|
| basic-memory | **Yes** | **Yes (wikilinks)** | No (FTS5) | No (delegated to LLM) | Partial (MCP-first) | Yes | AGPL-3.0 | **9 (truth) / needs librarian** |
| Letta (MemGPT) | No | No | Yes | Agentic | Server, not lib | Yes | Apache | 3 |
| mem0 | No | Entity graph opt. | Yes | No | Yes | Yes | Apache | 3 |
| Graphiti (Zep) | No | Entity graph (temporal) | Hybrid+rerank | No | Yes (+graph DB svc) | Yes | Apache | 4 |
| Cognee | No (ingest) | Derived entity graph | Yes | No | Yes | Yes | Apache | 5 |
| LlamaIndex | No (ingest) | PropertyGraph (DIY) | Yes | **RouterQueryEngine** | **Yes** | Adapters | MIT | 7 (toolkit) |
| MS GraphRAG | No | Derived, batch | Yes | Map-reduce | Poor | No | MIT | 2 |
| txtai | No (ingest) | Semantic + manual edges | Hybrid | No | **Yes** | Yes (2025) | Apache | 6 (index engine) |
| obsidiantools | n/a (parser) | **Yes (NetworkX)** | No | No | Yes (dormant ⚠️) | No | MIT | parser only |
| Chroma / LanceDB / sqlite-vec | n/a | No | Yes | No | Yes | n/a | Apache/MIT | building block |
| Khoj | Files read-only | No | Yes+rerank | No | App, not lib | Yes | AGPL-3.0 | 3 |
| LightRAG (HKUDS) | No (ingest) | Derived entity graph | Hybrid | Dual-level | Yes | Community | MIT (verify) | 5–6 |

## Key candidate notes

- **basic-memory** — the only project whose core contract matches ours: markdown files =
  truth, SQLite = disposable derived index, wikilink graph, file-watch sync, MCP tools
  (`search_notes`, `build_context`). Gaps: keyword search only (no embeddings/routing),
  AGPL-3.0 (fine for personal use; entangling if ever distributed), MCP/CLI-first internals
  without API stability guarantees. **We adopt its file conventions** — frontmatter +
  observation/relation syntax (`- relation_type [[Target]]`) — not its code.
- **LlamaIndex** — strongest *toolkit*: RouterQueryEngine/selectors are literally the
  librarian primitive; ObsidianReader parses vaults with wikilink metadata. MIT, embeds
  cleanly. But markdown is ingest-only (no write-back), and pulling it in for the router
  alone is a heavy dependency for ~200 LOC of logic we can own.
- **Graphiti** — wrong source-of-truth model and needs a graph DB service, but its hybrid
  retrieval design (semantic + BM25 + graph traversal + rerankers) is the reference
  architecture our librarian's stage-1 imitates.
- **Letta / mem0** — DB-centric agent memory; would fight the markdown requirement. mem0
  could later be an *additional* auto-extracted conversation-memory stream beside the vault.
- **MS GraphRAG** — batch corpus analytics, expensive re-index on change; hostile to a
  living hand-edited KB. LightRAG is the lighter incremental take if we ever want
  LLM-extracted entity graphs *in addition to* the wikilink graph.
- **Khoj** — an app (Django + Postgres), not a library; integration would be REST-only.
- **Validating precedents (2025):** mem-agent (driaforall) — a small model whose whole job
  is maintaining an Obsidian-style markdown memory behind MCP; MemU — agent memory as a
  readable file notebook curated by a memory agent. Both prove the markdown-as-truth +
  model-as-librarian pattern.

## Recommendation (adopted in ARCHITECTURE.md §5)

**Roll our own thin core, pilfering basic-memory's conventions.**

1. The hard *requirement* (markdown = truth) is the easy part to *build* (parser + watcher +
   NetworkX ≈ days), while every off-the-shelf system except basic-memory violates it by
   design.
2. The differentiating component (the librarian) doesn't exist off the shelf anyway — we
   write it regardless, so write it against our own clean document model.
3. License/ops hygiene: all MIT/Apache deps, zero services, one process inside FastAPI.
4. Escape hatches preserved: the vault is plain Obsidian-compatible markdown, so
   basic-memory, Khoj, Obsidian, or LightRAG can be pointed at the same folder later with
   no migration.

Stack: `python-frontmatter` + `markdown-it-py` (wikilinks) + `NetworkX` + `watchfiles` +
SQLite FTS5 + local embeddings (fastembed / Ollama `nomic-embed-text`, NumPy brute-force at
personal scale; LanceDB as the upgrade path) + two-stage librarian (hybrid RRF → LLM router
over a "card catalog" of doc summaries) + FastMCP exposure.

Fallback if we'd rather not own the file layer: run basic-memory as an AGPL-isolated sidecar
process for vault/graph/sync and build only the librarian ourselves.

## Phase-0 verification checklist — results (verified live, June 2026)

| # | Item | Result | Plan impact |
|---|---|---|---|
| 1 | basic-memory | ✅ Active in 2026; **still AGPL-3.0** | None — we adopt conventions, not code |
| 2 | sqlite-vec | ⚠️ Research said stalled, but it **revived in 2026** (0.1.8–0.1.10-alpha, Mar–Apr 2026; DiskANN coming). Still pre-v1 alpha | NumPy brute-force first stands; sqlite-vec rejoins LanceDB as an upgrade path once it hits stable |
| 3 | fastembed | ✅ Active; ONNX-quantized CPU-friendly models (default bge-small); Ollama `nomic-embed-text` also fine | Phase 3 choice confirmed |
| 4 | Core deps | ✅ `uv sync` resolved current 2026 releases: python-frontmatter 1.3, markdown-it-py 4.2, networkx 3.6, watchfiles 1.2, anthropic 0.109, fastapi 0.136 | All alive |
| 5 | Kuzu / LightRAG / txtai / mem-agent / MemU | Not re-verified — none are dependencies of the chosen design | Re-check only if we later add an entity-graph layer |

Sources: [basic-memory GitHub](https://github.com/basicmachines-co/basic-memory),
[basicmemory.com](https://basicmemory.com/),
[sqlite-vec releases](https://github.com/asg017/sqlite-vec/releases),
[Ollama nomic-embed-text](https://ollama.com/library/nomic-embed-text).

**Conclusion: the recommended stack is confirmed; no changes to the architecture or plan.**
