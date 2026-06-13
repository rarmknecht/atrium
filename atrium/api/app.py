import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from atrium import __version__, db
from atrium.api.auth import BearerAuthMiddleware
from atrium.api import context as context_api
from atrium.api import hooks as hooks_api
from atrium.api import meta as meta_api
from atrium.api import modules as modules_api
from atrium.api import reports as reports_api
from atrium.api import triggers as triggers_api
from atrium.config import Settings, get_settings
from atrium.context.embeddings import get_provider
from atrium.context.indexer import VaultIndexer
from atrium.context.librarian import Librarian
from atrium.context.vault import VaultStore
from atrium.core.events import RunEventHub
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

        # startup recovery: runs still marked 'running' belong to a previous
        # process that died mid-run — there's no task behind them anymore.
        cur = await app.state.db.execute(
            """UPDATE runs SET status = 'interrupted',
                   summary = COALESCE(NULLIF(summary, ''), 'interrupted by shutdown'),
                   finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
               WHERE status = 'running'"""
        )
        await app.state.db.commit()
        if cur.rowcount:
            logger.info("startup recovery: marked %d orphaned run(s) interrupted", cur.rowcount)

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
        app.state.anthropic_configured = anthropic_configured
        app.state.run_events = RunEventHub()
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
            events=app.state.run_events,
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
    if settings.auth_token:
        app.add_middleware(BearerAuthMiddleware, token=settings.auth_token)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(modules_api.router)
    app.include_router(triggers_api.router)
    app.include_router(hooks_api.router)
    app.include_router(context_api.router)
    app.include_router(reports_api.router)
    app.include_router(meta_api.router)

    @app.get("/api/health")
    async def health() -> dict:
        async with app.state.db.execute("SELECT 1") as cur:
            await cur.fetchone()
        return {
            "status": "ok",
            "version": __version__,
            "schema_version": app.state.schema_version,
            "vault": str(settings.vault_path),
            "auth_required": bool(settings.auth_token),
        }

    # Serve the built React UI (web/dist) at the root with SPA fallback, so the
    # whole platform runs from one origin in production. No-op if not built.
    dist = settings.web_dist
    if dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")
        index = dist / "index.html"

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            candidate = (dist / full_path) if full_path else index
            if candidate.is_file() and candidate != index:
                return FileResponse(candidate)
            return FileResponse(index)  # client-side routes -> app shell

        logger.info("serving web UI from %s", dist)

    return app
