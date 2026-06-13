import asyncio

from pydantic import BaseModel, Field

from atrium.core.module import Module, ModuleContext
from atrium.models import RunResult


class Config(BaseModel):
    greeting: str = Field(default="Hello", description="Word to greet with")
    target: str = Field(default="world", description="Who to greet")
    sleep_seconds: float = Field(default=0.2, ge=0, le=10, description="Pretend-work duration")


class HelloWorld(Module):
    ConfigModel = Config

    async def run(self, ctx: ModuleContext) -> RunResult:
        cfg: Config = ctx.config
        message = f"{cfg.greeting}, {cfg.target}!"
        ctx.logger.info("greeting composed: %s", message)

        await asyncio.sleep(cfg.sleep_seconds)

        count = await ctx.state.get("run_count", 0) + 1
        await ctx.state.set("run_count", count)

        await ctx.report.emit(
            title=message,
            body_md=f"# {message}\n\nThis module has now run **{count}** time(s).",
            kind="greeting",
            data={"count": count},
        )
        ctx.logger.info("report emitted (run %d)", count)
        return RunResult(status="ok", summary=message, data={"count": count})
