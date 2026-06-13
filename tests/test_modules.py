from pathlib import Path
from textwrap import dedent

import httpx
import pytest

from atrium.api.app import create_app
from atrium.config import Settings

REPO_MODULES = Path(__file__).parent.parent / "modules"


def _write_module(root: Path, module_id: str, body: str, manifest_extra: str = "") -> None:
    d = root / module_id
    d.mkdir(parents=True)
    (d / "module.toml").write_text(
        dedent(f"""
        [module]
        id = "{module_id}"
        name = "{module_id}"
        {manifest_extra}
        """),
        encoding="utf-8",
    )
    (d / "__init__.py").write_text(dedent(body), encoding="utf-8")


CRASHER = """
    from atrium.core.module import Module, ModuleContext
    from atrium.models import RunResult

    class Crasher(Module):
        async def run(self, ctx: ModuleContext) -> RunResult:
            ctx.logger.info("about to crash")
            raise RuntimeError("boom")
"""

SLOWPOKE = """
    import asyncio
    from atrium.core.module import Module, ModuleContext
    from atrium.models import RunResult

    class Slowpoke(Module):
        async def run(self, ctx: ModuleContext) -> RunResult:
            await asyncio.sleep(60)
            return RunResult(summary="never reached")
"""

BROKEN_IMPORT = """
    import does_not_exist_anywhere
"""


@pytest.fixture
async def client(tmp_path):
    """App over a temp modules dir containing hello_world (copied refs) + fixtures."""
    modules = tmp_path / "modules"
    modules.mkdir()
    # real reference module straight from the repo
    import shutil

    shutil.copytree(REPO_MODULES / "hello_world", modules / "hello_world")
    _write_module(modules, "crasher", CRASHER)
    _write_module(modules, "slowpoke", SLOWPOKE, manifest_extra="timeout_seconds = 0.2")
    _write_module(modules, "broken_import", BROKEN_IMPORT)

    settings = Settings(
        vault_path=tmp_path / "vault",
        data_dir=tmp_path / "data",
        modules_path=modules,
        anthropic_api_key=None,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c


async def test_registry_lists_modules_including_broken(client):
    resp = await client.get("/api/modules")
    assert resp.status_code == 200
    by_id = {m["id"]: m for m in resp.json()}
    assert by_id["hello_world"]["status"] == "ready"
    assert by_id["crasher"]["status"] == "ready"
    assert by_id["broken_import"]["status"] == "error"
    assert "import failed" in by_id["broken_import"]["error"]


async def test_module_detail_exposes_config_schema(client):
    resp = await client.get("/api/modules/hello_world")
    body = resp.json()
    assert body["config_schema"]["properties"]["greeting"]["default"] == "Hello"
    assert body["config"]["greeting"] == "Hello"  # defaults materialized


async def test_config_validation_rejects_bad_field(client):
    resp = await client.put(
        "/api/modules/hello_world/config", json={"sleep_seconds": "not a number"}
    )
    assert resp.status_code == 422
    resp = await client.put(
        "/api/modules/hello_world/config", json={"greeting": "Hej", "sleep_seconds": 0}
    )
    assert resp.status_code == 200
    assert resp.json()["config"]["greeting"] == "Hej"


async def test_manual_run_executes_and_records_history(client):
    await client.put("/api/modules/hello_world/config", json={"sleep_seconds": 0})
    resp = await client.post("/api/modules/hello_world/run")
    run = resp.json()
    assert run["status"] == "ok"
    assert run["summary"] == "Hello, world!"
    assert "greeting composed" in run["logs"]
    assert run["finished_at"] is not None

    history = (await client.get("/api/modules/hello_world/runs")).json()
    assert len(history) == 1
    assert history[0]["id"] == run["id"]
    assert history[0]["trigger_type"] == "manual"


async def test_crashing_module_records_error_and_server_survives(client):
    run = (await client.post("/api/modules/crasher/run")).json()
    assert run["status"] == "error"
    assert "boom" in run["summary"]
    assert "about to crash" in run["logs"]
    # server still healthy
    assert (await client.get("/api/health")).json()["status"] == "ok"


async def test_timeout_recorded_as_error(client):
    run = (await client.post("/api/modules/slowpoke/run")).json()
    assert run["status"] == "error"
    assert "timed out" in run["summary"]


async def test_run_on_broken_module_409s(client):
    resp = await client.post("/api/modules/broken_import/run")
    assert resp.status_code == 409


async def test_disabled_module_skips(client):
    await client.put("/api/modules/hello_world/enabled", json={"enabled": False})
    run = (await client.post("/api/modules/hello_world/run")).json()
    assert run["status"] == "skipped"
    assert "disabled" in run["summary"]
    await client.put("/api/modules/hello_world/enabled", json={"enabled": True})


async def test_state_persists_across_runs(client):
    await client.put("/api/modules/hello_world/config", json={"sleep_seconds": 0})
    r1 = (await client.post("/api/modules/hello_world/run")).json()
    r2 = (await client.post("/api/modules/hello_world/run")).json()
    import json as _json

    assert _json.loads(r1["data_json"])["count"] + 1 == _json.loads(r2["data_json"])["count"]
