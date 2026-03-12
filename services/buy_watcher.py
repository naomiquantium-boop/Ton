from __future__ import annotations
import asyncio, time
from typing import Dict
from bot.config import settings
from services.token_meta import fetch_token_meta
from services.ads_service import AdsService
from utils.price import ton_usd
from utils.formatter import build_buy_message_group, build_buy_message_channel
from bot.keyboards import buy_kb

class BuyWatcher:
    def __init__(self, bot, db, rpc):
        self.bot = bot; self.db = db; self.rpc = rpc; self._running = False; self._last_ton_price = 3.0; self._chat_type_cache: Dict[int, str] = {}

    async def _chat_type(self, chat_id: int) -> str:
        if chat_id in self._chat_type_cache: return self._chat_type_cache[chat_id]
        try: ctype = getattr(await self.bot.get_chat(chat_id), 'type', '') or ''
        except Exception: ctype = ''
        self._chat_type_cache[chat_id] = ctype; return ctype

    async def _load_targets(self, conn):
        cur = await conn.execute("SELECT * FROM group_settings WHERE is_active=1"); rows = await cur.fetchall(); m = {}
        for r in rows:
            mint = r['token_mint']; m.setdefault(mint, {'groups': [], 'post_channel': False}); m[mint]['groups'].append(r)
        cur = await conn.execute("SELECT mint, post_mode, telegram_link, preferred_dex FROM tracked_tokens"); rows2 = await cur.fetchall()
        for r in rows2:
            mint = r['mint']; m.setdefault(mint, {'groups': [], 'post_channel': False}); m[mint]['post_channel'] = r['post_mode'] == 'channel'; m[mint]['preferred_dex'] = r['preferred_dex']; m[mint]['telegram_link'] = r['telegram_link']
        return m

    async def _get_last_sig(self, conn, mint: str):
        cur = await conn.execute("SELECT v FROM state_kv WHERE k=?", (f'last_sig:{mint}',)); row = await cur.fetchone(); return row['v'] if row else None

    async def _set_last_sig(self, conn, mint: str, sig: str):
        await conn.execute("INSERT INTO state_kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (f'last_sig:{mint}', sig)); await conn.commit()

    async def run_forever(self):
        self._running = True
        while self._running:
            try: await self.tick()
            except Exception: pass
            await asyncio.sleep(settings.POLL_INTERVAL_SEC)

    async def _fetch_events(self, mint: str, last_sig: str | None):
        rows = await self.rpc.get_jetton_transfers(mint, limit=15)
        events, newest = [], None
        now = int(time.time())
        for row in rows:
            sig = row.get('transaction_hash') or row.get('tx_hash') or row.get('hash')
            if not sig:
                continue
            if newest is None:
                newest = sig
            if last_sig is None:
                # first sync: remember newest transfer but do not post history
                continue
            if sig == last_sig:
                break
            amount_raw = row.get('amount') or row.get('jetton_amount') or 0
            decimals = int((row.get('jetton') or {}).get('decimals') or row.get('decimals') or 9)
            try:
                got_tokens = float(amount_raw) / (10 ** decimals)
            except Exception:
                got_tokens = 0.0
            buyer = row.get('destination') or row.get('to') or row.get('owner') or 'Unknown'
            ts = int(row.get('utime') or row.get('timestamp') or now)
            if got_tokens <= 0 or ts < now - 900:
                continue
            events.append({'buyer': buyer, 'got_tokens': got_tokens, 'signature': sig, 'timestamp': ts})
        return list(reversed(events)), newest

    async def tick(self):
        conn = await self.db.connect(); targets = await self._load_targets(conn); ads_svc = AdsService(conn); active_ad_text, active_ad_link = await ads_svc.get_active_ad(); fallback_text = await ads_svc.get_owner_fallback(); ad_text = active_ad_text or fallback_text or 'Promote here with SpyTON Ads'; ad_link = active_ad_link if active_ad_text else settings.BOOK_ADS_URL
        ton_price = await ton_usd(settings.TON_PRICE_URL)
        if ton_price and ton_price > 0: self._last_ton_price = ton_price
        else: ton_price = self._last_ton_price
        for mint, tgt in targets.items():
            last_sig = await self._get_last_sig(conn, mint)
            new_events, newest_sig = await self._fetch_events(mint, last_sig)
            if last_sig is None and newest_sig:
                await self._set_last_sig(conn, mint, newest_sig)
                continue
            if newest_sig and newest_sig != last_sig and not new_events:
                await self._set_last_sig(conn, mint, newest_sig)
            for ev in new_events:
                await self._set_last_sig(conn, mint, ev['signature'])
                await self._post_buy(mint, ev, tgt, ad_text, ad_link, ton_price)
        await conn.close()

    async def _post_buy(self, mint: str, ev: dict, tgt: dict, ad_text: str | None, ad_link: str | None, ton_price: float):
        meta = await fetch_token_meta(mint); token_name = meta.get('symbol') or meta.get('name') or mint[:6]
        got_tokens = float(ev.get('got_tokens') or 0.0); buyer = ev.get('buyer') or 'Unknown'; spent_usd = (float(meta.get('priceUsd') or 0.0) * got_tokens) if meta.get('priceUsd') is not None else 0.0; spent_ton = (spent_usd / ton_price) if spent_usd and ton_price else 0.0
        if spent_ton < float(settings.MIN_BUY_DEFAULT_TON): return
        now_ts = int(time.time())
        try:
            conn2 = await self.db.connect()
            if spent_usd > 0: await conn2.execute("INSERT INTO buys(mint, usd, ts) VALUES(?,?,?)", (mint, spent_usd, now_ts))
            if meta.get('priceUsd') is not None: await conn2.execute("INSERT INTO price_snapshots(mint, price_usd, ts) VALUES(?,?,?)", (mint, float(meta.get('priceUsd')), now_ts))
            if meta.get('mcapUsd') is not None: await conn2.execute("INSERT INTO mcap_snapshots(mint, mcap_usd, ts) VALUES(?,?,?)", (mint, float(meta.get('mcapUsd')), now_ts))
            await conn2.commit(); await conn2.close()
        except Exception: pass
        tx_url = settings.TON_VIEWER_TX_URL.format(tx=ev['signature']); tg_url = tgt.get('telegram_link'); token_cfg = {'buy_step': 1, 'min_buy': 0.0, 'emoji': '🟢', 'media_file_id': None, 'media_kind': 'photo'}
        try:
            conn_tg = await self.db.connect(); cur2 = await conn_tg.execute("SELECT telegram_link, preferred_dex FROM tracked_tokens WHERE mint=?", (mint,)); row2 = await cur2.fetchone(); cur3 = await conn_tg.execute("SELECT buy_step, min_buy, emoji, media_file_id, media_kind FROM token_settings WHERE mint=?", (mint,)); row3 = await cur3.fetchone(); await conn_tg.close()
            if row2 and row2[0]: tg_url = row2[0]
            if row3: token_cfg = {'buy_step': row3[0] or 1, 'min_buy': float(row3[1] or 0.0), 'emoji': row3[2] or '🟢', 'media_file_id': row3[3], 'media_kind': row3[4] or 'photo'}
        except Exception: pass
        msg_text_channel = build_buy_message_channel(token_symbol=token_name, emoji='✅', spent_sol=spent_ton, spent_usd=spent_usd, spent_symbol='TON', spent_value=spent_ton, got_tokens=got_tokens, buyer=buyer, tx_url=tx_url, price_usd=meta.get('priceUsd'), mcap_usd=meta.get('mcapUsd'), tg_url=tg_url, ad_text=ad_text, ad_link=ad_link, chart_url=meta.get('dexUrl'))
        for r in tgt['groups']:
            min_buy = max(float(settings.MIN_BUY_DEFAULT_TON), float(r['min_buy_sol'] or 0), float(token_cfg.get('min_buy') or 0))
            if spent_ton < min_buy: continue
            emoji = token_cfg.get('emoji') or r['emoji'] or '🟢'; tg = tg_url or r['telegram_link'] or None; media = token_cfg.get('media_file_id') or r['media_file_id']; media_kind = token_cfg.get('media_kind') or 'photo'; chat_id = int(r['group_id']); ctype = await self._chat_type(chat_id)
            msg_text2 = build_buy_message_group(token_symbol=token_name, emoji=emoji, spent_sol=spent_ton, spent_usd=spent_usd, spent_symbol='TON', spent_value=spent_ton, got_tokens=got_tokens, buyer=buyer, tx_url=tx_url, price_usd=meta.get('priceUsd'), mcap_usd=meta.get('mcapUsd'), tg_url=tg, ad_text=ad_text, ad_link=ad_link, chart_url=meta.get('dexUrl'))
            try:
                if ctype == 'channel' or not media:
                    await self.bot.send_message(chat_id, msg_text2 if ctype != 'channel' else msg_text_channel, reply_markup=buy_kb(mint, meta.get('dexName')), disable_web_page_preview=True, parse_mode='HTML')
                elif media_kind == 'animation':
                    await self.bot.send_animation(chat_id, media, caption=msg_text2, reply_markup=buy_kb(mint, meta.get('dexName')), parse_mode='HTML')
                elif media_kind == 'video':
                    await self.bot.send_video(chat_id, media, caption=msg_text2, reply_markup=buy_kb(mint, meta.get('dexName')), parse_mode='HTML')
                elif media_kind == 'document':
                    await self.bot.send_document(chat_id, media, caption=msg_text2, reply_markup=buy_kb(mint, meta.get('dexName')), parse_mode='HTML')
                else:
                    await self.bot.send_photo(chat_id, media, caption=msg_text2, reply_markup=buy_kb(mint, meta.get('dexName')), parse_mode='HTML')
            except Exception: pass
        if settings.POST_CHANNEL and (tgt.get('groups') or tgt.get('post_channel')):
            try:
                await self.bot.send_message(settings.POST_CHANNEL, msg_text_channel, reply_markup=buy_kb(mint, meta.get('dexName')), disable_web_page_preview=True, parse_mode='HTML')
            except Exception:
                pass

    async def close(self):
        self._running = False
