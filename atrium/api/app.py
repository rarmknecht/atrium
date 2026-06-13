import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from atrium import __version__, db
from atrium.api import modules as modules_api
from atrium.config import Settings, get_settings
from atrium.core.registry import ModuleRegistry
from atrium.core.runner import ModuleRunner

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.vault_path.mkdir(parents=True, exist_ok=True)
        app.state.settings = settings
        app.state.db = await db.connect(settings.db_path)
        app.state.schema_version = await db.migrate(app.state.db)

        app.state.registry = ModuleRegistry(settings.modules_path)
        app.state.registry.scan()
        app.state.runner = ModuleRunner(app.state.db, app.state.registry)

        logger.info(
            "atrium up — vault=%s db=%s schema=v%s modules=%d",
            settings.vault_path, settings.db_path, app.state.schema_version,
            len(app.state.registry.all()),
        )
        try:
            yield
        finally:
            await app.state.db.close()

    app = FastAPI(title="Atrium", version=__version__, lifespan=lifespan)
    app.include_router(modules_api.router)

    @app.get("/api/health")
    async def health() -> dict:
        async with app.state.db.execute("SELECT 1") as cur:
            await cur.fetchone()
        return {
            "status": "ok",
            "version": __version__,
            "schema_version": app.state.schema_version,
            "vault": str(settings.vault_path),
        }

    return app
