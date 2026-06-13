import json
import shutil
from pathlib import Path
from textwrap import dedent

import httpx
import pytest

from atrium.api.app import create_app
from atrium.config import Settings

REPO_ROOT = Path(__file__).parent.parent


@pytest.fixture
async def app_client(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    vault = tmp_path / "vault"
    shutil.copytree(REPO_ROOT / "vault", vault)

    modules = tmp_path / "modules"
    modules.mkdir()
    for mod in ("daily_brief", "vault_janitor"):
        shutil.copytree(REPO_ROOT / "modules" / mod, modules / mod)
    _write_usage_probe(modules)

    settings = Settings(
        vault_path=vault,
        data_dir=tmp_path / "data",
        modules_path=modules,
        embeddings_provider="off",
        watch_vault=False,
        anthropic_api_key=None,  # hermetic: never use a real key from .env/env
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield app, c


def _write_usage_probe(modules: Path) -> None:
    """Module that records fake token usage — tests the runner's usage plumbing."""
    d = modules / "usage_probe"
    d.mkdir()
    (d / "module.toml").write_text(
        '[module]\nid = "usage_probe"\nname = "Usage Probe"\n', encoding="utf-8"
    )
    (d / "__init__.py").write_text(
        dedent("""\
        from types import SimpleNamespace
        from atrium.core.module import Module, ModuleContext
        from atrium.models import RunResult

        class UsageProbe(Module):
            async def run(self, ctx: ModuleContext) -> RunResult:
                ctx.llm.add_usage(SimpleNamespace(
                    input_tokens=100,
                    output_tokens=40,
                    cache_creation_input_tokens=10,
                    cache_read_input_tokens=5,
                ))
                return RunResult(status="ok", summary="usage recorded")
        """),
        encoding="utf-8",
    )


def test_settings_reads_unprefixed_anthropic_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    assert Settings().anthropic_api_key == "sk-test-123"


# -- both proof modules coexist ----------------------------------------------------


async def test_both_modules_listed_independently(app_client):
    _, client = app_client
    mods = {m["id"]: m for m in (await client.get("/api/modules")).json()}
    assert mods["daily_brief"]["status"] == "ready"
    assert mods["daily_brief"]["kind"] == "agent"
    assert mods["vault_janitor"]["status"] == "ready"
    assert mods["vault_janitor"]["kind"] == "automation"


# -- token usage plumbing ------------------------------------------------------------


async def test_runner_records_token_usage_on_run_row(app_client):
    _, client = app_client
    run = (await client.post("/api/modules/usage_probe/run")).json()
    assert run["status"] == "ok"
    assert run["tokens_in"] == 115  # 100 input + 10 cache write + 5 cache read
    assert run["tokens_out"] == 40


# -- no API key: clean failure, not a crash -------------------------------------------


async def test_daily_brief_without_key_fails_cleanly(app_client):
    _, client = app_client
    run = (await client.post("/api/modules/daily_brief/run")).json()
    assert run["status"] == "error"
    assert "ANTHROPIC_API_KEY" in run["summary"]
    # platform unaffected
    assert (await client.get("/api/health")).json()["status"] == "ok"


# -- vault janitor (no LLM) end-to-end -------------------------------------------------


async def test_janitor_clean_vault(app_client):
    _, client = app_client
    run = (await client.post("/api/modules/vault_janitor/run")).json()
    assert run["status"] == "ok", run["summary"]
    assert json.loads(run["data_json"])["findings"] == 0
    assert run["tokens_in"] == 0  # proves no LLM involved


async def test_janitor_finds_problems(app_client):
    _, client = app_client
    # dead link + orphan + untagged, in one doc
    await client.put(
        "/api/context/doc",
        json={
            "path": "projects/derelict.md",
            "frontmatter": {"title": "Derelict"},
            "body": "Links to [[nowhere_at_all]].",
        },
    )
    # orphan with no links at all
    await client.put(
        "/api/context/doc",
        json={
            "path": "projects/island.md",
            "frontmatter": {"title": "Island", "tags": ["projects"]},
            "body": "No links here.",
        },
    )
    run = (await client.post("/api/modules/vault_janitor/run")).json()
    assert run["status"] == "warning"

    report = (await client.get("/api/reports", params={"kind": "findings"})).json()[0]
    data = json.loads(report["data_json"])
    assert {"doc": "projects/derelict.md", "target": "nowhere_at_all"} in data["dead_links"]
    assert "projects/island.md" in data["orphans"]
    assert "projects/derelict.md" in data["untagged"]
    assert "Dead links" in report["body_md"]


# -- reports API ------------------------------------------------------------------------


async def test_reports_filters(app_client):
    _, client = app_client
    await client.post("/api/modules/vault_janitor/run")

    all_reports = (await client.get("/api/reports")).json()
    assert len(all_reports) == 1

    by_module = (await client.get("/api/reports", params={"module_id": "vault_janitor"})).json()
    assert len(by_module) == 1
    assert by_module[0]["kind"] == "findings"

    none = (await client.get("/api/reports", params={"module_id": "daily_brief"})).json()
    assert none == []

    future = (await client.get("/api/reports", params={"since": "2999-01-01"})).json()
    assert future == []

    single = (await client.get(f"/api/reports/{all_reports[0]['id']}")).json()
    assert single["body_md"]
    assert (await client.get("/api/reports/nope")).status_code == 404
