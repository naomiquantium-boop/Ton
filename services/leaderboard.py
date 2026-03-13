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
        if not settings.TRENDING_CHANNEL:
            return
        conn = await self.db.connect()
        fixed_mid = int(getattr(settings, 'LEADERBOARD_MESSAGE_ID', 0) or 0)
        saved_mid = await self._get_kv(conn, 'leaderboard_message_id')
        if fixed_mid:
            await self._set_kv(conn, 'leaderboard_message_id', str(fixed_mid))
            target_mid = fixed_mid
        elif saved_mid:
            target_mid = int(saved_mid)
        else:
            # Never auto-create leaderboard posts from the updater.
            # A leaderboard message must first be created by /createleaderboard,
            # then the updater only edits that one message.
            await conn.close()
            return
        now = int(time.time()); since = now - 24 * 3600
        cur = await conn.execute("SELECT mint, SUM(usd) AS vol FROM buys WHERE ts>=? GROUP BY mint ORDER BY vol DESC LIMIT 30", (since,))
        buy_rows = await cur.fetchall()
        cur = await conn.execute("SELECT mint, COALESCE(symbol, name, mint) AS label, telegram_link, manual_rank, trend_until_ts, trending_slot FROM tracked_tokens WHERE post_mode!='disabled' ORDER BY created_at DESC")
        tracked = await cur.fetchall()
        cur = await conn.execute("SELECT token_mint AS mint, MAX(telegram_link) AS telegram_link FROM group_settings WHERE telegram_link IS NOT NULL AND telegram_link!='' GROUP BY token_mint")
        group_links = {r['mint']: r['telegram_link'] for r in await cur.fetchall()}
        metrics = {r['mint']: float(r['vol'] or 0) for r in buy_rows}
        labels = {r['mint']: r['label'] for r in tracked}
        tg_links = {r['mint']: (r['telegram_link'] or group_links.get(r['mint'])) for r in tracked}
        tracked_mints = {r['mint'] for r in tracked}
        pinned_top3, pinned_top10 = [], []
        for r in tracked:
            if int(r['trend_until_ts'] or 0) > now:
                if (r['trending_slot'] or '').lower() == 'top3':
                    pinned_top3.append(r['mint'])
                else:
                    pinned_top10.append(r['mint'])
                metrics[r['mint']] = max(metrics.get(r['mint'], 0.0), 1.0)
        organic = [m for m, _ in sorted(metrics.items(), key=lambda kv: kv[1], reverse=True) if m in tracked_mints and m not in pinned_top3 and m not in pinned_top10]
        ordered_mints = (pinned_top3[:3] + pinned_top10[: max(0, 10 - len(pinned_top3[:3]))] + organic)[:10]
        rows: List[Tuple[int, str, str, float, str | None, str | None]] = []
        for mint in ordered_mints:
            meta = await fetch_token_meta(mint)
            label = meta.get('symbol') or meta.get('name') or labels.get(mint) or 'Metadata pending'
            mcap = float(meta.get('mcapUsd') or metrics.get(mint, 0.0) or 0.0)
            is_live = mint in pinned_top3 or mint in pinned_top10
            if (not label or label.upper() == 'TOKEN' or label == mint or label == mint[:6]) and not is_live and mcap <= 0:
                continue

            prev_mcap = 0.0
            try:
                baseline_ts = now - 900
                cur = await conn.execute(
                    "SELECT mcap_usd FROM mcap_snapshots WHERE mint=? AND ts<=? ORDER BY ts DESC, id DESC LIMIT 1",
                    (mint, baseline_ts),
                )
                prev_row = await cur.fetchone()
                if not prev_row:
                    cur = await conn.execute(
                        "SELECT mcap_usd FROM mcap_snapshots WHERE mint=? ORDER BY ts ASC, id ASC LIMIT 1",
                        (mint,),
                    )
                    prev_row = await cur.fetchone()
                prev_mcap = float(prev_row['mcap_usd']) if prev_row and prev_row['mcap_usd'] is not None else 0.0
            except Exception:
                prev_mcap = 0.0

            pct = 0.0
            if prev_mcap > 0 and mcap > 0:
                pct = ((mcap - prev_mcap) / prev_mcap) * 100.0

            metric = f"{mcap/1_000_000:.0f}M" if mcap >= 1_000_000 else (f"{mcap/1_000:.0f}K" if mcap >= 1_000 else f"{mcap:.0f}")
            rows.append((len(rows) + 1, label, metric, pct, tg_links.get(mint), meta.get('dexUrl')))

            if mcap > 0:
                try:
                    cur = await conn.execute(
                        "SELECT mcap_usd, ts FROM mcap_snapshots WHERE mint=? ORDER BY ts DESC, id DESC LIMIT 1",
                        (mint,),
                    )
                    last_snap = await cur.fetchone()
                    last_mcap = float(last_snap['mcap_usd']) if last_snap and last_snap['mcap_usd'] is not None else 0.0
                    last_ts = int(last_snap['ts']) if last_snap and last_snap['ts'] is not None else 0
                    if not last_snap or abs(last_mcap - mcap) > 0.0001 or now - last_ts >= 180:
                        await conn.execute(
                            "INSERT INTO mcap_snapshots(mint, mcap_usd, ts) VALUES(?,?,?)",
                            (mint, mcap, now),
                        )
                except Exception:
                    pass

        await conn.commit()
        text = build_leaderboard_message(rows, settings.LEADERBOARD_FOOTER_HANDLE)
        target_chat = settings.TRENDING_CHANNEL_TARGET
        try:
            await self.bot.edit_message_text(text=text, chat_id=target_chat, message_id=int(target_mid), reply_markup=leaderboard_kb(), disable_web_page_preview=True, parse_mode='HTML')
        except TelegramBadRequest:
            pass
        await conn.close()

    async def close(self):
        self._running = False
