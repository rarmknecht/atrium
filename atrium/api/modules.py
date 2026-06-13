import json

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError

from atrium.core.registry import ModuleRecord
from atrium.models import TriggerInfo

router = APIRouter(prefix="/api/modules", tags=["modules"])


def _record_summary(record: ModuleRecord, enabled: bool) -> dict:
    m = record.manifest
    return {
        "id": record.id,
        "status": record.status,
        "error": record.error,
        "warnings": record.load_warnings,
        "enabled": enabled,
        "name": m.name if m else record.dir_name,
        "version": m.version if m else None,
        "description": m.description if m else None,
        "kind": m.kind if m else None,
        "triggers_supported": m.triggers.supported if m else [],
    }


def _get_record(request: Request, module_id: str) -> ModuleRecord:
    record = request.app.state.registry.get(module_id)
    if record is None:
        raise HTTPException(404, f"unknown module {module_id!r}")
    return record


def _get_ready_record(request: Request, module_id: str) -> ModuleRecord:
    record = _get_record(request, module_id)
    if record.status != "ready":
        raise HTTPException(409, f"module {module_id!r} is not loadable: {record.error}")
    return record


@router.get("")
async def list_modules(request: Request) -> list[dict]:
    runner = request.app.state.runner
    return [
        _record_summary(r, await runner.is_enabled(r.id))
        for r in request.app.state.registry.all()
    ]


@router.get("/{module_id}")
async def get_module(request: Request, module_id: str) -> dict:
    record = _get_record(request, module_id)
    runner = request.app.state.runner
    out = _record_summary(record, await runner.is_enabled(module_id))
    if record.status == "ready":
        out["config_schema"] = record.config_model.model_json_schema()
        try:
            out["config"] = (await runner.load_config(record)).model_dump(mode="json")
            out["config_valid"] = True
        except Exception as exc:
            out["config"], out["config_valid"], out["config_error"] = None, False, str(exc)
    return out


@router.put("/{module_id}/config")
async def put_config(request: Request, module_id: str, body: dict) -> dict:
    record = _get_ready_record(request, module_id)
    try:
        config = await request.app.state.runner.save_config(record, body)
    except ValidationError as exc:
        raise HTTPException(422, detail=json.loads(exc.json())) from exc
    return {"config": config.model_dump(mode="json")}


class EnabledBody(BaseModel):
    enabled: bool


@router.put("/{module_id}/enabled")
async def put_enabled(request: Request, module_id: str, body: EnabledBody) -> dict:
    _get_record(request, module_id)
    await request.app.state.runner.set_enabled(module_id, body.enabled)
    return {"enabled": body.enabled}


@router.post("/{module_id}/run")
async def run_module(request: Request, module_id: str) -> dict:
    """Manual trigger. Executes the run to completion and returns the run row."""
    _get_ready_record(request, module_id)
    runner = request.app.state.runner
    run_id = await runner.dispatch(module_id, TriggerInfo(type="manual"))
    run = await runner.get_run(run_id)
    assert run is not None
    return run


@router.get("/{module_id}/runs")
async def list_runs(request: Request, module_id: str, limit: int = 50) -> list[dict]:
    _get_record(request, module_id)
    return await request.app.state.runner.list_runs(module_id, limit=min(limit, 500))
