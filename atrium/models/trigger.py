"""Trigger definitions — validated shapes for each trigger type's config."""

from typing import Any

from pydantic import BaseModel, Field, model_validator

from atrium.models.manifest import TriggerType


class ContinuousConfig(BaseModel):
    """Always-running loop: run() → sleep → repeat."""

    sleep_seconds: float = Field(default=60.0, ge=0.05)
    max_backoff_seconds: float = Field(default=3600.0, ge=1.0)


class ScheduleConfig(BaseModel):
    """Cron expression or fixed interval — exactly one."""

    cron: str | None = None
    interval_seconds: float | None = Field(default=None, ge=0.05)

    @model_validator(mode="after")
    def exactly_one(self) -> "ScheduleConfig":
        if (self.cron is None) == (self.interval_seconds is None):
            raise ValueError("set exactly one of 'cron' or 'interval_seconds'")
        if self.cron is not None:
            from apscheduler.triggers.cron import CronTrigger

            CronTrigger.from_crontab(self.cron)  # raises ValueError on bad expressions
        return self


class WebhookConfig(BaseModel):
    """No options yet — the per-trigger secret token is platform-generated."""


CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "continuous": ContinuousConfig,
    "schedule": ScheduleConfig,
    "webhook": WebhookConfig,
}


def validate_trigger_config(type_: TriggerType, raw: dict[str, Any]) -> BaseModel:
    model = CONFIG_MODELS.get(type_)
    if model is None:
        raise ValueError(f"trigger type {type_!r} takes no configuration")
    return model.model_validate(raw)


class TriggerCreate(BaseModel):
    module_id: str
    type: TriggerType
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class TriggerUpdate(BaseModel):
    config: dict[str, Any] | None = None
    enabled: bool | None = None
