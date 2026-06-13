from pydantic import BaseModel, Field

from atrium.core.module import Module, ModuleContext
from atrium.models import RunResult


class Config(BaseModel):
    flag_missing_tags: bool = Field(default=True, description="Flag docs with no tags")
    ignore_prefixes: list[str] = Field(
        default=["logs/"], description="Path prefixes exempt from orphan/tag checks"
    )


class VaultJanitor(Module):
    ConfigModel = Config

    async def run(self, ctx: ModuleContext) -> RunResult:
        cfg: Config = ctx.config
        docs = await ctx.librarian.list_docs()

        def exempt(path: str) -> bool:
            return any(path.startswith(p) for p in cfg.ignore_prefixes)

        dead_links: list[tuple[str, str]] = []
        orphans: list[str] = []
        untagged: list[str] = []

        for doc in docs:
            for link in doc.links:
                if not link.resolved:
                    dead_links.append((doc.path, link.target))
            if exempt(doc.path):
                continue
            if not doc.backlinks and not any(lk.resolved for lk in doc.links):
                orphans.append(doc.path)
            if cfg.flag_missing_tags and not doc.tags:
                untagged.append(doc.path)

        total = len(dead_links) + len(orphans) + len(untagged)
        ctx.logger.info(
            "scanned %d docs: %d dead links, %d orphans, %d untagged",
            len(docs), len(dead_links), len(orphans), len(untagged),
        )

        lines = [f"Scanned **{len(docs)}** documents.", ""]
        if dead_links:
            lines += ["## Dead links", ""]
            lines += [f"- `{p}` → `[[{t}]]` (unresolved)" for p, t in dead_links]
            lines += [""]
        if orphans:
            lines += ["## Orphan documents (no links in or out)", ""]
            lines += [f"- `{p}`" for p in orphans]
            lines += [""]
        if untagged:
            lines += ["## Missing tags", ""]
            lines += [f"- `{p}`" for p in untagged]
            lines += [""]
        if total == 0:
            lines.append("Vault is clean — nothing to fix. ✨")

        await ctx.report.emit(
            title=f"Vault health: {total} finding(s) across {len(docs)} docs",
            body_md="\n".join(lines),
            kind="findings",
            data={
                "docs": len(docs),
                "dead_links": [{"doc": p, "target": t} for p, t in dead_links],
                "orphans": orphans,
                "untagged": untagged,
            },
        )
        return RunResult(
            status="warning" if total else "ok",
            summary=f"{total} finding(s) across {len(docs)} docs",
            data={"findings": total},
        )
