"""The Librarian: routes a task/query to the most relevant vault documents.

Stage 1 (cheap, every query): hybrid retrieval — FTS5 BM25 + embedding cosine,
fused with Reciprocal Rank Fusion, aggregated from chunks to parent docs.

Stage 2 (agent queries): one Claude call over the "card catalog" (every doc's
summary line) plus the stage-1 hits; returns ranked doc paths, assembled into a
ContextBundle with 1-hop neighbor summaries. Falls back to stage 1 when no API
key is configured.
"""

import json
import logging
import re

import aiosqlite
import numpy as np
from pydantic import BaseModel, Field

from atrium.context.embeddings import EmbeddingProvider
from atrium.context.indexer import VaultIndexer
from atrium.models.context import ContextBundle, ContextDoc, DocLink, SearchHit
from atrium.models.manifest import ManifestContext

logger = logging.getLogger(__name__)

RRF_K = 60
CATALOG_CAP = 500


def _fts_query(query: str) -> str:
    """User text -> safe FTS5 OR-of-terms query."""
    terms = re.findall(r"[\w]+", query.lower())
    return " OR ".join(f'"{t}"' for t in terms[:32])


def _scope_ok(path: str, prefixes: list[str] | None) -> bool:
    if prefixes is None:
        return True
    return any(path.startswith(p) for p in prefixes)


class RouteSelection(BaseModel):
    """Structured output of the stage-2 router call."""

    paths: list[str] = Field(description="Vault doc paths, most relevant first")
    include_neighbors: bool = Field(
        default=True, description="Whether 1-hop linked docs add useful context"
    )


class Librarian:
    def __init__(
        self,
        db: aiosqlite.Connection,
        indexer: VaultIndexer,
        embeddings: EmbeddingProvider | None,
        router_model: str = "claude-opus-4-8",
        anthropic_configured: bool = False,
    ):
        self._db = db
        self._indexer = indexer
        self._embeddings = embeddings
        self._router_model = router_model
        self._anthropic_configured = anthropic_configured

    # -- doc access -----------------------------------------------------------

    async def get(self, path: str, include_body: bool = True) -> ContextDoc:
        path = self._indexer.store.normalize(path)
        async with self._db.execute(
            "SELECT * FROM context_docs WHERE path = ?", (path,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise FileNotFoundError(f"no vault document at {path!r}")
        return self._doc_from_row(row, include_body=include_body)

    async def list_docs(self) -> list[ContextDoc]:
        async with self._db.execute(
            "SELECT * FROM context_docs ORDER BY path"
        ) as cur:
            return [self._doc_from_row(r, include_body=False) for r in await cur.fetchall()]

    def _doc_from_row(self, row: aiosqlite.Row, include_body: bool) -> ContextDoc:
        links = []
        for link in json.loads(row["links_json"]):
            resolved, ok = self._resolver().resolve(link["target"])
            links.append(DocLink(target=resolved, relation=link.get("relation"), resolved=ok))
        body = None
        frontmatter = None
        if include_body:
            parsed = self._indexer.store.read(row["path"])
            body, frontmatter = parsed.body, parsed.frontmatter
        return ContextDoc(
            path=row["path"],
            title=row["title"],
            tags=json.loads(row["tags_json"]),
            type=row["type"],
            summary=row["summary"],
            updated=row["updated"],
            links=links,
            backlinks=self._indexer.backlinks(row["path"]),
            body=body,
            frontmatter=frontmatter,
        )

    def _resolver(self):
        from atrium.context.vault import LinkResolver

        return LinkResolver(list(self._indexer.graph.nodes))

    # -- stage 1: hybrid search --------------------------------------------------

    async def ask(
        self, query: str, k: int = 5, scope: list[str] | None = None
    ) -> list[SearchHit]:
        lexical = await self._bm25(query, limit=k * 6)
        semantic = await self._vector(query, limit=k * 6)

        # RRF over chunk lists -> doc scores; keep best snippets per doc
        doc_scores: dict[str, float] = {}
        doc_snippets: dict[str, list[str]] = {}
        for ranked in (lexical, semantic):
            for position, (path, snippet) in enumerate(ranked):
                if not _scope_ok(path, scope):
                    continue
                doc_scores[path] = doc_scores.get(path, 0.0) + 1.0 / (RRF_K + position + 1)
                snippets = doc_snippets.setdefault(path, [])
                if snippet and snippet not in snippets and len(snippets) < 3:
                    snippets.append(snippet)

        top = sorted(doc_scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
        hits = []
        for path, score in top:
            try:
                doc = await self.get(path, include_body=False)
            except FileNotFoundError:
                continue
            hits.append(SearchHit(doc=doc, score=round(score, 6), snippets=doc_snippets[path]))
        return hits

    async def _bm25(self, query: str, limit: int) -> list[tuple[str, str]]:
        fts = _fts_query(query)
        if not fts:
            return []
        async with self._db.execute(
            """SELECT path, snippet(context_chunks, 3, '', '', ' … ', 24) AS snip
               FROM context_chunks WHERE context_chunks MATCH ?
               ORDER BY rank LIMIT ?""",
            (fts, limit),
        ) as cur:
            return [(row["path"], row["snip"]) for row in await cur.fetchall()]

    async def _vector(self, query: str, limit: int) -> list[tuple[str, str]]:
        if self._embeddings is None:
            return []
        async with self._db.execute(
            "SELECT path, chunk_idx, vector, dim FROM context_embeddings WHERE model = ?",
            (self._embeddings.name,),
        ) as cur:
            rows = await cur.fetchall()
        if not rows:
            return []
        try:
            q = await self._embeddings.embed_query(query)
        except Exception as exc:
            logger.warning("query embedding failed (%s) — BM25 only", exc)
            return []
        matrix = np.stack(
            [np.frombuffer(row["vector"], dtype=np.float32) for row in rows]
        )
        norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(q) or 1.0)
        scores = matrix @ q / np.where(norms == 0, 1.0, norms)
        order = np.argsort(-scores)[:limit]
        out: list[tuple[str, str]] = []
        for i in order:
            row = rows[int(i)]
            async with self._db.execute(
                "SELECT content FROM context_chunks WHERE path = ? AND chunk_idx = ?",
                (row["path"], row["chunk_idx"]),
            ) as cur:
                chunk = await cur.fetchone()
            out.append((row["path"], (chunk["content"][:160] + " …") if chunk else ""))
        return out

    # -- stage 2: LLM route ---------------------------------------------------------

    async def route(
        self, task: str, k: int = 4, scope: list[str] | None = None
    ) -> ContextBundle:
        hits = await self.ask(task, k=max(k * 2, 8), scope=scope)
        if not self._anthropic_configured:
            return await self._bundle(task, [h.doc.path for h in hits[:k]], scope, routed=False)

        docs = await self.list_docs()
        catalog = [
            {"path": d.path, "title": d.title, "summary": d.summary or ""}
            for d in docs
            if _scope_ok(d.path, scope)
        ][:CATALOG_CAP]

        try:
            selection = await self._route_llm(task, catalog, hits, k)
        except Exception as exc:
            logger.warning("router LLM call failed (%s) — falling back to stage-1", exc)
            return await self._bundle(task, [h.doc.path for h in hits[:k]], scope, routed=False)

        valid = [p for p in selection.paths if _scope_ok(p, scope)][:k]
        return await self._bundle(
            task, valid, scope, routed=True, neighbors=selection.include_neighbors
        )

    async def _route_llm(self, task: str, catalog: list[dict], hits, k: int) -> RouteSelection:
        import anthropic

        client = anthropic.AsyncAnthropic()
        hit_lines = [
            {"path": h.doc.path, "snippets": h.snippets} for h in hits
        ]
        response = await client.messages.parse(
            model=self._router_model,
            max_tokens=2048,
            system=(
                "You are the librarian of a personal markdown knowledge vault. "
                "Given a task, select the documents whose content is most useful for "
                f"completing it. Choose at most {k}. Prefer precision over coverage; "
                "select nothing that is merely topically adjacent."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Task:\n{task}\n\n"
                    f"Card catalog (every document):\n{json.dumps(catalog, indent=1)}\n\n"
                    f"Search hits with matched snippets:\n{json.dumps(hit_lines, indent=1)}"
                ),
            }],
            output_format=RouteSelection,
        )
        parsed = response.parsed_output
        if parsed is None:
            raise ValueError("router returned no parseable selection")
        return parsed

    async def _bundle(
        self,
        task: str,
        paths: list[str],
        scope: list[str] | None,
        routed: bool,
        neighbors: bool = True,
    ) -> ContextBundle:
        bundle_docs: list[ContextDoc] = []
        for path in paths:
            try:
                bundle_docs.append(await self.get(path, include_body=True))
            except (FileNotFoundError, ValueError):
                continue

        neighbor_docs: list[ContextDoc] = []
        if neighbors:
            chosen = {d.path for d in bundle_docs}
            seen = set(chosen)
            for doc in bundle_docs:
                for n in self._indexer.neighbors(doc.path, depth=1):
                    if n not in seen and _scope_ok(n, scope):
                        seen.add(n)
                        try:
                            neighbor_docs.append(await self.get(n, include_body=False))
                        except FileNotFoundError:
                            continue
        return ContextBundle(
            query=task, docs=bundle_docs, neighbor_summaries=neighbor_docs[:10], routed=routed
        )

    # -- writes (file-first; index follows synchronously) -----------------------------

    async def put(self, path: str, fm: dict | None, body: str) -> ContextDoc:
        parsed = self._indexer.store.write(path, fm, body)
        await self._indexer.index_file(parsed.path)
        return await self.get(parsed.path)

    async def append(self, path: str, text: str) -> ContextDoc:
        parsed = self._indexer.store.append(path, text)
        await self._indexer.index_file(parsed.path)
        return await self.get(parsed.path)

    async def delete(self, path: str) -> None:
        normalized = self._indexer.store.normalize(path)
        self._indexer.store.delete(normalized)
        await self._indexer.index_file(normalized)


class ScopeViolation(PermissionError):
    pass


class ScopedLibrarian:
    """The LibrarianClient a module sees — manifest read/write prefixes enforced.

    Empty read scope means read-everything; write scope is always explicit.
    """

    def __init__(self, librarian: Librarian, module_id: str, scope: ManifestContext):
        self._librarian = librarian
        self._module_id = module_id
        self._read = scope.read or None     # None -> unrestricted read
        self._write = scope.write           # [] -> no writes allowed

    def _check_read(self, path: str) -> None:
        if not _scope_ok(path, self._read):
            raise ScopeViolation(
                f"module {self._module_id!r} may not read {path!r} (read scope: {self._read})"
            )

    def _check_write(self, path: str) -> None:
        if not _scope_ok(path, self._write):  # empty scope -> no writes allowed
            raise ScopeViolation(
                f"module {self._module_id!r} may not write {path!r} (write scope: {self._write})"
            )

    async def ask(self, query: str, k: int = 5) -> list[SearchHit]:
        return await self._librarian.ask(query, k=k, scope=self._read)

    async def list_docs(self) -> list[ContextDoc]:
        docs = await self._librarian.list_docs()
        return [d for d in docs if _scope_ok(d.path, self._read)]

    async def route(self, task: str, k: int = 4) -> ContextBundle:
        return await self._librarian.route(task, k=k, scope=self._read)

    async def get(self, path: str, include_body: bool = True) -> ContextDoc:
        self._check_read(path)
        return await self._librarian.get(path, include_body=include_body)

    async def neighbors(self, path: str, depth: int = 1) -> list[str]:
        self._check_read(path)
        return [
            p for p in self._librarian._indexer.neighbors(path, depth)
            if _scope_ok(p, self._read)
        ]

    async def put(self, path: str, fm: dict | None, body: str) -> ContextDoc:
        self._check_write(self._librarian._indexer.store.normalize(path))
        return await self._librarian.put(path, fm, body)

    async def append(self, path: str, text: str) -> ContextDoc:
        self._check_write(self._librarian._indexer.store.normalize(path))
        return await self._librarian.append(path, text)
