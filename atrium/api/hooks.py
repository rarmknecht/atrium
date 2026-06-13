"""Inbound webhooks: the platform's only write surface intended for external callers.

Authentication is the per-trigger secret token in the URL path. A bad module id or
token both return the same 404 so the endpoint doesn't leak which modules exist.
"""

import json

from fastapi import APIRouter, HTTPException, Request

from atrium.models import TriggerInfo, WebhookPayload

router = APIRouter(prefix="/api/hooks", tags=["hooks"])

# never forward credentials/cookies into module-visible payloads
_DROPPED_HEADERS = {"authorization", "cookie", "x-api-key"}


@router.post("/{module_id}/{token}")
async def inbound_webhook(request: Request, module_id: str, token: str) -> dict:
    trigger = await request.app.state.triggers.find_webhook(module_id, token)
    if trigger is None:
        raise HTTPException(404, "not found")

    raw = await request.body()
    try:
        body = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        body = raw.decode("utf-8", errors="replace")

    payload = WebhookPayload(
        headers={
            k.lower(): v
            for k, v in request.headers.items()
            if k.lower() not in _DROPPED_HEADERS
        },
        query=dict(request.query_params),
        body=body,
    )

    runner = request.app.state.runner
    run_id = await runner.dispatch(
        module_id,
        TriggerInfo(type="webhook", trigger_id=trigger["id"]),
        webhook=payload,
    )
    run = await runner.get_run(run_id)
    assert run is not None
    return {"run_id": run_id, "status": run["status"], "summary": run["summary"]}
