import asyncio
import shutil
from pathlib import Path
from textwrap import dedent

import httpx
import pytest

from atrium.api.app import create_app
from atrium.config import Settings
from atrium.context.vault import LinkResolver, chunk_body, parse_markdown

REPO_ROOT = Path(__file__).parent.parent

# -- unit: parser ---------------------------------------------------------------


def test_parse_frontmatter_links_and_relations():
    text = dedent("""\
        ---
        title: Jane Doe
        tags: [people, work]
        type: person
        summary: Colleague on the platform team.
        ---
        # Jane Doe

        Works with [[Bob Smith]] on [[projects/atrium|the platform]].

        - manages [[Carol]]
        - works_on [[projects/atrium]]
    """)
    doc = parse_markdown("people/jane_doe.md", text)
    assert doc.title == "Jane Doe"
    assert doc.tags == ["people", "work"]
    assert doc.type == "person"
    assert doc.summary == "Colleague on the platform team."
    by_target = {(lk.target, lk.relation) for lk in doc.raw_links}
    assert ("Bob Smith", None) in by_target
    assert ("projects/atrium", None) in by_target
    assert ("Carol", "manages") in by_target
    assert ("projects/atrium", "works_on") in by_target


def test_parse_summary_falls_back_to_first_paragraph():
    doc = parse_markdown("x.md", "# Heading\n\nFirst real paragraph here.\n\nSecond.")
    assert doc.summary == "First real paragraph here."


def test_chunking_splits_on_headings_and_size():
    body = "intro\n\n## A\n" + ("word " * 200) + "\n\n## B\nshort"
    chunks = chunk_body("Doc", body)
    headings = [c.heading for c in chunks]
    assert "Doc" in headings and "A" in headings and "B" in headings
    assert all(len(c.content) <= 1800 for c in chunks)


def test_link_resolver_path_and_stem():
    r = LinkResolver(["people/jane_doe.md", "projects/atrium.md"])
    assert r.resolve("projects/atrium") == ("projects/atrium.md", True)
    assert r.resolve("Jane_Doe") == ("people/jane_doe.md", True)
    assert r.resolve("missing") == ("missing", False)


# -- app fixture ------------------------------------------------------------------


@pytest.fixture
async def app_client(tmp_path):
    vault = tmp_path / "vault"
    shutil.copytree(REPO_ROOT / "vault", vault)
    modules = tmp_path / "modules"
    modules.mkdir()
    _write_vault_writer(modules)

    settings = Settings(
        vault_path=vault,
        data_dir=tmp_path / "data",
        modules_path=modules,
        embeddings_provider="off",
        watch_vault=True,
        anthropic_api_key=None,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield app, c


def _write_vault_writer(modules: Path) -> None:
    d = modules / "vault_writer"
    d.mkdir()
    (d / "module.toml").write_text(
        dedent("""\
        [module]
        id = "vault_writer"
        name = "Vault Writer"
        [module.context]
        read = ["logs/", "preferences/"]
        write = ["logs/"]
        """),
        encoding="utf-8",
    )
    (d / "__init__.py").write_text(
        dedent("""\
        from pydantic import BaseModel
        from atrium.core.module import Module, ModuleContext
        from atrium.models import RunResult

        class Config(BaseModel):
            path: str = "logs/test_note.md"

        class VaultWriter(Module):
            ConfigModel = Config

            async def run(self, ctx: ModuleContext) -> RunResult:
                doc = await ctx.librarian.append(ctx.config.path, "- note from module")
                hits = await ctx.librarian.ask("preferences", k=3)
                return RunResult(
                    status="ok",
                    summary=f"wrote {doc.path}",
                    data={"hit_paths": [h.doc.path for h in hits]},
                )
        """),
        encoding="utf-8",
    )


# -- API: tree / doc CRUD / graph ---------------------------------------------------


async def test_tree_lists_seed_docs(app_client):
    _, client = app_client
    tree = (await client.get("/api/context/tree")).json()
    paths = {d["path"] for d in tree}
    assert "projects/atrium.md" in paths
    assert "preferences/tooling.md" in paths


async def test_doc_roundtrip_file_first(app_client):
    app, client = app_client
    resp = await client.put(
        "/api/context/doc",
        json={
            "path": "people/jane.md",
            "frontmatter": {"title": "Jane", "tags": ["people"], "summary": "A colleague."},
            "body": "# Jane\n\nWorks on [[atrium]].",
        },
    )
    assert resp.status_code == 200
    # file-first: the markdown exists on disk
    vault_root = app.state.indexer.store.root
    assert (vault_root / "people" / "jane.md").is_file()

    doc = (await client.get("/api/context/doc", params={"path": "people/jane.md"})).json()
    assert doc["title"] == "Jane"
    assert any(lk["target"] == "projects/atrium.md" and lk["resolved"] for lk in doc["links"])

    # backlink shows up on the target
    atrium_doc = (
        await client.get("/api/context/doc", params={"path": "projects/atrium.md"})
    ).json()
    assert "people/jane.md" in atrium_doc["backlinks"]


async def test_doc_path_traversal_rejected(app_client):
    _, client = app_client
    resp = await client.put(
        "/api/context/doc", json={"path": "../escape.md", "frontmatter": {}, "body": "x"}
    )
    assert resp.status_code == 422


async def test_delete_doc_removes_from_disk_and_index(app_client):
    app, client = app_client
    await client.put(
        "/api/context/doc", json={"path": "logs/tmp.md", "frontmatter": {}, "body": "temp"}
    )
    assert (await client.delete("/api/context/doc", params={"path": "logs/tmp.md"})).status_code == 204
    assert not (app.state.indexer.store.root / "logs" / "tmp.md").exists()
    assert (await client.get("/api/context/doc", params={"path": "logs/tmp.md"})).status_code == 404


async def test_graph_has_typed_edges(app_client):
    _, client = app_client
    graph = (await client.get("/api/context/graph")).json()
    edges = {(e["source"], e["target"]): e["relation"] for e in graph["edges"]}
    assert edges.get(("projects/atrium.md", "preferences/tooling.md")) == "built_with"
    assert ("logs/2026-06-12.md", "projects/atrium.md") in edges


# -- search ---------------------------------------------------------------------------


async def test_ask_ranks_relevant_doc_first(app_client):
    _, client = app_client
    hits = (
        await client.post("/api/context/ask", json={"query": "python uv tooling", "k": 3})
    ).json()
    assert hits
    assert hits[0]["doc"]["path"] == "preferences/tooling.md"
    assert hits[0]["snippets"]


async def test_route_without_api_key_falls_back_to_stage1(app_client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _, client = app_client
    bundle = (
        await client.post("/api/context/route", json={"task": "write a daily brief", "k": 2})
    ).json()
    assert bundle["routed"] is False
    assert bundle["docs"]
    assert all(d["body"] is not None for d in bundle["docs"])


async def test_external_edit_reflected_in_search(app_client):
    """Exit criterion: edit a file with any external tool; search sees it within seconds."""
    app, client = app_client
    target = app.state.indexer.store.root / "projects" / "zebra_quest.md"
    target.parent.mkdir(exist_ok=True)
    target.write_text(
        "---\ntitle: Zebra Quest\nsummary: Tracking the elusive zebra migration project.\n---\n"
        "# Zebra Quest\n\nzebra migration telemetry dashboards.\n",
        encoding="utf-8",
    )
    for _ in range(50):  # up to ~5s for the watcher to pick it up
        hits = (
            await client.post("/api/context/ask", json={"query": "zebra migration", "k": 3})
        ).json()
        if hits and hits[0]["doc"]["path"] == "projects/zebra_quest.md":
            break
        await asyncio.sleep(0.1)
    else:
        pytest.fail("external edit not reflected in search within 5s")


async def test_reindex_endpoint(app_client):
    _, client = app_client
    stats = (await client.post("/api/context/reindex")).json()
    assert stats["docs"] >= 4
    assert stats["removed"] == 0


# -- module scope enforcement -----------------------------------------------------------


async def test_module_write_in_scope_succeeds(app_client):
    _, client = app_client
    run = (await client.post("/api/modules/vault_writer/run")).json()
    assert run["status"] == "ok", run["summary"]
    doc = (await client.get("/api/context/doc", params={"path": "logs/test_note.md"})).json()
    assert "note from module" in doc["body"]


async def test_module_write_out_of_scope_fails(app_client):
    _, client = app_client
    await client.put(
        "/api/modules/vault_writer/config", json={"path": "people/sneaky.md"}
    )
    run = (await client.post("/api/modules/vault_writer/run")).json()
    assert run["status"] == "error"
    assert "may not write" in run["summary"]
    # nothing written
    resp = await client.get("/api/context/doc", params={"path": "people/sneaky.md"})
    assert resp.status_code == 404


async def test_module_read_scope_filters_search(app_client):
    _, client = app_client
    run = (await client.post("/api/modules/vault_writer/run")).json()
    assert run["status"] == "ok"
    import json

    hit_paths = json.loads(run["data_json"])["hit_paths"]
    assert hit_paths, "expected in-scope search hits"
    assert all(p.startswith(("logs/", "preferences/")) for p in hit_paths)
