import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

import os

from atrium import __version__, db
from atrium.api import context as context_api
from atrium.api import hooks as hooks_api
from atrium.api import modules as modules_api
from atrium.api import reports as reports_api
from atrium.api import triggers as triggers_api
from atrium.config import Settings, get_settings
from atrium.context.embeddings import get_provider
from atrium.context.indexer import VaultIndexer
from atrium.context.librarian import Librarian
from atrium.context.vault import VaultStore
from atrium.core.registry import ModuleRegistry
from atrium.core.runner import ModuleRunner
from atrium.core.triggers import TriggerEngine

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.vault_path.mkdir(parents=True, exist_ok=True)
        app.state.settings = settings
        app.state.db = await db.connect(settings.db_path)
        app.state.schema_version = await db.migrate(app.state.db)

        # context layer: vault -> indexer -> librarian
        store = VaultStore(settings.vault_path)
        embeddings = get_provider(settings.embeddings_provider, settings.embedding_model)
        app.state.indexer = VaultIndexer(app.state.db, store, embeddings)
        await app.state.indexer.full_scan()
        if settings.watch_vault:
            app.state.indexer.start_watcher()
        # .env-sourced key must reach the process env for the anthropic SDK
        if settings.anthropic_api_key and not os.environ.get("ANTHROPIC_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
        anthropic_configured = bool(
            settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
        )
        app.state.librarian = Librarian(
            app.state.db,
            app.state.indexer,
            embeddings,
            router_model=settings.router_model,
            anthropic_configured=anthropic_configured,
        )

        app.state.registry = ModuleRegistry(settings.modules_path)
        app.state.registry.scan()
        app.state.runner = ModuleRunner(
            app.state.db,
            app.state.registry,
            librarian=app.state.librarian,
            llm_model=settings.llm_model,
            anthropic_configured=anthropic_configured,
        )
        app.state.triggers = TriggerEngine(app.state.db, app.state.registry, app.state.runner)
        await app.state.triggers.start()

        logger.info(
            "atrium up — vault=%s db=%s schema=v%s modules=%d",
            settings.vault_path, settings.db_path, app.state.schema_version,
            len(app.state.registry.all()),
        )
        try:
            yield
        finally:
            await app.state.indexer.stop_watcher()
            await app.state.triggers.stop()
            await app.state.db.close()

    app = FastAPI(title="Atrium", version=__version__, lifespan=lifespan)
    app.include_router(modules_api.router)
    app.include_router(triggers_api.router)
    app.include_router(hooks_api.router)
    app.include_router(context_api.router)
    app.include_router(reports_api.router)

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
