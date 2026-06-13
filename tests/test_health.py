import httpx
import pytest

from atrium.api.app import create_app
from atrium.config import Settings


@pytest.fixture
async def client(tmp_path):
    settings = Settings(
        vault_path=tmp_path / "vault", data_dir=tmp_path / "data", anthropic_api_key=None
    )
    app = create_app(settings)
    # ASGITransport does not run lifespan events — enter the lifespan manually
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c


async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["schema_version"] >= 1


async def test_migrations_idempotent(tmp_path):
    from atrium import db

    conn = await db.connect(tmp_path / "x.db")
    v1 = await db.migrate(conn)
    v2 = await db.migrate(conn)
    assert v1 == v2 >= 1
    # core tables exist
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ) as cur:
        tables = {row[0] for row in await cur.fetchall()}
    assert {"module_config", "triggers", "runs", "reports", "kv_state"} <= tables
    await conn.close()
