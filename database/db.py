from pathlib import Path
import aiosqlite


def _sqlite_path(database_url: str) -> str:
    if database_url.startswith('sqlite+aiosqlite:///'):
        return database_url.replace('sqlite+aiosqlite:///', '/')
    if database_url.startswith('sqlite:///'):
        return database_url.replace('sqlite:///', '/')
    raise RuntimeError('Only sqlite database URLs are supported by this starter project')


class DB:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.path = _sqlite_path(database_url)

    async def connect(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(self.path)
        conn.row_factory = aiosqlite.Row
        await conn.execute('PRAGMA journal_mode=WAL;')
        await conn.execute('PRAGMA foreign_keys=ON;')
        return conn
