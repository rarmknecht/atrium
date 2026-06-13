"""FastMCP server exposing Atrium's context vault to any MCP client (Claude Code,
Claude Desktop, …) over stdio.

Run with `atrium mcp`. It builds the same vault → indexer → librarian stack the
platform uses, so the librarian's hybrid search is available wherever you work.
Writes are unscoped here (you are the operator), unlike module runs.
"""

import json
import logging

from atrium.config import get_settings
from atrium.context.embeddings import get_provider
from atrium.context.indexer import VaultIndexer
from atrium.context.librarian import Librarian
from atrium.context.vault import VaultStore
from atrium import db

logger = logging.getLogger(__name__)


def build_server():
    from mcp.server.fastmcp import FastMCP

    settings = get_settings()
    mcp = FastMCP("atrium-context")

    state: dict = {}

    async def _ensure() -> Librarian:
        if "librarian" not in state:
            conn = await db.connect(settings.db_path)
            await db.migrate(conn)
            store = VaultStore(settings.vault_path)
            embeddings = get_provider(settings.embeddings_provider, settings.embedding_model)
            indexer = VaultIndexer(conn, store, embeddings)
            await indexer.full_scan()
            state["librarian"] = Librarian(conn, indexer, embeddings)
        return state["librarian"]

    @mcp.tool()
    async def search_context(query: str, k: int = 5) -> str:
        """Search the personal Atrium vault; returns matching docs with snippets."""
        lib = await _ensure()
        hits = await lib.ask(query, k=max(1, min(k, 15)))
        return json.dumps(
            [
                {"path": h.doc.path, "title": h.doc.title, "summary": h.doc.summary,
                 "snippets": h.snippets, "score": h.score}
                for h in hits
            ],
            indent=1,
        )

    @mcp.tool()
    async def read_context_doc(path: str) -> str:
        """Read one vault document in full (body, links, backlinks)."""
        lib = await _ensure()
        try:
            doc = await lib.get(path, include_body=True)
        except (FileNotFoundError, ValueError) as exc:
            return f"ERROR: {exc}"
        return (
            f"# {doc.title}\npath: {doc.path}\ntags: {', '.join(doc.tags) or '-'}\n"
            f"backlinks: {', '.join(doc.backlinks) or 'none'}\n\n{doc.body}"
        )

    @mcp.tool()
    async def write_context_doc(path: str, body: str, title: str = "") -> str:
        """Create or overwrite a vault document (markdown body + optional title)."""
        lib = await _ensure()
        try:
            doc = await lib.put(path, {"title": title} if title else {}, body)
        except ValueError as exc:
            return f"ERROR: {exc}"
        return f"OK: wrote {doc.path}"

    @mcp.tool()
    async def append_context_doc(path: str, text: str) -> str:
        """Append markdown to a vault document (creates it if missing)."""
        lib = await _ensure()
        try:
            doc = await lib.append(path, text)
        except ValueError as exc:
            return f"ERROR: {exc}"
        return f"OK: appended to {doc.path}"

    return mcp


def main() -> None:
    logging.basicConfig(level=logging.WARNING)  # keep stdout clean for stdio transport
    build_server().run()


if __name__ == "__main__":
    main()
