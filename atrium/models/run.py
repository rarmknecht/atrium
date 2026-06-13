from typing import Any, Literal

from pydantic import BaseModel, Field

from atrium.models.manifest import TriggerType


class RunResult(BaseModel):
    """What a module's run() / handle_webhook() returns."""

    status: Literal["ok", "warning", "error"] = "ok"
    summary: str = ""
    data: dict[str, Any] | None = None


class TriggerInfo(BaseModel):
    """Provenance of a run — what fired it."""

    type: TriggerType
    trigger_id: str | None = None
    payload: dict[str, Any] | None = None


class WebhookPayload(BaseModel):
    """Inbound webhook request, handed to Module.handle_webhook()."""

    headers: dict[str, str] = Field(default_factory=dict)
    query: dict[str, str] = Field(default_factory=dict)
    body: Any = None
