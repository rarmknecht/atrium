"""Vault: parse and write the markdown documents that are the context layer's
source of truth.

Conventions (Obsidian/basic-memory compatible):
- YAML frontmatter: title, tags, type, summary, updated
- Inline wikilinks: [[Target]], [[Target|alias]], [[Target#heading]]
- Typed relations: list lines of the form '- relation_type [[Target]]'
- Link targets resolve by exact relative path, then by filename stem (case-insensitive)
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import frontmatter

WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]")
RELATION_RE = re.compile(r"^\s*-\s+([a-z][a-z0-9_ ]*?)\s+(\[\[[^\]]+\]\])\s*$", re.IGNORECASE)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

MAX_CHUNK_CHARS = 1800


@dataclass
class RawLink:
    target: str          # as written inside [[...]]
    relation: str | None = None


@dataclass
class ParsedDoc:
    path: str            # vault-relative posix path
    title: str
    tags: list[str]
    type: str | None
    summary: str | None
    updated: str | None
    body: str
    frontmatter: dict
    raw_links: list[RawLink] = field(default_factory=list)
    content_hash: str = ""


@dataclass
class Chunk:
    idx: int
    heading: str
    content: str

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(f"{self.heading}\n{self.content}".encode()).hexdigest()


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    return [str(v) for v in value]


def parse_markdown(rel_path: str, text: str) -> ParsedDoc:
    post = frontmatter.loads(text)
    meta = dict(post.metadata)
    body = post.content

    links: list[RawLink] = []
    seen: set[tuple[str, str | None]] = set()
    for line in body.splitlines():
        m = RELATION_RE.match(line)
        relation = m.group(1).strip().lower().replace(" ", "_") if m else None
        for target in WIKILINK_RE.findall(line):
            key = (target.strip(), relation)
            if target.strip() and key not in seen:
                seen.add(key)
                links.append(RawLink(target=target.strip(), relation=relation))

    summary = meta.get("summary")
    if not summary:
        for para in body.split("\n\n"):
            para = para.strip()
            if para and not para.startswith("#"):
                summary = re.sub(r"\s+", " ", para)[:200]
                break

    return ParsedDoc(
        path=rel_path,
        title=str(meta.get("title") or PurePosixPath(rel_path).stem.replace("_", " ")),
        tags=_as_list(meta.get("tags")),
        type=str(meta["type"]) if meta.get("type") else None,
        summary=summary,
        updated=str(meta["updated"]) if meta.get("updated") else None,
        body=body,
        frontmatter=meta,
        raw_links=links,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def chunk_body(title: str, body: str) -> list[Chunk]:
    """Heading-aware chunks; oversized sections split on paragraph boundaries."""
    sections: list[tuple[str, list[str]]] = [(title, [])]
    for line in body.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            sections.append((m.group(2).strip() or title, []))
        else:
            sections[-1][1].append(line)

    chunks: list[Chunk] = []
    for heading, lines in sections:
        text = "\n".join(lines).strip()
        if not text:
            continue
        if len(text) <= MAX_CHUNK_CHARS:
            chunks.append(Chunk(idx=len(chunks), heading=heading, content=text))
            continue
        buf = ""
        for para in text.split("\n\n"):
            if buf and len(buf) + len(para) + 2 > MAX_CHUNK_CHARS:
                chunks.append(Chunk(idx=len(chunks), heading=heading, content=buf.strip()))
                buf = para
            else:
                buf = f"{buf}\n\n{para}" if buf else para
        if buf.strip():
            chunks.append(Chunk(idx=len(chunks), heading=heading, content=buf.strip()))
    return chunks


class LinkResolver:
    """Resolve raw wikilink targets to vault paths (exact path, then stem match)."""

    def __init__(self, all_paths: list[str]):
        self._paths = set(all_paths)
        self._by_stem: dict[str, str] = {}
        for p in sorted(all_paths):
            self._by_stem.setdefault(PurePosixPath(p).stem.lower(), p)

    def resolve(self, target: str) -> tuple[str, bool]:
        candidate = target if target.endswith(".md") else f"{target}.md"
        candidate = str(PurePosixPath(candidate))
        if candidate in self._paths:
            return candidate, True
        stem = PurePosixPath(target).stem.lower()
        if stem in self._by_stem:
            return self._by_stem[stem], True
        return target, False


class VaultStore:
    """Read/write markdown files. All writes go file-first; the index follows."""

    def __init__(self, root: Path):
        self.root = root

    def normalize(self, rel_path: str) -> str:
        p = PurePosixPath(rel_path.replace("\\", "/"))
        if p.is_absolute() or ".." in p.parts or not p.parts:
            raise ValueError(f"invalid vault path {rel_path!r}")
        if p.suffix.lower() != ".md":
            raise ValueError(f"vault documents must be .md files, got {rel_path!r}")
        return str(p)

    def abs_path(self, rel_path: str) -> Path:
        return self.root / self.normalize(rel_path)

    def list_paths(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*.md")
            if p.is_file() and not any(part.startswith(".") for part in p.parts)
        )

    def read(self, rel_path: str) -> ParsedDoc:
        rel = self.normalize(rel_path)
        text = self.abs_path(rel).read_text(encoding="utf-8")
        return parse_markdown(rel, text)

    def write(self, rel_path: str, fm: dict | None, body: str) -> ParsedDoc:
        rel = self.normalize(rel_path)
        post = frontmatter.Post(body, **(fm or {}))
        text = frontmatter.dumps(post) + "\n"
        target = self.abs_path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        return parse_markdown(rel, text)

    def append(self, rel_path: str, text: str) -> ParsedDoc:
        rel = self.normalize(rel_path)
        target = self.abs_path(rel)
        if target.is_file():
            existing = target.read_text(encoding="utf-8")
            target.write_text(existing.rstrip("\n") + "\n\n" + text.strip() + "\n",
                              encoding="utf-8", newline="\n")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text.strip() + "\n", encoding="utf-8", newline="\n")
        return self.read(rel)

    def delete(self, rel_path: str) -> None:
        self.abs_path(rel_path).unlink(missing_ok=True)
