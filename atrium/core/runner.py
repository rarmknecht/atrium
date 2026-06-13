"""Supervised module execution: timeout, crash capture, per-module no-overlap,
log capture, and run-history persistence."""

import asyncio
import json
import logging
import time
import uuid

import aiosqlite
from pydantic import BaseModel, ValidationError

from atrium.core.module import ModuleContext
from atrium.core.registry import ModuleRecord, ModuleRegistry
from atrium.models import RunResult, TriggerInfo, WebhookPayload

logger = logging.getLogger(__name__)

_LOG_FORMAT = logging.Formatter("%(asctime)s %(levelname)s — %(message)s")


class _BufferHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(_LOG_FORMAT)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


class ConfigError(ValueError):
    """Module config in the DB failed validation against the module's ConfigModel."""


class ModuleRunner:
    def __init__(
        self,
        db: aiosqlite.Connection,
        registry: ModuleRegistry,
        librarian=None,
        llm_model: str = "claude-opus-4-8",
        anthropic_configured: bool = False,
    ):
        self._db = db
        self._registry = registry
        self._librarian = librarian  # context-layer Librarian; scoped per module run
        self._llm_model = llm_model
        self._anthropic_configured = anthropic_configured
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, module_id: str) -> asyncio.Lock:
        return self._locks.setdefault(module_id, asyncio.Lock())

    # -- config -------------------------------------------------------------

    async def load_config(self, record: ModuleRecord) -> BaseModel:
        async with self._db.execute(
            "SELECT config_json FROM module_config WHERE module_id = ?", (record.id,)
        ) as cur:
            row = await cur.fetchone()
        raw = json.loads(row["config_json"]) if row else {}
        try:
            return record.config_model.model_validate(raw)
        except ValidationError as exc:
            raise ConfigError(str(exc)) from exc

    async def save_config(self, record: ModuleRecord, raw: dict) -> BaseModel:
        config = record.config_model.model_validate(raw)  # ValidationError -> 422 at API layer
        await self._db.execute(
            """INSERT INTO module_config (module_id, config_json)
               VALUES (?, ?)
               ON CONFLICT (module_id) DO UPDATE SET
                   config_json = excluded.config_json,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
            (record.id, config.model_dump_json()),
        )
        await self._db.commit()
        return config

    async def is_enabled(self, module_id: str) -> bool:
        async with self._db.execute(
            "SELECT enabled FROM module_config WHERE module_id = ?", (module_id,)
        ) as cur:
            row = await cur.fetchone()
        return bool(row["enabled"]) if row else True

    async def set_enabled(self, module_id: str, enabled: bool) -> None:
        await self._db.execute(
            """INSERT INTO module_config (module_id, enabled)
               VALUES (?, ?)
               ON CONFLICT (module_id) DO UPDATE SET
                   enabled = excluded.enabled,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
            (module_id, int(enabled)),
        )
        await self._db.commit()

    # -- execution ----------------------------------------------------------

    async def dispatch(
        self,
        module_id: str,
        trigger: TriggerInfo,
        webhook: WebhookPayload | None = None,
    ) -> str:
        """Execute one run; returns the run id. Never raises for module failures —
        crashes, timeouts, and bad config all land in run history as error rows."""
        record = self._registry.get_ready(module_id)

        if not await self.is_enabled(module_id):
            return await self._record_skip(record, trigger, "module disabled")

        lock = self._lock(module_id)
        if lock.locked():
            return await self._record_skip(record, trigger, "previous run still in progress")

        async with lock:
            return await self._execute(record, trigger, webhook)

    async def _execute(
        self, record: ModuleRecord, trigger: TriggerInfo, webhook: WebhookPayload | None
    ) -> str:
        run_id = uuid.uuid4().hex
        await self._db.execute(
            """INSERT INTO runs (id, module_id, trigger_id, trigger_type, status)
               VALUES (?, ?, ?, ?, 'running')""",
            (run_id, record.id, trigger.trigger_id, trigger.type),
        )
        await self._db.commit()

        buffer = _BufferHandler()
        run_logger = logging.getLogger(f"atrium.module.{record.id}")
        run_logger.setLevel(logging.DEBUG)
        run_logger.addHandler(buffer)

        from atrium.llm.service import LLMService

        llm = LLMService(self._llm_model, configured=self._anthropic_configured)

        started = time.monotonic()
        result: RunResult
        try:
            config = await self.load_config(record)
            assert record.manifest is not None
            librarian = None
            if self._librarian is not None:
                from atrium.context.librarian import ScopedLibrarian

                librarian = ScopedLibrarian(
                    self._librarian, record.id, record.manifest.context
                )
            ctx = ModuleContext(
                module_id=record.id,
                run_id=run_id,
                config=config,
                trigger=trigger,
                db=self._db,
                logger=run_logger,
                librarian=librarian,
                llm=llm,
            )
            assert record.instance is not None
            module = record.instance
            assert record.manifest is not None
            async with asyncio.timeout(record.manifest.timeout_seconds):
                await module.setup(ctx)
                try:
                    if webhook is not None:
                        result = await module.handle_webhook(ctx, webhook)
                    else:
                        result = await module.run(ctx)
                finally:
                    await module.teardown(ctx)
            if not isinstance(result, RunResult):
                result = RunResult(
                    status="warning",
                    summary=f"module returned {type(result).__name__}, expected RunResult",
                )
        except ConfigError as exc:
            result = RunResult(status="error", summary=f"invalid config: {exc}")
        except TimeoutError:
            result = RunResult(
                status="error",
                summary=f"timed out after {record.manifest.timeout_seconds}s",
            )
        except Exception as exc:
            logger.exception("module %s crashed (run %s)", record.id, run_id)
            run_logger.error("crashed: %r", exc)
            result = RunResult(status="error", summary=f"crashed: {exc!r}")
        finally:
            run_logger.removeHandler(buffer)

        duration_ms = int((time.monotonic() - started) * 1000)
        await self._db.execute(
            """UPDATE runs SET status = ?, summary = ?, data_json = ?, logs = ?,
                   tokens_in = ?, tokens_out = ?,
                   finished_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), duration_ms = ?
               WHERE id = ?""",
            (
                result.status,
                result.summary,
                json.dumps(result.data) if result.data is not None else None,
                "\n".join(buffer.lines),
                llm.usage.tokens_in,
                llm.usage.tokens_out,
                duration_ms,
                run_id,
            ),
        )
        await self._db.commit()
        return run_id

    async def _record_skip(
        self, record: ModuleRecord, trigger: TriggerInfo, reason: str
    ) -> str:
        run_id = uuid.uuid4().hex
        await self._db.execute(
            """INSERT INTO runs (id, module_id, trigger_id, trigger_type, status, summary,
                                 finished_at, duration_ms)
               VALUES (?, ?, ?, ?, 'skipped', ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), 0)""",
            (run_id, record.id, trigger.trigger_id, trigger.type, reason),
        )
        await self._db.commit()
        return run_id

    async def get_run(self, run_id: str) -> dict | None:
        async with self._db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def list_runs(self, module_id: str, limit: int = 50) -> list[dict]:
        async with self._db.execute(
            "SELECT * FROM runs WHERE module_id = ? ORDER BY started_at DESC LIMIT ?",
            (module_id, limit),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]
