"""SQLite persistence (Tier 1 / local). Versioned SQL migrations in /migrations.

The schema is portable to PostgreSQL; moving to Postgres + Alembic is tracked in the roadmap.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


class DB:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        if path not in (":memory:", ""):
            # The web process and the background worker share this file. WAL lets one write while others read, and a busy timeout makes a second writer wait instead of failing.
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA busy_timeout=30000")
        self.lock = threading.Lock()
        self.migrate()

    def migrate(self) -> list[str]:
        applied = []
        with self.lock:
            self.conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT)")
            done = {r[0] for r in self.conn.execute("SELECT version FROM schema_migrations")}
            for f in sorted(MIGRATIONS.glob("*.sql")):
                if f.stem not in done:
                    self.conn.executescript(f.read_text())
                    self.conn.execute("INSERT INTO schema_migrations VALUES(?,?)", (f.stem, now()))
                    applied.append(f.stem)
            self.conn.commit()
        return applied

    def q(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, args).fetchall()

    def x(self, sql: str, args=()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur.lastrowid or 0

    def xmany(self, sql: str, rows) -> None:
        with self.lock:
            self.conn.executemany(sql, rows)
            self.conn.commit()

    @contextmanager
    def tx(self, immediate: bool = False):
        """One atomic transaction. Yields the raw connection: use conn.execute inside (not self.x, which commits).
        immediate=True takes the database's write lock at the start, so two processes cannot both read the same balance and then both spend it."""
        with self.lock:
            try:
                self.conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield self.conn
                self.conn.commit()
            except BaseException:
                self.conn.rollback()
                raise

    def audit(self, actor: str, action: str, detail: dict) -> None:
        self.x("INSERT INTO audit_log(ts,actor,action,detail) VALUES(?,?,?,?)", (now(), actor, action, json.dumps(detail)))

    # preferences ----------------------------------------------------------
    def pref_get(self, key: str, default=None):
        r = self.q("SELECT value FROM preferences WHERE key=?", (key,))
        return json.loads(r[0][0]) if r else default

    def pref_set(self, key: str, value) -> None:
        self.x("INSERT INTO preferences(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               (key, json.dumps(value)))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()
