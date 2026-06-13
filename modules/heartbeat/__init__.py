from pydantic import BaseModel, Field

from atrium.core.module import Module, ModuleContext
from atrium.models import RunResult, WebhookPayload


class Config(BaseModel):
    fail_every: int = Field(
        default=0, ge=0, description="Raise on every Nth beat (0 = never) — for backoff testing"
    )


class Heartbeat(Module):
    ConfigModel = Config

    async def run(self, ctx: ModuleContext) -> RunResult:
        beat = await ctx.state.get("beats", 0) + 1
        await ctx.state.set("beats", beat)
        cfg: Config = ctx.config
        if cfg.fail_every and beat % cfg.fail_every == 0:
            ctx.logger.warning("injected failure on beat %d", beat)
            raise RuntimeError(f"injected failure on beat {beat}")
        ctx.logger.info("beat %d (%s)", beat, ctx.trigger.type)
        return RunResult(status="ok", summary=f"beat {beat}", data={"beat": beat})

    async def handle_webhook(self, ctx: ModuleContext, payload: WebhookPayload) -> RunResult:
        beat = await ctx.state.get("beats", 0) + 1
        await ctx.state.set("beats", beat)
        ctx.logger.info("beat %d via webhook", beat)
        return RunResult(
            status="ok",
            summary=f"beat {beat} (webhook)",
            data={"beat": beat, "body": payload.body, "query": payload.query},
        )
