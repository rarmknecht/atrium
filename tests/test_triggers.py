import asyncio
import shutil
from pathlib import Path

import httpx
import pytest

from atrium.api.app import create_app
from atrium.config import Settings

REPO_MODULES = Path(__file__).parent.parent / "modules"


def _settings(tmp_path: Path) -> Settings:
    modules = tmp_path / "modules"
    if not modules.exists():
        modules.mkdir()
        shutil.copytree(REPO_MODULES / "heartbeat", modules / "heartbeat")
    return Settings(vault_path=tmp_path / "vault", data_dir=tmp_path / "data", modules_path=modules)


@pytest.fixture
async def app_client(tmp_path):
    app = create_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield app, c


async def _runs(client: httpx.AsyncClient, module_id: str = "heartbeat") -> list[dict]:
    return (await client.get(f"/api/modules/{module_id}/runs")).json()


# -- validation ---------------------------------------------------------------


async def test_create_rejects_unknown_module(app_client):
    _, client = app_client
    resp = await client.post(
        "/api/triggers", json={"module_id": "nope", "type": "schedule", "config": {"cron": "* * * * *"}}
    )
    assert resp.status_code == 404


async def test_create_rejects_bad_schedule_config(app_client):
    _, client = app_client
    for config in [{}, {"cron": "* * * * *", "interval_seconds": 5}, {"cron": "not a cron"}]:
        resp = await client.post(
            "/api/triggers", json={"module_id": "heartbeat", "type": "schedule", "config": config}
        )
        assert resp.status_code == 422, config


async def test_create_rejects_manual_trigger(app_client):
    _, client = app_client
    resp = await client.post("/api/triggers", json={"module_id": "heartbeat", "type": "manual"})
    assert resp.status_code == 422


# -- schedule -----------------------------------------------------------------


async def test_interval_schedule_fires_repeatedly(app_client):
    _, client = app_client
    resp = await client.post(
        "/api/triggers",
        json={"module_id": "heartbeat", "type": "schedule", "config": {"interval_seconds": 0.15}},
    )
    assert resp.status_code == 201
    trigger = resp.json()
    assert trigger["live"]["registered"] is True
    assert trigger["live"]["next_fire_time"] is not None

    await asyncio.sleep(0.55)
    runs = await _runs(client)
    fired = [r for r in runs if r["trigger_type"] == "schedule" and r["status"] == "ok"]
    assert len(fired) >= 2
    assert all(r["trigger_id"] == trigger["id"] for r in fired)


async def test_schedule_rebuilt_from_db_on_restart(tmp_path):
    """Triggers live in the DB; a fresh app over the same DB must re-register them."""
    settings = _settings(tmp_path)

    app1 = create_app(settings)
    async with app1.router.lifespan_context(app1):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app1), base_url="http://test"
        ) as c1:
            resp = await c1.post(
                "/api/triggers",
                json={
                    "module_id": "heartbeat",
                    "type": "schedule",
                    "config": {"interval_seconds": 0.15},
                },
            )
            trigger_id = resp.json()["id"]

    # "restart": brand-new app instance, same settings/db
    app2 = create_app(settings)
    async with app2.router.lifespan_context(app2):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app2), base_url="http://test"
        ) as c2:
            triggers = (await c2.get("/api/triggers")).json()
            assert triggers[0]["id"] == trigger_id
            assert triggers[0]["live"]["registered"] is True
            before = len(await _runs(c2))
            await asyncio.sleep(0.4)
            assert len(await _runs(c2)) > before  # it fires again after restart


# -- continuous ---------------------------------------------------------------


async def test_continuous_loops_and_pauses(app_client):
    _, client = app_client
    resp = await client.post(
        "/api/triggers",
        json={"module_id": "heartbeat", "type": "continuous", "config": {"sleep_seconds": 0.05}},
    )
    trigger = resp.json()
    assert trigger["live"]["registered"] is True

    await asyncio.sleep(0.4)
    count_running = len(await _runs(client))
    assert count_running >= 3

    # pause: loop stops
    resp = await client.put(f"/api/triggers/{trigger['id']}", json={"enabled": False})
    assert resp.json()["live"]["registered"] is False
    await asyncio.sleep(0.2)
    count_paused = len(await _runs(client))
    await asyncio.sleep(0.3)
    assert len(await _runs(client)) == count_paused  # no new runs while paused

    # resume: loop starts again
    await client.put(f"/api/triggers/{trigger['id']}", json={"enabled": True})
    await asyncio.sleep(0.3)
    assert len(await _runs(client)) > count_paused


async def test_continuous_survives_errors_with_backoff(app_client):
    """Module fails every run; the loop must keep going but slow down (backoff)."""
    _, client = app_client
    await client.put("/api/modules/heartbeat/config", json={"fail_every": 1})
    resp = await client.post(
        "/api/triggers",
        json={
            "module_id": "heartbeat",
            "type": "continuous",
            "config": {"sleep_seconds": 0.05, "max_backoff_seconds": 10},
        },
    )
    trigger = resp.json()

    await asyncio.sleep(0.8)
    runs = await _runs(client)
    errors = [r for r in runs if r["status"] == "error"]
    assert len(errors) >= 2  # still firing despite errors
    # backoff: with 0.05s sleep doubling per error, 0.8s admits far fewer runs
    # than the ~16 a flat sleep would allow
    assert len(runs) <= 6
    assert trigger["id"] in {r["trigger_id"] for r in errors}
    # engine still registers the loop as live
    t = next(t for t in (await client.get("/api/triggers")).json() if t["id"] == trigger["id"])
    assert t["live"]["registered"] is True


# -- webhook --------------------------------------------------------------------


async def test_webhook_roundtrip(app_client):
    _, client = app_client
    resp = await client.post("/api/triggers", json={"module_id": "heartbeat", "type": "webhook"})
    trigger = resp.json()
    token = trigger["token"]
    assert token

    resp = await client.post(
        f"/api/hooks/heartbeat/{token}?source=test",
        json={"event": "ping", "value": 42},
        headers={"X-Custom": "yes", "Authorization": "Bearer secret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"

    run = (await _runs(client))[0]
    assert run["trigger_type"] == "webhook"
    import json

    data = json.loads(run["data_json"])
    assert data["body"] == {"event": "ping", "value": 42}
    assert data["query"] == {"source": "test"}


async def test_webhook_bad_token_404s(app_client):
    _, client = app_client
    await client.post("/api/triggers", json={"module_id": "heartbeat", "type": "webhook"})
    resp = await client.post("/api/hooks/heartbeat/wrong-token", json={})
    assert resp.status_code == 404
    assert await _runs(client) == []


async def test_webhook_disabled_trigger_404s(app_client):
    _, client = app_client
    trigger = (
        await client.post("/api/triggers", json={"module_id": "heartbeat", "type": "webhook"})
    ).json()
    await client.put(f"/api/triggers/{trigger['id']}", json={"enabled": False})
    resp = await client.post(f"/api/hooks/heartbeat/{trigger['token']}", json={})
    assert resp.status_code == 404


# -- delete ---------------------------------------------------------------------


async def test_delete_trigger_stops_it(app_client):
    _, client = app_client
    trigger = (
        await client.post(
            "/api/triggers",
            json={"module_id": "heartbeat", "type": "continuous", "config": {"sleep_seconds": 0.05}},
        )
    ).json()
    await asyncio.sleep(0.15)
    assert (await client.delete(f"/api/triggers/{trigger['id']}")).status_code == 204
    count = len(await _runs(client))
    await asyncio.sleep(0.25)
    assert len(await _runs(client)) == count
    assert (await client.get("/api/triggers")).json() == []
