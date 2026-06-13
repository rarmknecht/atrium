from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from atrium.core.module import Module, ModuleContext
from atrium.llm.tools import librarian_tools
from atrium.models import RunResult

SYSTEM = """You write a short personal daily brief for the vault's owner.

Ground everything in the provided vault context — their projects, preferences,
people, and logs. Follow any communication preferences found in the context
exactly (tone, length, structure). Mention concrete items from the vault, not
generic advice. If something looks stale or needs attention, say so plainly.
Output pure markdown, no preamble."""


class Config(BaseModel):
    focus: str = Field(
        default="today's priorities, active projects, and anything stale that needs attention",
        description="What the brief should concentrate on",
    )
    mode: Literal["route", "agent"] = Field(
        default="route",
        description="route: librarian picks context, one completion. agent: Claude explores the vault with tools.",
    )
    write_to_vault: bool = Field(default=True, description="Also save the brief to logs/briefs/")
    model: str | None = Field(default=None, description="Override the platform's default model")
    effort: str | None = Field(default=None, description="Claude effort level override")


class DailyBrief(Module):
    ConfigModel = Config

    async def run(self, ctx: ModuleContext) -> RunResult:
        cfg: Config = ctx.config
        today = date.today().isoformat()

        if cfg.mode == "agent":
            ctx.logger.info("agent mode: Claude explores the vault with librarian tools")
            text = await ctx.llm.agent(
                f"Today is {today}. Explore the vault as needed, then write my daily brief. "
                f"Focus: {cfg.focus}",
                tools=librarian_tools(ctx.librarian),
                system=SYSTEM,
                model=cfg.model,
                effort=cfg.effort,
            )
        else:
            ctx.logger.info("route mode: librarian selects context, single completion")
            bundle = await ctx.librarian.route(
                f"Context needed to write the owner's daily brief for {today}. Focus: {cfg.focus}",
                k=4,
            )
            ctx.logger.info(
                "librarian selected %s (routed=%s)",
                [d.path for d in bundle.docs], bundle.routed,
            )
            context_md = "\n\n---\n\n".join(
                f"<doc path='{d.path}'>\n{d.body}\n</doc>" for d in bundle.docs
            )
            neighbors_md = "\n".join(
                f"- {d.path}: {d.summary}" for d in bundle.neighbor_summaries
            )
            text = await ctx.llm.complete(
                f"Vault context:\n{context_md}\n\n"
                f"Related docs (summaries only):\n{neighbors_md or '- none'}\n\n"
                f"Write my daily brief for {today}. Focus: {cfg.focus}",
                system=SYSTEM,
                model=cfg.model,
                effort=cfg.effort,
            )

        if not text.strip():
            return RunResult(status="error", summary="model returned an empty brief")

        await ctx.report.emit(
            title=f"Daily brief — {today}",
            body_md=text,
            kind="brief",
            data={"mode": cfg.mode, "chars": len(text)},
        )
        if cfg.write_to_vault:
            await ctx.librarian.put(
                f"logs/briefs/{today}.md",
                {"title": f"Daily brief {today}", "tags": ["log", "brief"], "type": "log"},
                text,
            )
        return RunResult(
            status="ok",
            summary=f"brief for {today} ({cfg.mode} mode, {len(text)} chars)",
            data={"mode": cfg.mode, "chars": len(text)},
        )
