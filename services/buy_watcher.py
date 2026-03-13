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
    POOL_HINTS = ('dedust', 'ston', 'ston.fi', 'stonfi', 'router', 'pool', 'vault', 'lp', 'amm', 'swap')
    SWAP_HINTS = ('swap', 'ston', 'ston.fi', 'stonfi', 'dedust', 'router', 'dex')
    SELL_HINTS = ('sell', 'sold', 'swap jetton for ton', 'jetton->ton', 'swapexactjettonsforton')
    QUOTE_HINTS = (' ton', 'ton ', 'usdt', 'usd₮', 'usd', 'usdc')

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

    async def _was_posted(self, conn, sig: str) -> bool:
        cur = await conn.execute("SELECT 1 FROM state_kv WHERE k=?", (f'posted_tx:{sig}',))
        return (await cur.fetchone()) is not None

    async def _mark_posted(self, conn, sig: str):
        await conn.execute("INSERT INTO state_kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (f'posted_tx:{sig}', str(int(time.time()))))
        await conn.commit()

    def _row_failed_flag(self, row: dict) -> bool:
        if row.get('successful') is False or row.get('success') is False:
            return True
        if row.get('aborted') is True or row.get('transaction_aborted') is True or row.get('tx_aborted') is True:
            return True
        status = str(row.get('status') or '').lower()
        if status in {'failed', 'error', 'aborted'}:
            return True
        return False

    def _tx_is_successful(self, tx: dict | None) -> bool | None:
        if not tx:
            return None
        desc = tx.get('description') or {}
        if desc.get('aborted') is True:
            return False
        compute = tx.get('compute_ph') or tx.get('compute_phase') or {}
        if compute.get('success') is False:
            return False
        action = tx.get('action') or tx.get('action_phase') or {}
        if action and action.get('success') is False:
            return False
        status = str(tx.get('status') or '').lower()
        if status in {'failed', 'error', 'aborted'}:
            return False
        return True
    def _flatten_pairs(self, obj, prefix: str = ""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f"{prefix}.{k}" if prefix else str(k)
                yield from self._flatten_pairs(v, key)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                key = f"{prefix}[{i}]" if prefix else f"[{i}]"
                yield from self._flatten_pairs(v, key)
        else:
            yield prefix.lower(), str(obj).lower()

    def _text_blob(self, *objs) -> str:
        parts: list[str] = []
        for obj in objs:
            if not obj:
                continue
            parts.extend(v for _, v in self._flatten_pairs(obj))
        return ' '.join(parts)

    def _looks_swapish(self, *objs) -> bool:
        blob = self._text_blob(*objs)
        return any(tag in blob for tag in self.SWAP_HINTS)

    def _looks_explicit_sell(self, *objs) -> bool:
        blob = self._text_blob(*objs)
        return any(tag in blob for tag in self.SELL_HINTS)

    def _is_poolish(self, value: str | None) -> bool:
        v = str(value or '').lower()
        return any(tag in v for tag in self.POOL_HINTS)

    def _row_transfer_direction(self, row: dict) -> bool | None:
        src = str(row.get('source') or row.get('from') or row.get('sender') or row.get('wallet_address') or '').lower()
        dst = str(row.get('destination') or row.get('to') or row.get('owner') or row.get('recipient') or '').lower()
        src_pool = self._is_poolish(src)
        dst_pool = self._is_poolish(dst)
        if dst_pool and not src_pool:
            return False
        if src_pool and not dst_pool:
            return True
        if src_pool and dst_pool:
            return False
        return None

    def _row_looks_like_sell(self, row: dict) -> bool:
        transfer_dir = self._row_transfer_direction(row)
        if transfer_dir is False:
            return True
        for path, value in self._flatten_pairs(row):
            if any(k in path for k in ('destination', 'to', 'owner', 'recipient')) and self._is_poolish(value):
                return True
            if any(k in path for k in ('comment', 'payload', 'message', 'opcode', 'operation', 'type')) and any(tag in value for tag in ('sell', 'swapexactjettonsforton', 'swap jetton for ton')):
                return True
        return False


    def _normalize_preview_text(self, value: str | None) -> str:
        s = str(value or '').lower()
        for ch in (',', '\u2009', '\xa0', '\n', '\r', '\t', '→', '➡', '⇒', '⟶', '⟹'):
            s = s.replace(ch, ' > ' if ch in ('→', '➡', '⇒', '⟶', '⟹') else ' ')
        return ' '.join(s.split())

    def _classify_swap_preview(self, value: str | None, labels: list[str]) -> bool | None:
        val = self._normalize_preview_text(value)
        if '>' not in val:
            return None
        left, right = [x.strip() for x in val.split('>', 1)]
        labels = [str(x).lower().strip() for x in labels if x and str(x).strip()]
        left_has = any(lbl in left for lbl in labels)
        right_has = any(lbl in right for lbl in labels)
        if left_has and not right_has:
            return False
        if right_has and not left_has:
            return True
        return None

    def _classify_from_preview_fields(self, obj: dict | None, labels: list[str]) -> bool | None:
        if not obj:
            return None
        explicit = None
        for path, value in self._flatten_pairs(obj):
            if any(k in path for k in ('preview', 'name', 'description', 'title', 'text', 'label', 'value')):
                res = self._classify_swap_preview(value, labels)
                if res is False:
                    return False
                if res is True:
                    explicit = True
        return explicit

    def _event_swap_preview_side(self, event: dict | None, labels: list[str]) -> bool | None:
        if not event or not labels:
            return None
        actions = event.get('actions') or []
        for action in actions:
            flat = list(self._flatten_pairs(action))
            text_blob = ' '.join(v for _, v in flat)
            if 'swap' not in text_blob:
                continue
            res = self._classify_from_preview_fields(action, labels)
            if res is not None:
                return res
        return None

    def _event_action_is_buy(self, event: dict | None, mint: str, labels: list[str] | None = None) -> bool | None:
        if not event:
            return None
        flat_event = list(self._flatten_pairs(event))
        event_blob = ' '.join(v for _, v in flat_event)
        if any(tag in event_blob for tag in ('failed transaction', 'failed', 'aborted', 'bounce', 'bounced')):
            return False
        preview_side = self._event_swap_preview_side(event, labels or [])
        if preview_side is not None:
            return preview_side
        actions = event.get('actions') or []
        target = str(mint).lower()
        saw_swap = False
        buy_score = 0
        sell_score = 0
        for action in actions:
            atype = str(action.get('type') or action.get('__typename') or '').lower()
            status = str(action.get('status') or '').lower()
            flat = list(self._flatten_pairs(action))
            text_blob = ' '.join(v for _, v in flat)
            if status in {'failed', 'error', 'aborted'} or any(tag in text_blob for tag in ('failed transaction', 'failed', 'aborted')):
                return False
            if 'swap' in atype or 'swap' in text_blob:
                saw_swap = True
            for path, value in flat:
                has_target = (target in value) or (target in path)
                if not has_target:
                    continue
                if any(tag in path for tag in ('amount_out', 'jetton_out', 'token_out', 'asset_out', 'receive', 'received')):
                    buy_score += 3
                if any(tag in path for tag in ('amount_in', 'jetton_in', 'token_in', 'asset_in', 'send', 'sent', 'offer')):
                    sell_score += 3
                if any(tag in path for tag in ('destination', 'to', 'recipient')) and self._is_poolish(value):
                    sell_score += 2
                if any(tag in path for tag in ('source', 'from', 'sender')) and self._is_poolish(value):
                    buy_score += 2
            if target in text_blob:
                if any(tag in text_blob for tag in ('sell', 'sold', 'swap jetton for ton', 'jetton->ton')):
                    sell_score += 2
                if any(tag in text_blob for tag in ('buy', 'bought', 'swap ton for jetton', 'ton->jetton')):
                    buy_score += 2
        if saw_swap:
            if sell_score > buy_score and sell_score > 0:
                return False
            if buy_score > sell_score and buy_score > 0:
                return True
            return None
        return None

    def _tx_preview_is_buy(self, tx: dict | None, labels: list[str]) -> bool | None:
        return self._classify_from_preview_fields(tx or {}, labels)

    def _explicit_swap_side_anywhere(self, *objs, labels: list[str]) -> bool | None:
        explicit = None
        for obj in objs:
            if not obj:
                continue
            res = self._classify_from_preview_fields(obj if isinstance(obj, dict) else {'text': obj}, labels)
            if res is False:
                return False
            if res is True:
                explicit = True
        return explicit

    async def run_forever(self):
        self._running = True
        while self._running:
            try: await self.tick()
            except Exception: pass
            await asyncio.sleep(settings.POLL_INTERVAL_SEC)

    async def _fetch_events(self, mint: str, last_sig: str | None):
        rows = await self.rpc.get_jetton_transfers(mint, limit=20)
        events, newest = [], None
        now = int(time.time())
        for row in rows:
            sig = row.get('transaction_hash') or row.get('tx_hash') or row.get('hash')
            if not sig:
                continue
            if newest is None:
                newest = sig
            if last_sig is None:
                continue
            if sig == last_sig:
                break
            if self._row_failed_flag(row):
                continue
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
            events.append({'buyer': buyer, 'got_tokens': got_tokens, 'signature': sig, 'timestamp': ts, 'row': row})
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
            meta_hint = {}
            try:
                meta_hint = await fetch_token_meta(mint)
            except Exception:
                meta_hint = {}
            labels = [mint, meta_hint.get('symbol') or '', meta_hint.get('name') or '']
            for ev in new_events:
                sig = ev['signature']
                if await self._was_posted(conn, sig):
                    await self._set_last_sig(conn, mint, sig)
                    continue
                tx_ok = None
                tx = None
                try:
                    tx = await self.rpc.get_transaction_by_hash(sig)
                    tx_ok = self._tx_is_successful(tx)
                except Exception:
                    tx_ok = None
                if tx_ok is False:
                    await self._set_last_sig(conn, mint, sig)
                    continue
                event = None
                is_buy = None
                tx_preview_buy = None
                try:
                    event = await self.rpc.get_event_by_hash(sig)
                    is_buy = self._event_action_is_buy(event, mint, labels)
                except Exception:
                    event = None
                    is_buy = None
                try:
                    tx_preview_buy = self._tx_preview_is_buy(tx, labels)
                except Exception:
                    tx_preview_buy = None
                explicit_side = self._explicit_swap_side_anywhere(row, tx, event, labels=labels)

                row = ev.get('row') or {}
                if self._row_failed_flag(row) or self._looks_explicit_sell(row, tx, event):
                    await self._set_last_sig(conn, mint, sig)
                    continue

                # Narrow sell-only fix: if any parsed swap preview clearly shows the tracked token on the left/input side, skip it.
                if explicit_side is False or is_buy is False or tx_preview_buy is False or self._row_looks_like_sell(row):
                    await self._set_last_sig(conn, mint, sig)
                    continue

                swapish = self._looks_swapish(row, tx, event)
                row_dir = self._row_transfer_direction(row)
                positive_buy = (is_buy is True) or (tx_preview_buy is True)
                if swapish:
                    if not positive_buy and row_dir is not True:
                        await self._set_last_sig(conn, mint, sig)
                        continue
                else:
                    if not positive_buy and row_dir is not True:
                        await self._set_last_sig(conn, mint, sig)
                        continue

                posted = await self._post_buy(mint, ev, tgt, ad_text, ad_link, ton_price)
                if posted:
                    await self._mark_posted(conn, sig)
                await self._set_last_sig(conn, mint, sig)
        await conn.close()

    async def _post_buy(self, mint: str, ev: dict, tgt: dict, ad_text: str | None, ad_link: str | None, ton_price: float):
        meta = await fetch_token_meta(mint); token_name = (meta.get('symbol') or meta.get('name') or mint[:6]);
        if token_name.startswith(('EQ', 'UQ', 'kQ', '0:')):
            token_name = mint[:6]
        try:
            if meta.get('symbol') or meta.get('name') or meta.get('dexName'):
                connm = await self.db.connect()
                await connm.execute("UPDATE tracked_tokens SET symbol=COALESCE(?, symbol), name=COALESCE(?, name), preferred_dex=COALESCE(?, preferred_dex) WHERE mint=?", (meta.get('symbol'), meta.get('name'), meta.get('dexName'), mint))
                await connm.commit(); await connm.close()
        except Exception:
            pass
        got_tokens = float(ev.get('got_tokens') or 0.0); buyer = ev.get('buyer') or 'Unknown'; spent_usd = (float(meta.get('priceUsd') or 0.0) * got_tokens) if meta.get('priceUsd') is not None else 0.0; spent_ton = (spent_usd / ton_price) if spent_usd and ton_price else 0.0
        if spent_ton < float(settings.MIN_BUY_DEFAULT_TON): return False
        now_ts = int(time.time())
        try:
            conn2 = await self.db.connect()
            if spent_usd > 0: await conn2.execute("INSERT INTO buys(mint, usd, ts) VALUES(?,?,?)", (mint, spent_usd, now_ts))
            if meta.get('priceUsd') is not None: await conn2.execute("INSERT INTO price_snapshots(mint, price_usd, ts) VALUES(?,?,?)", (mint, float(meta.get('priceUsd')), now_ts))
            if meta.get('mcapUsd') is not None: await conn2.execute("INSERT INTO mcap_snapshots(mint, mcap_usd, ts) VALUES(?,?,?)", (mint, float(meta.get('mcapUsd')), now_ts))
            await conn2.commit(); await conn2.close()
        except Exception: pass
        tx_hash_hex = self.rpc.tx_hash_to_hex(ev['signature']) or ev['signature']
        tx_url = settings.TON_VIEWER_TX_URL.format(tx=tx_hash_hex); tg_url = tgt.get('telegram_link'); token_cfg = {'buy_step': 1, 'min_buy': 0.0, 'emoji': '🟢', 'media_file_id': None, 'media_kind': 'photo'}
        try:
            conn_tg = await self.db.connect(); cur2 = await conn_tg.execute("SELECT telegram_link, preferred_dex FROM tracked_tokens WHERE mint=?", (mint,)); row2 = await cur2.fetchone(); cur3 = await conn_tg.execute("SELECT buy_step, min_buy, emoji, media_file_id, media_kind FROM token_settings WHERE mint=?", (mint,)); row3 = await cur3.fetchone(); await conn_tg.close()
            if row2 and row2[0]: tg_url = row2[0]
            if row3: token_cfg = {'buy_step': row3[0] or 1, 'min_buy': float(row3[1] or 0.0), 'emoji': row3[2] or '🟢', 'media_file_id': row3[3], 'media_kind': row3[4] or 'photo'}
        except Exception: pass
        msg_text_channel = build_buy_message_channel(token_symbol=token_name, emoji='✅', spent_sol=spent_ton, spent_usd=spent_usd, spent_symbol='TON', spent_value=spent_ton, got_tokens=got_tokens, buyer=buyer, tx_url=tx_url, price_usd=meta.get('priceUsd'), mcap_usd=meta.get('mcapUsd'), tg_url=tg_url, ad_text=ad_text, ad_link=ad_link, chart_url=meta.get('dexUrl'))
        sent_any = False
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
                sent_any = True
            except Exception:
                pass
        if settings.POST_CHANNEL and (tgt.get('groups') or tgt.get('post_channel')):
            try:
                await self.bot.send_message(settings.POST_CHANNEL_TARGET, msg_text_channel, reply_markup=buy_kb(mint, meta.get('dexName')), disable_web_page_preview=True, parse_mode='HTML')
                sent_any = True
            except Exception:
                pass
        return sent_any

    async def close(self):
        self._running = False
