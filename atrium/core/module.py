"""The module contract: ``Module`` base class and the ``ModuleContext`` injected per run.

Everything crossing the module boundary is serializable (pydantic models, str, dict) —
the rule that keeps the door open for subprocess / out-of-process modules later.
"""

import json
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, ClassVar

import aiosqlite
from pydantic import BaseModel

from atrium.models import RunResult, TriggerInfo, WebhookPayload


class EmptyConfig(BaseModel):
    """Default config for modules that declare none."""


class Reporter:
    """ctx.report — emit reports surfaced in the UI's report feed."""

    def __init__(self, db: aiosqlite.Connection, module_id: str, run_id: str):
        self._db = db
        self._module_id = module_id
        self._run_id = run_id

    async def emit(
        self,
        title: str,
        body_md: str = "",
        kind: str = "report",
        data: dict[str, Any] | None = None,
    ) -> str:
        report_id = uuid.uuid4().hex
        await self._db.execute(
            """INSERT INTO reports (id, module_id, run_id, kind, title, body_md, data_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                report_id,
                self._module_id,
                self._run_id,
                kind,
                title,
                body_md,
                json.dumps(data) if data is not None else None,
            ),
        )
        await self._db.commit()
        return report_id


class KVStore:
    """ctx.state — per-module persistent key-value scratch state."""

    def __init__(self, db: aiosqlite.Connection, module_id: str):
        self._db = db
        self._module_id = module_id

    async def get(self, key: str, default: Any = None) -> Any:
        async with self._db.execute(
            "SELECT value_json FROM kv_state WHERE module_id = ? AND key = ?",
            (self._module_id, key),
        ) as cur:
            row = await cur.fetchone()
        return json.loads(row["value_json"]) if row else default

    async def set(self, key: str, value: Any) -> None:
        await self._db.execute(
            """INSERT INTO kv_state (module_id, key, value_json)
               VALUES (?, ?, ?)
               ON CONFLICT (module_id, key) DO UPDATE SET
                   value_json = excluded.value_json,
                   updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')""",
            (self._module_id, key, json.dumps(value)),
        )
        await self._db.commit()

    async def delete(self, key: str) -> None:
        await self._db.execute(
            "DELETE FROM kv_state WHERE module_id = ? AND key = ?", (self._module_id, key)
        )
        await self._db.commit()


class ModuleContext:
    """Everything the platform hands a module for one run."""

    def __init__(
        self,
        *,
        module_id: str,
        run_id: str,
        config: BaseModel,
        trigger: TriggerInfo,
        db: aiosqlite.Connection,
        logger: logging.Logger,
        librarian=None,
    ):
        self.module_id = module_id
        self.run_id = run_id
        self.config = config
        self.trigger = trigger
        self.logger = logger
        self.report = Reporter(db, module_id, run_id)
        self.state = KVStore(db, module_id)
        self._librarian = librarian

    @property
    def librarian(self):  # noqa: ANN201 — ScopedLibrarian (avoids platform import cycle)
        if self._librarian is None:
            raise RuntimeError("context layer not available in this run")
        return self._librarian

    @property
    def llm(self):  # noqa: ANN201 — LLMService lands in Phase 4
        raise NotImplementedError("The LLM service arrives in Phase 4")


class Module(ABC):
    """Base class every Atrium module implements.

    A module package's __init__.py must expose exactly one Module subclass.
    """

    ConfigModel: ClassVar[type[BaseModel]] = EmptyConfig

    async def setup(self, ctx: ModuleContext) -> None:
        """Optional one-time initialization before a run."""

    @abstractmethod
    async def run(self, ctx: ModuleContext) -> RunResult: ...

    async def teardown(self, ctx: ModuleContext) -> None:
        """Optional cleanup after a run (called even when run() raised)."""

    async def handle_webhook(self, ctx: ModuleContext, payload: WebhookPayload) -> RunResult:
        """Override for webhook-triggered modules; defaults to a plain run()."""
        return await self.run(ctx)
