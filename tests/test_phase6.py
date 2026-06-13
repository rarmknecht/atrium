import httpx
import pytest

from atrium import db
from atrium.api.app import create_app
from atrium.config import Settings


def _settings(tmp_path, **kw):
    return Settings(
        vault_path=tmp_path / "vault",
        data_dir=tmp_path / "data",
        modules_path=tmp_path / "modules",
        embeddings_provider="off",
        watch_vault=False,
        anthropic_api_key=None,
        **kw,
    )


async def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# -- auth ---------------------------------------------------------------------


@pytest.fixture
async def secured(tmp_path):
    (tmp_path / "modules").mkdir()
    app = create_app(_settings(tmp_path, auth_token="s3cret"))
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            yield c


async def test_health_is_public_and_advertises_auth(secured):
    r = await secured.get("/api/health")
    assert r.status_code == 200
    assert r.json()["auth_required"] is True


async def test_api_requires_token(secured):
    assert (await secured.get("/api/modules")).status_code == 401
    assert (await secured.get("/api/settings")).status_code == 401


async def test_correct_token_allows(secured):
    r = await secured.get("/api/modules", headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200


async def test_wrong_token_rejected(secured):
    r = await secured.get("/api/modules", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


async def test_webhook_path_exempt_from_bearer(secured):
    # no bearer -> not 401; unknown module/token -> 404 (hooks self-authenticate)
    r = await secured.post("/api/hooks/whatever/token", json={})
    assert r.status_code == 404


async def test_no_auth_token_means_open(tmp_path):
    (tmp_path / "modules").mkdir()
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            assert (await c.get("/api/health")).json()["auth_required"] is False
            assert (await c.get("/api/modules")).status_code == 200


# -- startup recovery ----------------------------------------------------------


async def test_orphaned_running_runs_marked_interrupted(tmp_path):
    settings = _settings(tmp_path)
    (tmp_path / "modules").mkdir()

    # simulate a process that died mid-run: a 'running' row with no task behind it
    conn = await db.connect(settings.db_path)
    await db.migrate(conn)
    await conn.execute(
        "INSERT INTO runs (id, module_id, trigger_type, status) VALUES (?, ?, ?, 'running')",
        ("orphan1", "ghost", "manual"),
    )
    await conn.commit()
    await conn.close()

    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            runs = (await c.get("/api/runs")).json()
    orphan = next(r for r in runs if r["id"] == "orphan1")
    assert orphan["status"] == "interrupted"
    assert orphan["finished_at"] is not None


# -- SPA static serving --------------------------------------------------------


@pytest.fixture
async def with_ui(tmp_path):
    (tmp_path / "modules").mkdir()
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Atrium</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('hi')", encoding="utf-8")
    app = create_app(_settings(tmp_path, web_dist=dist))
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            yield c


async def test_serves_index_at_root(with_ui):
    r = await with_ui.get("/")
    assert r.status_code == 200
    assert "Atrium" in r.text


async def test_spa_fallback_for_client_routes(with_ui):
    r = await with_ui.get("/modules/daily_brief")
    assert r.status_code == 200
    assert "Atrium" in r.text  # app shell, not a 404


async def test_static_asset_served(with_ui):
    r = await with_ui.get("/assets/app.js")
    assert r.status_code == 200
    assert "console.log" in r.text


async def test_api_still_wins_over_spa(with_ui):
    r = await with_ui.get("/api/health")
    assert r.json()["status"] == "ok"  # not the index.html shell
