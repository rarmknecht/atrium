from fastapi import APIRouter, HTTPException, Request

from atrium.core.triggers import TriggerError
from atrium.models import TriggerCreate, TriggerUpdate

router = APIRouter(prefix="/api/triggers", tags=["triggers"])


@router.get("")
async def list_triggers(request: Request, module_id: str | None = None) -> list[dict]:
    return await request.app.state.triggers.list(module_id)


@router.post("", status_code=201)
async def create_trigger(request: Request, body: TriggerCreate) -> dict:
    engine = request.app.state.triggers
    try:
        return await engine.create(body.module_id, body.type, body.config, body.enabled)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (TriggerError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.put("/{trigger_id}")
async def update_trigger(request: Request, trigger_id: str, body: TriggerUpdate) -> dict:
    engine = request.app.state.triggers
    try:
        return await engine.update(trigger_id, body.config, body.enabled)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/{trigger_id}", status_code=204)
async def delete_trigger(request: Request, trigger_id: str) -> None:
    engine = request.app.state.triggers
    if await engine.get(trigger_id) is None:
        raise HTTPException(404, f"unknown trigger {trigger_id!r}")
    await engine.delete(trigger_id)
