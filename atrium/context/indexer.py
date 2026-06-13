"""Vault indexer: keeps the derived SQLite index (docs, FTS5 chunks, embeddings)
and the in-memory link graph in sync with the markdown files on disk.

Files are the source of truth. The watcher picks up external edits (any editor,
Obsidian, git pull); API writes index synchronously for read-your-write behavior.
"""

import asyncio
import json
import logging
from pathlib import Path

import aiosqlite
import networkx as nx
import numpy as np
import watchfiles

from atrium.context.embeddings import EmbeddingProvider
from atrium.context.vault import LinkResolver, VaultStore, chunk_body, parse_markdown

logger = logging.getLogger(__name__)


class VaultIndexer:
    def __init__(
        self,
        db: aiosqlite.Connection,
        store: VaultStore,
        embeddings: EmbeddingProvider | None,
    ):
        self._db = db
        self.store = store
        self._embeddings = embeddings
        self.graph = nx.DiGraph()
        self._watch_task: asyncio.Task | None = None
        self._index_lock = asyncio.Lock()

    # -- full scan -------------------------------------------------------------

    async def full_scan(self) -> dict:
        """Index new/changed files, drop deleted ones, rebuild the graph."""
        async with self._index_lock:
            on_disk = self.store.list_paths()
            async with self._db.execute(
                "SELECT path, content_hash FROM context_docs"
            ) as cur:
                indexed = {row["path"]: row["content_hash"] for row in await cur.fetchall()}

            added = changed = 0
            for rel in on_disk:
                try:
                    doc = self.store.read(rel)
                except Exception as exc:
                    logger.warning("skipping unreadable vault file %s: %s", rel, exc)
                    continue
                if rel not in indexed:
                    added += 1
                elif indexed[rel] != doc.content_hash:
                    changed += 1
                else:
                    continue
                await self._index_parsed(doc)

            removed = set(indexed) - set(on_disk)
            for rel in removed:
                await self._remove(rel)

            await self._db.commit()
            await self._rebuild_links_and_graph()
            stats = {
                "docs": len(on_disk), "added": added,
                "changed": changed, "removed": len(removed),
            }
            logger.info("vault scan: %s", stats)
            return stats

    async def index_file(self, rel_path: str) -> None:
        """Index one file (used by API writes and the watcher)."""
        async with self._index_lock:
            abs_path = self.store.abs_path(rel_path)
            if not abs_path.is_file():
                await self._remove(rel_path)
            else:
                doc = parse_markdown(
                    self.store.normalize(rel_path), abs_path.read_text(encoding="utf-8")
                )
                await self._index_parsed(doc)
            await self._db.commit()
            await self._rebuild_links_and_graph()

    # -- internals ---------------------------------------------------------------

    async def _index_parsed(self, doc) -> None:
        chunks = chunk_body(doc.title, doc.body)
        await self._db.execute(
            """INSERT INTO context_docs
                   (path, title, tags_json, type, summary, updated, links_json,
                    content_hash, indexed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
               ON CONFLICT (path) DO UPDATE SET
                   title = excluded.title, tags_json = excluded.tags_json,
                   type = excluded.type, summary = excluded.summary,
                   updated = excluded.updated, links_json = excluded.links_json,
                   content_hash = excluded.content_hash, indexed_at = excluded.indexed_at""",
            (
                doc.path, doc.title, json.dumps(doc.tags), doc.type, doc.summary,
                doc.updated,
                json.dumps(
                    [{"target": lk.target, "relation": lk.relation} for lk in doc.raw_links]
                ),
                doc.content_hash,
            ),
        )
        await self._db.execute("DELETE FROM context_chunks WHERE path = ?", (doc.path,))
        for chunk in chunks:
            await self._db.execute(
                "INSERT INTO context_chunks (path, chunk_idx, heading, content) VALUES (?, ?, ?, ?)",
                (doc.path, chunk.idx, chunk.heading, chunk.content),
            )
        await self._refresh_embeddings(doc.path, chunks)

    async def _refresh_embeddings(self, path: str, chunks) -> None:
        if self._embeddings is None:
            return
        model = self._embeddings.name
        async with self._db.execute(
            "SELECT chunk_idx, content_hash, model FROM context_embeddings WHERE path = ?",
            (path,),
        ) as cur:
            existing = {
                row["chunk_idx"]: (row["content_hash"], row["model"])
                for row in await cur.fetchall()
            }
        todo = [
            c for c in chunks
            if existing.get(c.idx) != (c.content_hash, model)
        ]
        stale = set(existing) - {c.idx for c in chunks}
        for idx in stale:
            await self._db.execute(
                "DELETE FROM context_embeddings WHERE path = ? AND chunk_idx = ?", (path, idx)
            )
        if not todo:
            return
        try:
            vectors = await self._embeddings.embed(
                [f"{c.heading}\n{c.content}" for c in todo]
            )
        except Exception as exc:
            logger.warning("embedding failed for %s (%s) — BM25 only for this doc", path, exc)
            return
        for chunk, vec in zip(todo, vectors):
            await self._db.execute(
                """INSERT INTO context_embeddings (path, chunk_idx, content_hash, model, dim, vector)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (path, chunk_idx) DO UPDATE SET
                       content_hash = excluded.content_hash, model = excluded.model,
                       dim = excluded.dim, vector = excluded.vector""",
                (path, chunk.idx, chunk.content_hash, model, len(vec),
                 np.asarray(vec, dtype=np.float32).tobytes()),
            )

    async def _remove(self, rel_path: str) -> None:
        for table in ("context_docs", "context_chunks", "context_embeddings"):
            await self._db.execute(f"DELETE FROM {table} WHERE path = ?", (rel_path,))

    async def _rebuild_links_and_graph(self) -> None:
        """Re-resolve raw wikilink targets against the current doc set; rebuild graph."""
        async with self._db.execute("SELECT path, links_json FROM context_docs") as cur:
            rows = await cur.fetchall()
        resolver = LinkResolver([row["path"] for row in rows])

        graph = nx.DiGraph()
        for row in rows:
            graph.add_node(row["path"])
        for row in rows:
            for link in json.loads(row["links_json"]):
                resolved, ok = resolver.resolve(link["target"])
                if ok:
                    graph.add_edge(row["path"], resolved, relation=link.get("relation"))
        self.graph = graph

    # -- queries used by the librarian/API ----------------------------------------

    def backlinks(self, path: str) -> list[str]:
        if path not in self.graph:
            return []
        return sorted(self.graph.predecessors(path))

    def neighbors(self, path: str, depth: int = 1) -> list[str]:
        if path not in self.graph:
            return []
        undirected = self.graph.to_undirected(as_view=True)
        found = nx.single_source_shortest_path_length(undirected, path, cutoff=depth)
        return sorted(p for p in found if p != path)

    def graph_json(self) -> dict:
        return {
            "nodes": [{"id": n} for n in self.graph.nodes],
            "edges": [
                {"source": u, "target": v, "relation": d.get("relation")}
                for u, v, d in self.graph.edges(data=True)
            ],
        }

    # -- watcher -------------------------------------------------------------------

    def start_watcher(self) -> None:
        self._watch_task = asyncio.create_task(self._watch(), name="vault-watcher")

    async def stop_watcher(self) -> None:
        if self._watch_task is not None:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass
            self._watch_task = None

    async def _watch(self) -> None:
        self.store.root.mkdir(parents=True, exist_ok=True)
        logger.info("watching vault %s", self.store.root)
        try:
            async for changes in watchfiles.awatch(self.store.root, step=200):
                touched = {
                    Path(p) for _, p in changes if p.endswith(".md")
                }
                for abs_path in touched:
                    try:
                        rel = abs_path.relative_to(self.store.root.resolve()).as_posix()
                    except ValueError:
                        rel = abs_path.relative_to(self.store.root).as_posix()
                    try:
                        await self.index_file(rel)
                        logger.info("reindexed %s (external change)", rel)
                    except Exception:
                        logger.exception("failed to reindex %s", rel)
        except asyncio.CancelledError:
            raise
