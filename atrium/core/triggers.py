"""Trigger engine: fires module runs from schedules, continuous loops, and webhooks.

Trigger *definitions* live in the ``triggers`` table (the source of truth, rebuilt into
live jobs/tasks on startup). APScheduler handles cron/interval; continuous triggers are
supervised asyncio tasks with exponential backoff on consecutive errors.
"""

import asyncio
import json
import logging
import secrets
import uuid

import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from atrium.core.registry import ModuleRegistry
from atrium.core.runner import ModuleRunner
from atrium.models import (
    ContinuousConfig,
    ScheduleConfig,
    TriggerInfo,
    validate_trigger_config,
)

logger = logging.getLogger(__name__)


class TriggerError(ValueError):
    """Invalid trigger definition (unknown module, unsupported type, bad config)."""


class TriggerEngine:
    def __init__(self, db: aiosqlite.Connection, registry: ModuleRegistry, runner: ModuleRunner):
        self._db = db
        self._registry = registry
        self._runner = runner
        self._scheduler = AsyncIOScheduler()
        self._continuous: dict[str, asyncio.Task] = {}

    # -- lifecycle ------------------------------------------------------------

    async def start(self) -> None:
        """Rebuild all live jobs/loops from the DB. Called once, inside the event loop."""
        self._scheduler.start()
        for trigger in await self.list():
            if trigger["enabled"]:
                self._register(trigger)
        logger.info(
            "trigger engine up — %d schedule job(s), %d continuous loop(s)",
            len(self._scheduler.get_jobs()),
            len(self._continuous),
        )

    async def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        for task in self._continuous.values():
            task.cancel()
        if self._continuous:
            await asyncio.gather(*self._continuous.values(), return_exceptions=True)
        self._continuous.clear()

    # -- CRUD (DB is source of truth; live state follows) ----------------------

    async def create(self, module_id: str, type_: str, config: dict, enabled: bool = True) -> dict:
        record = self._registry.get(module_id)
        if record is None:
            raise KeyError(f"unknown module {module_id!r}")
        if record.manifest and type_ not in record.manifest.triggers.supported:
            raise TriggerError(
                f"module {module_id!r} does not support {type_!r} triggers "
                f"(supported: {record.manifest.triggers.supported})"
            )
        if type_ == "manual":
            raise TriggerError("manual runs need no trigger — use POST /api/modules/{id}/run")
        validated = validate_trigger_config(type_, config)  # ValueError -> 422 at API layer

        trigger_id = uuid.uuid4().hex
        token = secrets.token_urlsafe(24) if type_ == "webhook" else None
        await self._db.execute(
            """INSERT INTO triggers (id, module_id, type, config_json, token, enabled)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (trigger_id, module_id, type_, validated.model_dump_json(), token, int(enabled)),
        )
        await self._db.commit()

        trigger = await self.get(trigger_id)
        assert trigger is not None
        if enabled:
            self._register(trigger)
        trigger["live"] = self._live_status(trigger)
        return trigger

    async def update(self, trigger_id: str, config: dict | None, enabled: bool | None) -> dict:
        trigger = await self.get(trigger_id)
        if trigger is None:
            raise KeyError(f"unknown trigger {trigger_id!r}")

        new_config = trigger["config"]
        if config is not None:
            new_config = validate_trigger_config(trigger["type"], config).model_dump()
        new_enabled = trigger["enabled"] if enabled is None else enabled

        await self._db.execute(
            """UPDATE triggers SET config_json = ?, enabled = ?,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
               WHERE id = ?""",
            (json.dumps(new_config), int(new_enabled), trigger_id),
        )
        await self._db.commit()

        self._unregister(trigger_id)
        updated = await self.get(trigger_id)
        assert updated is not None
        if updated["enabled"]:
            self._register(updated)
        updated["live"] = self._live_status(updated)
        return updated

    async def delete(self, trigger_id: str) -> None:
        self._unregister(trigger_id)
        await self._db.execute("DELETE FROM triggers WHERE id = ?", (trigger_id,))
        await self._db.commit()

    async def get(self, trigger_id: str) -> dict | None:
        async with self._db.execute(
            "SELECT * FROM triggers WHERE id = ?", (trigger_id,)
        ) as cur:
            row = await cur.fetchone()
        return self._row_to_dict(row) if row else None

    async def list(self, module_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM triggers"
        args: tuple = ()
        if module_id:
            sql += " WHERE module_id = ?"
            args = (module_id,)
        async with self._db.execute(sql + " ORDER BY created_at", args) as cur:
            return [self._row_to_dict(row) for row in await cur.fetchall()]

    async def find_webhook(self, module_id: str, token: str) -> dict | None:
        """Constant-time-ish token match for the inbound webhook route."""
        for trigger in await self.list(module_id):
            if (
                trigger["type"] == "webhook"
                and trigger["enabled"]
                and trigger["token"]
                and secrets.compare_digest(trigger["token"], token)
            ):
                return trigger
        return None

    def _row_to_dict(self, row: aiosqlite.Row) -> dict:
        d = dict(row)
        d["config"] = json.loads(d.pop("config_json"))
        d["enabled"] = bool(d["enabled"])
        d["live"] = self._live_status(d)
        return d

    def _live_status(self, trigger: dict) -> dict:
        """What the engine is actually doing for this trigger right now."""
        if trigger["type"] == "schedule":
            job = self._scheduler.get_job(trigger["id"]) if self._scheduler.running else None
            return {
                "registered": job is not None,
                "next_fire_time": job.next_run_time.isoformat() if job and job.next_run_time else None,
            }
        if trigger["type"] == "continuous":
            task = self._continuous.get(trigger["id"])
            return {"registered": task is not None and not task.done()}
        return {"registered": trigger["enabled"]}  # webhook: enabled == listening

    # -- live registration ------------------------------------------------------

    def _register(self, trigger: dict) -> None:
        if trigger["type"] == "schedule":
            cfg = ScheduleConfig.model_validate(trigger["config"])
            ap_trigger = (
                CronTrigger.from_crontab(cfg.cron)
                if cfg.cron
                else IntervalTrigger(seconds=cfg.interval_seconds)
            )
            self._scheduler.add_job(
                self._fire,
                trigger=ap_trigger,
                args=[trigger["module_id"], trigger["id"], "schedule"],
                id=trigger["id"],
                coalesce=True,          # collapse a missed backlog into one fire
                misfire_grace_time=30,  # later than this -> skip, don't pile up
                max_instances=1,
                replace_existing=True,
            )
        elif trigger["type"] == "continuous":
            cfg = ContinuousConfig.model_validate(trigger["config"])
            task = asyncio.create_task(
                self._continuous_loop(trigger["module_id"], trigger["id"], cfg),
                name=f"continuous:{trigger['module_id']}:{trigger['id']}",
            )
            self._continuous[trigger["id"]] = task
        # webhook + manual need no live registration

    def _unregister(self, trigger_id: str) -> None:
        if self._scheduler.running and self._scheduler.get_job(trigger_id):
            self._scheduler.remove_job(trigger_id)
        task = self._continuous.pop(trigger_id, None)
        if task is not None:
            task.cancel()

    async def _fire(self, module_id: str, trigger_id: str, type_: str) -> None:
        try:
            await self._runner.dispatch(module_id, TriggerInfo(type=type_, trigger_id=trigger_id))
        except Exception:
            # dispatch only raises for platform-level problems (e.g. module became
            # unloadable) — module failures are recorded as error runs, not raised
            logger.exception("trigger %s: dispatch failed for module %s", trigger_id, module_id)

    async def _continuous_loop(
        self, module_id: str, trigger_id: str, cfg: ContinuousConfig
    ) -> None:
        consecutive_errors = 0
        try:
            while True:
                status = None
                try:
                    run_id = await self._runner.dispatch(
                        module_id, TriggerInfo(type="continuous", trigger_id=trigger_id)
                    )
                    run = await self._runner.get_run(run_id)
                    status = run["status"] if run else None
                except Exception:
                    logger.exception(
                        "continuous %s: dispatch failed for module %s", trigger_id, module_id
                    )
                    status = "error"

                if status == "error":
                    consecutive_errors += 1
                    delay = min(
                        cfg.sleep_seconds * (2**consecutive_errors), cfg.max_backoff_seconds
                    )
                    logger.warning(
                        "continuous %s: %d consecutive error(s), backing off %.1fs",
                        trigger_id, consecutive_errors, delay,
                    )
                else:
                    consecutive_errors = 0
                    delay = cfg.sleep_seconds
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            logger.info("continuous %s: stopped", trigger_id)
            raise
