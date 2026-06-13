"""Platform-provided tools for agent modules: the librarian as a Claude toolset.

Built per run around the module's ScopedLibrarian, so manifest read/write scopes
hold inside agent loops too. Tool failures return "ERROR: ..." strings rather than
raising, so the model can adapt mid-loop.
"""

import json

from anthropic import beta_async_tool


def librarian_tools(librarian) -> list:
    """Build the standard vault toolset around a (scoped) librarian."""

    @beta_async_tool
    async def search_context(query: str, k: int = 5) -> str:
        """Search the user's personal knowledge vault for relevant documents.

        Call this when you need personal context: the user's preferences, people,
        projects, or logs. Returns matching documents with paths, summaries, and
        matched snippets — use read_context_doc to fetch a full document.

        Args:
            query: Natural-language search query.
            k: Number of documents to return (1-10).
        """
        try:
            hits = await librarian.ask(query, k=max(1, min(int(k), 10)))
        except Exception as exc:
            return f"ERROR: {exc}"
        return json.dumps(
            [
                {
                    "path": h.doc.path,
                    "title": h.doc.title,
                    "summary": h.doc.summary,
                    "snippets": h.snippets,
                }
                for h in hits
            ],
            indent=1,
        )

    @beta_async_tool
    async def read_context_doc(path: str) -> str:
        """Read one vault document in full (frontmatter, body, links, backlinks).

        Args:
            path: Vault-relative path, e.g. 'preferences/communication.md'.
        """
        try:
            doc = await librarian.get(path, include_body=True)
        except Exception as exc:
            return f"ERROR: {exc}"
        links = ", ".join(f"{lk.relation or 'link'}->{lk.target}" for lk in doc.links) or "none"
        return (
            f"# {doc.title}\npath: {doc.path}\ntags: {', '.join(doc.tags) or '-'}\n"
            f"links: {links}\nbacklinks: {', '.join(doc.backlinks) or 'none'}\n\n{doc.body}"
        )

    @beta_async_tool
    async def append_context(path: str, text: str) -> str:
        """Append markdown to a vault document (creates it if missing).

        Only paths inside this module's declared write scope are allowed.

        Args:
            path: Vault-relative path, e.g. 'logs/notes.md'.
            text: Markdown to append.
        """
        try:
            doc = await librarian.append(path, text)
        except Exception as exc:
            return f"ERROR: {exc}"
        return f"OK: appended to {doc.path}"

    return [search_context, read_context_doc, append_context]
