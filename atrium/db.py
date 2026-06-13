"""SQLite bootstrap and plain-SQL versioned migrations.

Migrations are numbered ``NNNN_name.sql`` files in ``atrium/migrations/``, applied in
order inside a transaction and recorded in ``schema_migrations``.
"""

import logging
import re
from importlib import resources
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

_MIGRATION_RE = re.compile(r"^(\d{4})_.+\.sql$")


def _load_migrations() -> list[tuple[int, str, str]]:
    """Return (version, name, sql) sorted by version."""
    found: list[tuple[int, str, str]] = []
    for entry in resources.files("atrium.migrations").iterdir():
        m = _MIGRATION_RE.match(entry.name)
        if m:
            found.append((int(m.group(1)), entry.name, entry.read_text(encoding="utf-8")))
    found.sort()
    return found


async def connect(db_path: Path) -> aiosqlite.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode = WAL")
    await db.execute("PRAGMA foreign_keys = ON")
    await db.execute("PRAGMA busy_timeout = 5000")
    return db


async def migrate(db: aiosqlite.Connection) -> int:
    """Apply pending migrations; return the resulting schema version."""
    await db.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               version    INTEGER PRIMARY KEY,
               name       TEXT NOT NULL,
               applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
           )"""
    )
    async with db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations") as cur:
        row = await cur.fetchone()
        current = row[0]

    version = current
    for ver, name, sql in _load_migrations():
        if ver <= current:
            continue
        logger.info("applying migration %s", name)
        await db.executescript(sql)
        await db.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)", (ver, name)
        )
        version = ver
    await db.commit()
    return version
