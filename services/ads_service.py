from __future__ import annotations
import time


class AdsService:
    def __init__(self, db):
        self.db = db

    async def active_ad_for_token(self, token_address: str | None) -> tuple[str, str | None]:
        now = int(time.time())
        conn = await self.db.connect()
        try:
            if token_address:
                cur = await conn.execute(
                    "SELECT text, link FROM ads WHERE is_active=1 AND starts_at<=? AND ends_at>=? AND token_address=? ORDER BY id DESC LIMIT 1",
                    (now, now, token_address),
                )
                row = await cur.fetchone()
                if row:
                    return row['text'], row['link']
            cur = await conn.execute(
                "SELECT v FROM state_kv WHERE k='global_ad_text'"
            )
            row = await cur.fetchone()
            text = row['v'] if row else 'Advertise here'
            cur = await conn.execute(
                "SELECT v FROM state_kv WHERE k='global_ad_link'"
            )
            row = await cur.fetchone()
            return text, (row['v'] if row else None)
        finally:
            await conn.close()

    async def set_global_ad(self, text: str, link: str | None = None):
        conn = await self.db.connect()
        try:
            await conn.execute("INSERT INTO state_kv(k,v) VALUES('global_ad_text', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (text,))
            await conn.execute("INSERT INTO state_kv(k,v) VALUES('global_ad_link', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (link or '',))
            await conn.commit()
        finally:
            await conn.close()
