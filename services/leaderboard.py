from __future__ import annotations
import asyncio
from bot.config import settings
from utils.formatter import build_leaderboard
from bot.keyboards import leaderboard_kb


class LeaderboardUpdater:
    def __init__(self, bot, db):
        self.bot = bot
        self.db = db
        self._running = False

    async def _load_tokens(self):
        conn = await self.db.connect()
        try:
            cur = await conn.execute(
                "SELECT t.*, COALESCE(s.show_mcap,1) AS show_mcap FROM tracked_tokens t LEFT JOIN token_settings s ON s.token_address=t.token_address WHERE t.is_active=1 ORDER BY COALESCE(t.manual_rank, 9999), t.updated_at DESC LIMIT 10"
            )
            return await cur.fetchall()
        finally:
            await conn.close()

    async def update_once(self):
        rows = await self._load_tokens()
        tokens = []
        for r in rows:
            tokens.append({
                'symbol': r['symbol'],
                'name': r['name'],
                'chart_link': r['chart_link'],
                'market_cap_usd': (r['manual_rank'] or 0) and 0 or 0,
                'trend_change_pct': 0,
            })
        footer = 'To trend add @SpyTONBot in your group'
        text = build_leaderboard(tokens, footer)
        msg_id = settings.LEADERBOARD_MESSAGE_ID
        if msg_id:
            try:
                await self.bot.edit_message_text(text, chat_id=settings.POST_CHANNEL, message_id=msg_id, reply_markup=leaderboard_kb(settings.LISTING_URL), disable_web_page_preview=True)
                return
            except Exception:
                return
        try:
            sent = await self.bot.send_message(settings.POST_CHANNEL, text, reply_markup=leaderboard_kb(settings.LISTING_URL), disable_web_page_preview=True)
            if sent and settings.LEADERBOARD_MESSAGE_ID is None:
                pass
        except Exception:
            pass

    async def run_forever(self):
        self._running = True
        while self._running:
            try:
                await self.update_once()
            except Exception:
                pass
            await asyncio.sleep(60)

    async def close(self):
        self._running = False
