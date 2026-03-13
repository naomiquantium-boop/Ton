from __future__ import annotations
import asyncio, time, re
from typing import Dict
from bot.config import settings
from services.token_meta import fetch_token_meta
from services.ads_service import AdsService
from utils.price import ton_usd
from utils.formatter import build_buy_message_group, build_buy_message_channel
from bot.keyboards import buy_kb

class BuyWatcher:
    POOL_HINTS = ('dedust', 'ston', 'router', 'pool', 'vault', 'lp', 'amm', 'swap')
    SWAP_HINTS = ('swap', 'ston', 'ston.fi', 'stonfi', 'dedust', 'router', 'dex')
    SELL_HINTS = ('sell', 'sold', 'swap jetton for ton', 'jetton->ton', 'swapexactjettonsforton')

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
        # Keep numeric values intact: turn 99,227 into 99227 instead of '99 227'.
        s = re.sub(r'(?<=\d),(?=\d)', '', s)
        for ch in ('\u2009', '\xa0', '\n', '\r', '\t'):
            s = s.replace(ch.encode().decode('unicode_escape'), ' ')
        for arrow in ('→', '➡', '⇒', '⟶', '⟹', '->', '=>'):
            s = s.replace(arrow, ' > ')
        return ' '.join(s.split())

    def _classify_swap_preview(self, value: str | None, labels: list[str]) -> bool | None:
        val = self._normalize_preview_text(value)
        if '>' not in val:
            return None
        left, right = [x.strip() for x in val.split('>', 1)]
        norm_labels = [str(x).lower().strip() for x in labels if x and str(x).strip()]
        left_has = any(lbl in left for lbl in norm_labels)
        right_has = any(lbl in right for lbl in norm_labels)
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

    def _identity_set(self, mint: str, labels: list[str] | None = None) -> set[str]:
        identities = {str(mint).lower().strip()}
        for lbl in (labels or []):
            s = str(lbl or '').lower().strip()
            if s and len(s) >= 2:
                identities.add(s)
        return {x for x in identities if x}

    def _match_identity(self, value: str | None, identities: set[str]) -> bool:
        v = str(value or '').lower().strip()
        if not v:
            return False
        compact = ''.join(ch for ch in v if ch.isalnum())
        for ident in identities:
            if ident == v or ident in v or v in ident:
                return True
            ic = ''.join(ch for ch in ident if ch.isalnum())
            if ic and (ic == compact or ic in compact or compact in ic):
                return True
        return False

    def _extract_side_values(self, flat: list[tuple[str, str]], side: str) -> list[str]:
        tags = {
            'in': ('jetton_master_in', 'token_in', 'asset_in', 'amount_in', 'offer', 'sell', 'source_token', 'from_token', 'input_token'),
            'out': ('jetton_master_out', 'token_out', 'asset_out', 'amount_out', 'ask', 'buy', 'destination_token', 'to_token', 'output_token'),
        }[side]
        values: list[str] = []
        for path, value in flat:
            if any(tag in path for tag in tags):
                values.append(value)
        return values

    def _event_swap_direction(self, event: dict | None, mint: str, labels: list[str] | None = None) -> bool | None:
        if not event:
            return None
        identities = self._identity_set(mint, labels)
        explicit = self._classify_from_preview_fields(event, list(identities))
        if explicit is not None:
            return explicit
        for action in event.get('actions') or []:
            flat = list(self._flatten_pairs(action))
            blob = ' '.join(v for _, v in flat)
            atype = str(action.get('type') or action.get('__typename') or '').lower()
            if 'failed' in blob or 'aborted' in blob or str(action.get('status') or '').lower() in {'failed', 'aborted', 'error'}:
                return False
            is_swap = ('swap' in atype) or ('swap tokens' in blob) or any('jetton_master_in' in p or 'jetton_master_out' in p for p, _ in flat)
            if not is_swap:
                continue
            # 1) direct text preview anywhere in the action
            act_preview = self._classify_from_preview_fields(action, list(identities))
            if act_preview is not None:
                return act_preview
            # 2) structured in/out fields anywhere in the action
            in_vals = self._extract_side_values(flat, 'in')
            out_vals = self._extract_side_values(flat, 'out')
            in_match = any(self._match_identity(v, identities) for v in in_vals)
            out_match = any(self._match_identity(v, identities) for v in out_vals)
            if in_match and not out_match:
                return False
            if out_match and not in_match:
                return True
            # 3) any generic left/right style text line inside the action
            for _, value in flat:
                res = self._classify_swap_preview(value, list(identities))
                if res is not None:
                    return res
        return None

    def _event_action_is_buy(self, event: dict | None, mint: str, labels: list[str] | None = None) -> bool | None:
        return self._event_swap_direction(event, mint, labels)
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
                try:
                    event = await self.rpc.get_event_by_hash(sig)
                    is_buy = self._event_action_is_buy(event, mint, labels)
                except Exception:
                    event = None
                    is_buy = None

                row = ev.get('row') or {}
                preview_side = None
                try:
                    preview_side = self._classify_from_preview_fields(event, labels)
                    if preview_side is None:
                        preview_side = self._classify_from_preview_fields(tx, labels)
                    if preview_side is None:
                        preview_side = self._classify_from_preview_fields(row, labels)
                except Exception:
                    preview_side = None

                if self._row_failed_flag(row) or self._looks_explicit_sell(row, tx, event):
                    await self._set_last_sig(conn, mint, sig)
                    continue

                # Clear parsed sell -> skip immediately.
                if is_buy is False or preview_side is False:
                    await self._set_last_sig(conn, mint, sig)
                    continue
                if is_buy is None and preview_side is True:
                    is_buy = True

                swapish = self._looks_swapish(row, tx, event)
                row_dir = self._row_transfer_direction(row)
                # For swap-like transactions, require an explicit buy classification.
                # This prevents sells like TOKEN > TON / TOKEN > USDT from slipping through.
                if swapish and is_buy is not True:
                    await self._set_last_sig(conn, mint, sig)
                    continue
                # For non-swap plain transfers, only allow obvious inbound transfer direction.
                if not swapish and row_dir is not True:
                    await self._set_last_sig(conn, mint, sig)
                    continue

                ev['event'] = event
                ev['tx'] = tx
                posted = await self._post_buy(mint, ev, tgt, ad_text, ad_link, ton_price)
                if posted:
                    await self._mark_posted(conn, sig)
                await self._set_last_sig(conn, mint, sig)
        await conn.close()

    def _parse_amount_and_asset(self, side: str) -> tuple[float | None, str]:
        s = str(side or '').strip().replace(',', '')
        m = re.search(r'([-+]?\d+(?:\.\d+)?)\s*([A-Za-z0-9_\-$₮]+)', s)
        if not m:
            return None, s.lower()
        try:
            amt = float(m.group(1))
        except Exception:
            amt = None
        return amt, m.group(2).lower()

    def _extract_exact_buy_amounts(self, mint: str, labels: list[str] | None = None, *sources, target_got: float | None = None) -> tuple[float | None, float | None]:
        identities = self._identity_set(mint, labels)
        quote_assets = {"ton", "wton", "pton", "usdt", "usd₮", "usdc"}
        preview_candidates: list[tuple[float, float, float]] = []
        structured_candidates: list[tuple[float, float, float]] = []

        def _asset_matches(asset: str | None) -> bool:
            return self._match_identity(asset, identities)

        def _distance(got_amt: float) -> float:
            if target_got and target_got > 0:
                return abs(float(got_amt) - float(target_got))
            return 0.0

        def _add(lst, spent_amt: float, got_amt: float):
            if spent_amt is None or got_amt is None or spent_amt <= 0 or got_amt <= 0:
                return
            lst.append((float(spent_amt), float(got_amt), _distance(got_amt)))

        def _clean_num_str(s: str) -> str:
            s = self._normalize_preview_text(s)
            s = re.sub(r'(?<=\d),(?=\d)', '', s)
            return s

        def _parse_preview_text(text: str):
            val = _clean_num_str(text)
            if '>' not in val:
                return
            left, right = [x.strip() for x in val.split('>', 1)]
            spent_amt, spent_asset = self._parse_amount_and_asset(left)
            got_amt, got_asset = self._parse_amount_and_asset(right)
            if spent_amt is None or got_amt is None:
                return
            if spent_asset not in quote_assets:
                return
            if not _asset_matches(got_asset):
                return
            _add(preview_candidates, spent_amt, got_amt)

        def _parse_amount_any(raw, asset_obj=None):
            if raw is None:
                return None
            try:
                if isinstance(raw, (int, float)):
                    return float(raw)
                rs = _clean_num_str(str(raw))
                m = re.search(r'[-+]?\d+(?:\.\d+)?', rs)
                return float(m.group(0)) if m else None
            except Exception:
                return None

        def _asset_addr(asset):
            if isinstance(asset, dict):
                return str(asset.get('address') or asset.get('master') or asset.get('jetton_master') or asset.get('jettonMaster') or '').strip().lower()
            return ''

        def _asset_sym(asset):
            if isinstance(asset, dict):
                return str(asset.get('symbol') or asset.get('ticker') or asset.get('name') or '').strip().lower()
            return ''

        def _is_ton_asset(asset):
            return _asset_sym(asset) in quote_assets or str(asset.get('type') if isinstance(asset, dict) else '').lower() == 'ton'

        for src in sources:
            if not src:
                continue
            # Always scan textual preview first and prefer it
            if isinstance(src, dict):
                for path, value in self._flatten_pairs(src):
                    if any(k in path for k in ('preview', 'name', 'description', 'title', 'text', 'label', 'value')):
                        _parse_preview_text(value)
                actions = src.get('actions') or []
                if isinstance(actions, list):
                    for action in actions:
                        if not isinstance(action, dict):
                            continue
                        payload = action.get(action.get('type') or action.get('action') or action.get('name'))
                        aa = dict(action)
                        if isinstance(payload, dict):
                            aa.update(payload)
                        for path, value in self._flatten_pairs(aa):
                            if any(k in path for k in ('preview', 'name', 'description', 'title', 'text', 'label', 'value')):
                                _parse_preview_text(value)
                        in_asset = aa.get('asset_in') or aa.get('assetIn') or aa.get('in') or {}
                        out_asset = aa.get('asset_out') or aa.get('assetOut') or aa.get('out') or {}
                        amt_in = _parse_amount_any(aa.get('amount_in') or aa.get('amountIn') or aa.get('in_amount'), in_asset)
                        amt_out = _parse_amount_any(aa.get('amount_out') or aa.get('amountOut') or aa.get('out_amount'), out_asset)
                        if amt_in and amt_out and _is_ton_asset(in_asset) and (_asset_matches(_asset_addr(out_asset)) or _asset_matches(_asset_sym(out_asset))):
                            _add(structured_candidates, amt_in, amt_out)

        if preview_candidates:
            preview_candidates.sort(key=lambda x: (x[2], -x[0]))
            spent, got, _ = preview_candidates[0]
            return round(spent, 8), round(got, 8)
        if structured_candidates:
            structured_candidates.sort(key=lambda x: (x[2], -x[0]))
            spent, got, _ = structured_candidates[0]
            return round(spent, 8), round(got, 8)
        return None, None

    async def _post_buy(self, mint: str, ev: dict, tgt: dict, ad_text: str | None, ad_link: str | None, ton_price: float):
        meta = await fetch_token_meta(mint); token_name = (meta.get('symbol') or meta.get('name') or mint[:6])
        try:
            if meta.get('symbol') or meta.get('name') or meta.get('dexName'):
                connm = await self.db.connect()
                await connm.execute("UPDATE tracked_tokens SET symbol=COALESCE(?, symbol), name=COALESCE(?, name), preferred_dex=COALESCE(?, preferred_dex) WHERE mint=?", (meta.get('symbol'), meta.get('name'), meta.get('dexName'), mint))
                await connm.commit(); await connm.close()
        except Exception:
            pass
        got_tokens = float(ev.get('got_tokens') or 0.0); buyer = ev.get('buyer') or 'Unknown';
        exact_spent_ton, exact_got_tokens = self._extract_exact_buy_amounts(mint, [mint, meta.get('symbol') or '', meta.get('name') or ''], ev.get('event'), ev.get('tx'), ev.get('row'), target_got=got_tokens)
        if exact_got_tokens and exact_got_tokens > 0:
            got_tokens = exact_got_tokens
        spent_usd = (float(meta.get('priceUsd') or 0.0) * got_tokens) if meta.get('priceUsd') is not None else 0.0
        spent_ton = exact_spent_ton if exact_spent_ton and exact_spent_ton > 0 else ((spent_usd / ton_price) if spent_usd and ton_price else 0.0)
        if exact_spent_ton and exact_spent_ton > 0 and ton_price:
            spent_usd = exact_spent_ton * ton_price
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
        msg_text_channel = build_buy_message_channel(token_symbol=token_name, emoji=token_cfg.get('emoji') or '🟢', spent_sol=spent_ton, spent_usd=spent_usd, spent_symbol='TON', spent_value=spent_ton, got_tokens=got_tokens, buyer=buyer, tx_url=tx_url, price_usd=meta.get('priceUsd'), mcap_usd=meta.get('mcapUsd'), liquidity_usd=meta.get('liquidityUsd'), holders=meta.get('holders'), tg_url=tg_url, ad_text=ad_text, ad_link=ad_link, chart_url=meta.get('dexUrl'))
        sent_any = False
        for r in tgt['groups']:
            min_buy = max(float(settings.MIN_BUY_DEFAULT_TON), float(r['min_buy_sol'] or 0), float(token_cfg.get('min_buy') or 0))
            if spent_ton < min_buy: continue
            emoji = token_cfg.get('emoji') or r['emoji'] or '🟢'; tg = tg_url or r['telegram_link'] or None; media = token_cfg.get('media_file_id') or r['media_file_id']; media_kind = token_cfg.get('media_kind') or 'photo'; chat_id = int(r['group_id']); ctype = await self._chat_type(chat_id)
            msg_text2 = build_buy_message_group(token_symbol=token_name, emoji=emoji, spent_sol=spent_ton, spent_usd=spent_usd, spent_symbol='TON', spent_value=spent_ton, got_tokens=got_tokens, buyer=buyer, tx_url=tx_url, price_usd=meta.get('priceUsd'), mcap_usd=meta.get('mcapUsd'), liquidity_usd=meta.get('liquidityUsd'), holders=meta.get('holders'), tg_url=tg, ad_text=ad_text, ad_link=ad_link, chart_url=meta.get('dexUrl'))
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
