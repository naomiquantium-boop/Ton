import sqlite3
from pathlib import Path
from typing import Any


def _sqlite_path(database_url: str) -> str:
    # expecting sqlite+aiosqlite:///path
    if database_url.startswith("sqlite+aiosqlite:///"):
        return database_url.replace("sqlite+aiosqlite:///", "/")
    if database_url.startswith("sqlite:///"):
        return database_url.replace("sqlite:///", "/")
    raise RuntimeError("Only sqlite is supported in this starter project. Use sqlite+aiosqlite:///...")


class AsyncCursor:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    async def fetchone(self):
        return self._cursor.fetchone()

    async def fetchall(self):
        return self._cursor.fetchall()

    async def close(self):
        try:
            self._cursor.close()
        except Exception:
            pass


class AsyncConnection:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    async def execute(self, sql: str, params: tuple[Any, ...] = ()):
        cur = self._conn.execute(sql, params)
        return AsyncCursor(cur)

    async def executemany(self, sql: str, seq_of_params):
        cur = self._conn.executemany(sql, seq_of_params)
        return AsyncCursor(cur)

    async def commit(self):
        self._conn.commit()

    async def rollback(self):
        self._conn.rollback()

    async def close(self):
        # Keep the shared process-wide connection open. Existing code opens and closes
        # connections very frequently; doing that with aiosqlite creates a new worker
        # thread per call and can exhaust Railway's thread limit.
        return None


class DB:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.path = _sqlite_path(database_url)
        self._conn: AsyncConnection | None = None

    async def connect(self):
        if self._conn is not None:
            return self._conn
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(self.path, check_same_thread=False)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA journal_mode=WAL;")
        raw.execute("PRAGMA foreign_keys=ON;")
        self._conn = AsyncConnection(raw)
        return self._conn
