"""Cross-cutting endpoints: global run feed, platform settings, live event stream."""

import secrets

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["meta"])


@router.get("/api/runs")
async def recent_runs(request: Request, limit: int = 50) -> list[dict]:
    return await request.app.state.runner.list_recent_runs(min(max(limit, 1), 500))


@router.get("/api/settings")
async def settings(request: Request) -> dict:
    s = request.app.state.settings
    indexer = request.app.state.indexer
    return {
        "version": request.app.version,
        "schema_version": request.app.state.schema_version,
        "vault_path": str(s.vault_path),
        "modules_path": str(s.modules_path),
        "embeddings_provider": s.embeddings_provider,
        "embedding_model": s.embedding_model,
        "embeddings_active": indexer._embeddings is not None,
        "llm_model": s.llm_model,
        "router_model": s.router_model,
        "anthropic_configured": request.app.state.anthropic_configured,
        "watch_vault": s.watch_vault,
        "doc_count": indexer.graph.number_of_nodes(),
    }


@router.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    token = websocket.app.state.settings.auth_token
    if token and not secrets.compare_digest(websocket.query_params.get("token", ""), token):
        await websocket.close(code=4401)  # unauthorized
        return
    await websocket.accept()
    hub = websocket.app.state.run_events
    queue = hub.subscribe()
    try:
        await websocket.send_json({"type": "hello"})
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(queue)
