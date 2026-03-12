from __future__ import annotations
import asyncio, time
from typing import List, Tuple
from bot.config import settings
from services.token_meta import fetch_token_meta
from utils.formatter import build_leaderboard_message
from bot.keyboards import leaderboard_kb
from aiogram.exceptions import TelegramBadRequest

class LeaderboardUpdater:
    def __init__(self, bot, db):
        self.bot = bot; self.db = db; self._running = False

    async def _get_kv(self, conn, key: str):
        cur = await conn.execute("SELECT v FROM state_kv WHERE k=?", (key,)); row = await cur.fetchone(); return row['v'] if row else None

    async def _set_kv(self, conn, key: str, val: str):
        await conn.execute("INSERT INTO state_kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, val)); await conn.commit()

    async def run_forever(self):
        self._running = True
        while self._running:
            try: await self.tick()
            except Exception: pass
            await asyncio.sleep(30)

    async def tick(self):
        if not settings.TRENDING_CHANNEL: return
        conn = await self.db.connect(); now = int(time.time()); since = now - 24 * 3600
        cur = await conn.execute("SELECT mint, SUM(usd) AS vol FROM buys WHERE ts>=? GROUP BY mint ORDER BY vol DESC LIMIT 30", (since,))
        buy_rows = await cur.fetchall()
        cur = await conn.execute("SELECT mint, COALESCE(symbol, name, mint) AS label, manual_rank, trend_until_ts, trending_slot FROM tracked_tokens WHERE post_mode!='disabled' ORDER BY created_at DESC")
        tracked = await cur.fetchall()
        metrics = {r['mint']: float(r['vol'] or 0) for r in buy_rows}
        labels = {r['mint']: r['label'] for r in tracked}
        pinned_top3, pinned_top10 = [], []
        for r in tracked:
            if int(r['trend_until_ts'] or 0) > now:
                if (r['trending_slot'] or '').lower() == 'top3': pinned_top3.append(r['mint'])
                else: pinned_top10.append(r['mint'])
                metrics[r['mint']] = max(metrics.get(r['mint'], 0.0), 1.0)
        organic = [m for m, _ in sorted(metrics.items(), key=lambda kv: kv[1], reverse=True) if m not in pinned_top3 and m not in pinned_top10]
        ordered_mints = pinned_top3[:3] + pinned_top10[:10-len(pinned_top3[:3])] + organic
        ordered_mints = ordered_mints[:10]
        rows: List[Tuple[int, str, str, float, str | None]] = []
        for rank, mint in enumerate(ordered_mints, start=1):
            meta = await fetch_token_meta(mint)
            label = meta.get('symbol') or meta.get('name') or labels.get(mint) or mint[:6]
            mcap = meta.get('mcapUsd') or metrics.get(mint, 0.0)
            metric = f"{mcap/1_000_000:.0f}M" if mcap >= 1_000_000 else (f"{mcap/1_000:.0f}K" if mcap >= 1_000 else f"{mcap:.0f}")
            rows.append((rank, label, metric, 0.0, meta.get('dexUrl')))
        while len(rows) < 10:
            n = len(rows) + 1; rows.append((n, 'TOKEN', '0', 0.0, None))
        text = build_leaderboard_message(rows, settings.LEADERBOARD_FOOTER_HANDLE)
        fixed_mid = int(getattr(settings, 'LEADERBOARD_MESSAGE_ID', 0) or 0)
        if fixed_mid:
            await self._set_kv(conn, 'leaderboard_message_id', str(fixed_mid))
        mid = str(fixed_mid) if fixed_mid else await self._get_kv(conn, 'leaderboard_message_id')
        target_chat = settings.TRENDING_CHANNEL_TARGET
        try:
            if not mid:
                msg = await self.bot.send_message(target_chat, text, reply_markup=leaderboard_kb(), disable_web_page_preview=True, parse_mode='HTML')
                await self._set_kv(conn, 'leaderboard_message_id', str(msg.message_id))
            else:
                await self.bot.edit_message_text(text=text, chat_id=target_chat, message_id=int(mid), reply_markup=leaderboard_kb(), disable_web_page_preview=True, parse_mode='HTML')
        except TelegramBadRequest:
            # When a fixed leaderboard message is configured, never create extra leaderboard posts.
            # This prevents channel spam and only updates the chosen message.
            pass
        await conn.close()

    async def close(self):
        self._running = False
