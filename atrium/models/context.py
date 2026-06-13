from typing import Any

from pydantic import BaseModel, Field


class DocLink(BaseModel):
    target: str                 # resolved vault-relative path (or raw name if unresolved)
    relation: str | None = None # typed relation ('- relates_to [[X]]'), None for inline links
    resolved: bool = True


class ContextDoc(BaseModel):
    """A vault document as the platform sees it. The .md file is the source of truth."""

    path: str                   # vault-relative posix path — the canonical id
    title: str
    tags: list[str] = Field(default_factory=list)
    type: str | None = None
    summary: str | None = None
    updated: str | None = None
    links: list[DocLink] = Field(default_factory=list)
    backlinks: list[str] = Field(default_factory=list)
    body: str | None = None     # included on get/ask, omitted in listings
    frontmatter: dict[str, Any] | None = None


class SearchHit(BaseModel):
    doc: ContextDoc
    score: float
    snippets: list[str] = Field(default_factory=list)


class ContextBundle(BaseModel):
    """What the stage-2 librarian hands an agent: chosen docs + graph neighborhood."""

    query: str
    docs: list[ContextDoc]
    neighbor_summaries: list[ContextDoc] = Field(default_factory=list)
    routed: bool = False        # True when the LLM router picked; False = stage-1 only
