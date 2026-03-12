from __future__ import annotations
import asyncio
from dataclasses import asdict
import time

from bot.config import settings
from bot.keyboards import buy_post_kb
from services.ads_service import AdsService
from services.dex_adapters import ADAPTERS, BuyEvent
from services.metadata import fetch_jetton_meta
from utils.formatter import build_channel_post, build_group_post


class BuyWatcher:
    def __init__(self, bot, db, toncenter=None, tonapi=None):
        self.bot = bot
        self.db = db
        self.toncenter = toncenter
        self.tonapi = tonapi
        self.ads = AdsService(db)
        self._running = False

    async def close(self):
        if self.toncenter:
            await self.toncenter.close()
        if self.tonapi:
            await self.tonapi.close()

    async def _load_tokens(self):
        conn = await self.db.connect()
        try:
            cur = await conn.execute("""
            SELECT t.*, s.buy_step, s.min_buy_ton, s.emoji, s.media_file_id, s.media_kind, s.language,
                   s.show_media, s.show_mcap, s.show_price, s.show_holders, s.show_chart
            FROM tracked_tokens t
            LEFT JOIN token_settings s ON s.token_address=t.token_address
            WHERE t.is_active=1
            """)
            return await cur.fetchall()
        finally:
            await conn.close()

    async def _last_seen(self, key: str) -> str | None:
        conn = await self.db.connect()
        try:
            cur = await conn.execute('SELECT v FROM state_kv WHERE k=?', (key,))
            row = await cur.fetchone()
            return row['v'] if row else None
        finally:
            await conn.close()

    async def _set_last_seen(self, key: str, value: str):
        conn = await self.db.connect()
        try:
            await conn.execute('INSERT INTO state_kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v', (key, value))
            await conn.commit()
        finally:
            await conn.close()

    async def _group_targets(self, token_address: str):
        conn = await self.db.connect()
        try:
            cur = await conn.execute('SELECT * FROM group_settings WHERE token_address=? AND is_active=1', (token_address,))
            return await cur.fetchall()
        finally:
            await conn.close()

    async def _enrich_meta(self, token: dict):
        if not self.tonapi:
            return token
        if token.get('symbol') and token.get('name') and token.get('holders'):
            return token
        try:
            meta = await fetch_jetton_meta(token['token_address'], settings.TONAPI_BASE_URL, settings.TONAPI_API_KEY)
            token['symbol'] = token.get('symbol') or meta['symbol']
            token['name'] = token.get('name') or meta['name']
            token['holders'] = meta['holders']
            token['market_cap_usd'] = token.get('market_cap_usd') or 0
        except Exception:
            pass
        return token

    async def _fetch_events(self, token: dict) -> list[BuyEvent]:
        adapter = ADAPTERS.get(token['source'])
        if not adapter:
            return []
        last_key = f'last_seen:{token["token_address"]}:{token["watch_address"]}'
        last_seen = await self._last_seen(last_key)
        parsed: list[BuyEvent] = []
        newest = None
        if self.tonapi and settings.ENABLE_TONAPI:
            try:
                events = await self.tonapi.get_account_events(token['watch_address'], limit=15)
                for event in events:
                    sig = event.get('event_id') or ''
                    if newest is None:
                        newest = sig
                    if sig and sig == last_seen:
                        break
                    parsed_event = adapter.parse_tonapi_event(token, event)
                    if parsed_event:
                        parsed.append(parsed_event)
                if newest:
                    await self._set_last_seen(last_key, newest)
                    return list(reversed(parsed))
            except Exception:
                pass
        if self.toncenter and settings.ENABLE_TONCENTER:
            try:
                txs = await self.toncenter.get_transactions(token['watch_address'], limit=15)
                for tx in txs:
                    sig = tx.get('hash') or ''
                    if newest is None:
                        newest = sig
                    if sig and sig == last_seen:
                        break
                    parsed_event = adapter.parse_toncenter_tx(token, tx)
                    if parsed_event:
                        parsed.append(parsed_event)
                if newest:
                    await self._set_last_seen(last_key, newest)
            except Exception:
                pass
        return list(reversed(parsed))

    async def _post_event(self, token: dict, event: BuyEvent):
        settings_row = {
            'buy_step': token.get('buy_step') or 1,
            'min_buy_ton': token.get('min_buy_ton') or 0,
            'emoji': token.get('emoji') or '✅',
            'media_file_id': token.get('media_file_id'),
            'media_kind': token.get('media_kind') or 'photo',
        }
        if event.spent_ton < max(float(settings_row['min_buy_ton'] or 0), settings.CHANNEL_MIN_BUY_TON):
            return
        token = await self._enrich_meta(dict(token))
        event_dict = asdict(event)
        event_dict['holders'] = token.get('holders', 0)
        ad_text, ad_link = await self.ads.active_ad_for_token(token['token_address'])
        channel_text = build_channel_post(token, event_dict, settings_row, ad_text, ad_link, settings.TRENDING_URL)
        group_text = build_group_post(token, event_dict, settings_row, ad_text, ad_link, settings.TRENDING_URL)
        secondary_url = settings.TRENDING_URL
        secondary_text = 'Book Trending'
        if token.get('post_channel'):
            await self._send_post(settings.POST_CHANNEL, channel_text, token, event_dict, settings_row, secondary_url, secondary_text)
        groups = await self._group_targets(token['token_address'])
        for group in groups:
            if event.spent_ton < max(float(group['min_buy_ton'] or 0), settings.GROUP_MIN_BUY_TON):
                continue
            await self._send_post(group['group_id'], group_text, token, event_dict, settings_row, token.get('buy_link') or settings.BUY_URL_TEMPLATE, f'Buy {token.get("symbol") or token.get("name") or "Token"} with dTrade')

    async def _send_post(self, chat_id, text, token, event, settings_row, secondary_url, secondary_text):
        reply_markup = buy_post_kb(event.get('chart_url') or token.get('chart_link') or settings.TRENDING_URL, secondary_url, secondary_text)
        media = settings_row.get('media_file_id')
        media_kind = settings_row.get('media_kind')
        try:
            if media:
                if media_kind == 'video':
                    await self.bot.send_video(chat_id, media, caption=text, parse_mode='HTML', reply_markup=reply_markup)
                elif media_kind == 'animation':
                    await self.bot.send_animation(chat_id, media, caption=text, parse_mode='HTML', reply_markup=reply_markup)
                else:
                    await self.bot.send_photo(chat_id, media, caption=text, parse_mode='HTML', reply_markup=reply_markup)
            else:
                await self.bot.send_message(chat_id, text, parse_mode='HTML', disable_web_page_preview=True, reply_markup=reply_markup)
        except Exception:
            pass

    async def tick(self):
        rows = await self._load_tokens()
        for row in rows:
            token = dict(row)
            events = await self._fetch_events(token)
            for event in events:
                await self._post_event(token, event)

    async def run_forever(self):
        self._running = True
        while self._running:
            try:
                await self.tick()
            except Exception:
                pass
            await asyncio.sleep(settings.POLL_INTERVAL_SEC)
