from __future__ import annotations
import asyncio
import re
import time
import secrets
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from bot.config import settings
from bot.keyboards import (
    main_menu_kb, token_list_kb, advert_duration_kb, invoice_kb, lang_kb,
    token_edit_page_kb, trending_slot_kb, trending_duration_kb,
)
from services.payment_verifier import find_recent_payment, verify_ton_transfer
from services.ads_service import AdsService
from services.token_meta import fetch_token_meta
from database.db import DB
from utils.ton_rpc import TonAPI

router = Router()
MINT_RE = re.compile(r"^[A-Za-z0-9_-]{40,80}$")

class TrendingFlow(StatesGroup):
    link = State()

class AdvertFlow(StatesGroup):
    link = State()
    content = State()
    duration = State()

class AddTokenFlow(StatesGroup):
    mint = State()
    tg = State()

class EditTokenFlow(StatesGroup):
    value = State()

class InvoiceFlow(StatesGroup):
    txhash = State()

TREND_PRICES = {
    "top3": {
        "2h": (settings.TOP3_2H_PRICE_TON, 2 * 3600, "2h"),
        "4h": (settings.TOP3_4H_PRICE_TON, 4 * 3600, "4h"),
        "8h": (settings.TOP3_8H_PRICE_TON, 8 * 3600, "8h"),
        "24h": (settings.TOP3_24H_PRICE_TON, 24 * 3600, "24h"),
    },
    "top10": {
        "2h": (settings.TOP10_2H_PRICE_TON, 2 * 3600, "2h"),
        "4h": (settings.TOP10_4H_PRICE_TON, 4 * 3600, "4h"),
        "8h": (settings.TOP10_8H_PRICE_TON, 8 * 3600, "8h"),
        "24h": (settings.TOP10_24H_PRICE_TON, 24 * 3600, "24h"),
    },
}
ADS_PRICES = {
    "1d": (settings.ADS_1D_PRICE_TON, 86400, "1day"),
    "3d": (settings.ADS_3D_PRICE_TON, 3 * 86400, "3days"),
    "7d": (settings.ADS_7D_PRICE_TON, 7 * 86400, "7days"),
}


def _label_from_meta(meta: dict | None, mint: str, pending: str = "Metadata pending") -> str:
    meta = meta or {}
    symbol = (meta.get("symbol") or "").strip()
    name = (meta.get("name") or "").strip()
    for value in (symbol, name):
        if value and not value.startswith(("EQ", "UQ", "kQ", "0:")):
            return value
    return pending


def _is_owner(obj: Message | CallbackQuery) -> bool:
    return bool(obj.from_user and int(obj.from_user.id) == int(settings.OWNER_ID))

async def _ensure_owner(msg: Message) -> bool:
    if _is_owner(msg):
        return True
    uid = msg.from_user.id if msg.from_user else 'unknown'
    await msg.reply(f"❌ Owner command failed. Your Telegram ID is: <code>{uid}</code>", parse_mode='HTML')
    return False


def _parse_forceadd_args(raw: str) -> tuple[str, str | None]:
    raw = (raw or '').strip()
    if not raw:
        return '', None
    if '|' in raw:
        a,b = raw.split('|',1)
        return a.strip(), _norm_tg(b.strip()) if b.strip() else None
    parts = raw.split()
    mint = parts[0]
    tg = None
    for item in parts[1:]:
        if item.startswith('http://') or item.startswith('https://') or item.startswith('t.me/') or item.startswith('@'):
            tg = _norm_tg(item)
            break
    return mint, tg


def _extract_tx_sig(v: str) -> str:
    t = (v or '').strip()
    if 'tonviewer.com/transaction/' in t:
        t = t.split('tonviewer.com/transaction/', 1)[1]
    if '?' in t:
        t = t.split('?', 1)[0]
    if '#' in t:
        t = t.split('#', 1)[0]
    return t.rstrip('/').strip()


def _norm_tg(v: str | None) -> str | None:
    if not v:
        return None
    t = v.strip()
    if not t or t.lower() == 'skip':
        return None
    if t.startswith('@'):
        return f'https://t.me/{t[1:]}'
    if t.startswith('t.me/'):
        return f'https://{t}'
    if t.startswith('http://'):
        return f'https://{t[7:]}'
    return t



def _is_ca_query_text(text: str | None) -> bool:
    s = (text or '').strip().lower()
    if not s:
        return False
    base = s.split('@', 1)[0]
    return base in {'ca', '/ca', 'contract', '/contract', 'address', '/address'}

async def _reply_group_ca(msg: Message, db: DB):
    if msg.chat.type not in {'group', 'supergroup'}:
        return False
    conn = await db.connect()
    cur = await conn.execute("SELECT token_mint, COALESCE(NULLIF(symbol,''), NULLIF(name,''), token_mint) AS label FROM group_settings LEFT JOIN tracked_tokens ON tracked_tokens.mint=group_settings.token_mint WHERE group_id=? AND is_active=1 ORDER BY group_settings.id DESC LIMIT 1", (msg.chat.id,))
    row = await cur.fetchone()
    await conn.close()
    if not row:
        await msg.reply('No token added for this group yet.')
        return True
    await msg.reply(f"Symbol: {row['label']}\n{row['token_mint']}")
    return True
async def _tokens(db: DB) -> list[tuple[str, str]]:
    conn = await db.connect()
    cur = await conn.execute("SELECT mint, COALESCE(symbol, name, mint) AS label FROM tracked_tokens ORDER BY created_at DESC LIMIT 50")
    rows = await cur.fetchall()
    await conn.close()
    return [(r['mint'], r['label']) for r in rows]

async def _group_token(db: DB, group_id: int) -> str | None:
    conn = await db.connect()
    cur = await conn.execute("SELECT token_mint FROM group_settings WHERE group_id=? AND is_active=1", (group_id,))
    row = await cur.fetchone()
    await conn.close()
    return row[0] if row else None

async def _latest_pending_invoice_for_user(db: DB, user_id: int):
    conn = await db.connect()
    cur = await conn.execute("SELECT id FROM invoices WHERE user_id=? AND status='pending' ORDER BY created_at DESC LIMIT 1", (user_id,))
    row = await cur.fetchone()
    await conn.close()
    return int(row[0]) if row else None

async def _ensure_token_settings(db: DB, mint: str):
    conn = await db.connect()
    await conn.execute("INSERT OR IGNORE INTO token_settings(mint, created_at) VALUES(?,?)", (mint, int(time.time())))
    await conn.commit(); await conn.close()

async def _render_edit_page(db: DB, mint: str) -> tuple[str, dict]:
    conn = await db.connect()
    cur = await conn.execute("SELECT COALESCE(name, symbol, mint) AS label, telegram_link FROM tracked_tokens WHERE mint=?", (mint,))
    tr = await cur.fetchone()
    cur = await conn.execute("SELECT buy_step, min_buy, emoji, media_file_id, COALESCE(media_kind,'photo') AS media_kind FROM token_settings WHERE mint=?", (mint,))
    ts = await cur.fetchone()
    await conn.close()
    label = tr['label'] if tr else mint[:6]
    values = {
        'buy_step': ts['buy_step'] if ts else 1,
        'min_buy': float(ts['min_buy'] or 0) if ts else 0.0,
        'emoji': ts['emoji'] if ts and ts['emoji'] else '🟢',
        'media_file_id': ts['media_file_id'] if ts else None,
        'media_kind': ts['media_kind'] if ts else 'photo',
        'telegram_link': tr['telegram_link'] if tr else None,
    }
    text = f"Customize your Token\n\n<code>{mint}</code>\n\nName: <b>{label}</b>"
    return text, values

async def _upsert_tracked_token(db: DB, mint: str, telegram_link: str | None = None):
    meta = await fetch_token_meta(mint)
    conn = await db.connect()
    await conn.execute(
        "INSERT INTO tracked_tokens(mint, post_mode, telegram_link, symbol, name, force_trending, force_leaderboard, preferred_dex, created_at) VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(mint) DO UPDATE SET telegram_link=COALESCE(excluded.telegram_link, tracked_tokens.telegram_link), symbol=excluded.symbol, name=excluded.name, preferred_dex=COALESCE(excluded.preferred_dex, tracked_tokens.preferred_dex)",
        (mint, 'channel', telegram_link, meta.get('symbol'), meta.get('name'), 0, 0, meta.get('dexName'), int(time.time())),
    )
    await conn.commit(); await conn.close()
    await _ensure_token_settings(db, mint)
    return meta

async def _create_invoice(db: DB, user_id: int, username: str | None, token_mint: str, kind: str, link: str | None, content: str | None, amount_ton: float, duration_sec: int, slot_name: str | None = None) -> int:
    memo = f"SPYTON-{secrets.token_hex(6).upper()}"
    conn = await db.connect()
    cur = await conn.execute(
        "INSERT INTO invoices(user_id, username, token_mint, kind, link, content, amount_sol, duration_sec, wallet, memo, slot_name, created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, username, token_mint, kind, link, content, amount_ton, duration_sec, settings.PAYMENT_WALLET, memo, slot_name, int(time.time())),
    )
    await conn.commit(); iid = int(cur.lastrowid)
    await conn.close()
    return iid

async def _invoice_text(db: DB, invoice_id: int) -> str:
    conn = await db.connect(); cur = await conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)); inv = await cur.fetchone(); await conn.close()
    title = "Invoice Created"
    duration = f"{int(inv['duration_sec']) // 3600}h" if inv['kind'] == 'trending' else (f"{int(inv['duration_sec']) // 86400}day" if inv['duration_sec'] == 86400 else f"{int(inv['duration_sec']) // 86400}days")
    parts = [f"🧾 <b>{title}</b>", "", f"Token:\n<code>{inv['token_mint']}</code>"]
    if inv['kind'] == 'trending':
        parts.append(f"Slot: <b>{(inv['slot_name'] or '').upper()}</b>")
    parts.append(f"Duration: <b>{duration}</b>")
    parts.append(f"Price: <b>{float(inv['amount_sol']):g} TON</b>")
    parts += ["", f"✅ Pay to wallet:\n<code>{inv['wallet']}</code>", "", f"⚠️ Send with memo/comment:\n<code>{inv['memo']}</code>", "", "Then click <b>Verify Payment ✅</b>", "", "⏳ Invoice expires in <b>20 minutes</b>"]
    return "\n".join(parts)

async def _activation_notice(db: DB, invoice_id: int) -> str:
    conn = await db.connect()
    cur = await conn.execute("SELECT i.kind, i.token_mint, i.duration_sec, i.slot_name, COALESCE(t.symbol, t.name, i.token_mint) AS label FROM invoices i LEFT JOIN tracked_tokens t ON t.mint=i.token_mint WHERE i.id=?", (invoice_id,))
    row = await cur.fetchone(); await conn.close()
    if not row:
        return '✅ Payment verified and campaign activated.'
    if row['kind'] == 'trending':
        hours = max(1, int(row['duration_sec']) // 3600)
        return f"✅ Payment verified.\n🔥 {row['label']} is now live in {(row['slot_name'] or '').upper()} for {hours}h."
    days = max(1, int(row['duration_sec']) // 86400)
    return f"✅ Payment verified.\n💎 {row['label']} ads started for {days} day(s)."

async def _used_signatures(db: DB) -> set[str]:
    conn = await db.connect(); cur = await conn.execute("SELECT tx_sig FROM invoices WHERE tx_sig IS NOT NULL"); rows = await cur.fetchall(); await conn.close(); return {r[0] for r in rows if r[0]}

async def _activate_invoice(db: DB, invoice_id: int, sig: str, amount_ton: float):
    conn = await db.connect(); cur = await conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)); inv = await cur.fetchone()
    if not inv or inv['status'] == 'paid':
        await conn.close(); return False
    now = int(time.time())
    await conn.execute("UPDATE invoices SET status='paid', tx_sig=?, verified_at=? WHERE id=?", (sig, now, invoice_id))
    if inv['kind'] == 'trending':
        manual_rank = 3 if (inv['slot_name'] or '').lower() == 'top3' else 10
        await conn.execute(
            "UPDATE tracked_tokens SET force_trending=1, force_leaderboard=1, manual_rank=?, trending_slot=?, trend_until_ts=?, telegram_link=COALESCE(?, telegram_link) WHERE mint=?",
            (manual_rank, inv['slot_name'], now + int(inv['duration_sec']), inv['link'], inv['token_mint'])
        )
    else:
        ads = AdsService(conn)
        await ads.create_ad(inv['user_id'], inv['content'] or '', inv['link'], now, now + int(inv['duration_sec']), sig, amount_ton, 'ad')
    await conn.commit(); await conn.close(); return True

async def _check_invoice_payment(db: DB, rpc: TonAPI, invoice_id: int):
    conn = await db.connect(); cur = await conn.execute("SELECT status, amount_sol, memo FROM invoices WHERE id=?", (invoice_id,)); inv = await cur.fetchone(); await conn.close()
    if not inv:
        return (False, 'Invoice not found.')
    if inv['status'] == 'paid':
        return (True, 'Already paid.')
    used = await _used_signatures(db)
    res = await find_recent_payment(rpc, settings.PAYMENT_WALLET, float(inv['amount_sol']), used, expected_memo=inv['memo'])
    if not res.ok or not res.signature:
        return (False, 'Payment not detected yet.')
    if await _activate_invoice(db, invoice_id, res.signature, res.amount_ton):
        return (True, await _activation_notice(db, invoice_id))
    return (True, 'Already paid.')

async def _watch_invoice(bot, db: DB, rpc: TonAPI, chat_id: int, invoice_id: int):
    end = time.time() + 20 * 60
    while time.time() < end:
        try:
            ok, message = await _check_invoice_payment(db, rpc, invoice_id)
            if ok and message.startswith('✅'):
                await bot.send_message(chat_id, message)
                return
        except Exception:
            pass
        await asyncio.sleep(20)

@router.message(Command('start'))
async def start(msg: Message, state: FSMContext, db: DB):
    await state.clear()
    payload = ''
    parts = (msg.text or '').split(maxsplit=1)
    if len(parts) > 1:
        payload = parts[1].strip().lower()
    if payload == 'ads':
        tokens = await _tokens(db)
        if not tokens:
            return await msg.answer('💎 SpyTON Ads\n\nNo tracked tokens yet. Use ➕ Add Token first.', reply_markup=main_menu_kb())
        return await msg.answer('💎 SpyTON Ads\n\nSelect your token to continue.', reply_markup=token_list_kb(tokens, 'adtoken', back='menu:home'))
    if payload == 'trending':
        tokens = await _tokens(db)
        if not tokens:
            return await msg.answer('📈 SpyTON Trending\n\nNo tracked tokens yet. Use ➕ Add Token first.', reply_markup=main_menu_kb())
        return await msg.answer('📈 SpyTON Trending\n\nSelect your token to continue.', reply_markup=token_list_kb(tokens, 'trendtoken', back='menu:home'))
    await msg.answer('SpyTON main menu', reply_markup=main_menu_kb())

@router.callback_query(F.data == 'menu:home')
async def menu_home(cq: CallbackQuery, state: FSMContext):
    await state.clear(); await cq.message.answer('SpyTON main menu', reply_markup=main_menu_kb()); await cq.answer()

@router.callback_query(F.data == 'menu:lang')
async def menu_lang(cq: CallbackQuery):
    await cq.message.answer('Choose your buybot language.', reply_markup=lang_kb()); await cq.answer()

@router.callback_query(F.data.startswith('lang:set:'))
async def lang_set(cq: CallbackQuery):
    await cq.message.answer('✅ Language updated.'); await cq.answer()

@router.callback_query(F.data == 'menu:add')
async def menu_add(cq: CallbackQuery, state: FSMContext):
    await state.clear(); await state.set_state(AddTokenFlow.mint); await cq.message.answer('⬇️ Paste the TON token contract address'); await cq.answer()

@router.message(AddTokenFlow.mint)
async def add_token_mint(msg: Message, state: FSMContext, db: DB):
    if _is_ca_query_text(msg.text):
        if await _reply_group_ca(msg, db):
            return
    mint = (msg.text or '').strip()
    if not MINT_RE.match(mint):
        return await msg.reply('Send a valid TON token address.')
    meta = await _upsert_tracked_token(db, mint)
    if msg.chat.type in ('group', 'supergroup'):
        conn = await db.connect()
        await conn.execute(
            "INSERT INTO group_settings(group_id, token_mint, min_buy_sol, emoji, telegram_link, media_file_id, is_active, created_at) VALUES(?,?,?,?,?,?,1,?) ON CONFLICT(group_id) DO UPDATE SET token_mint=excluded.token_mint, is_active=1",
            (msg.chat.id, mint, float(settings.MIN_BUY_DEFAULT_TON), '🟢', None, None, int(time.time())),
        )
        await conn.commit(); await conn.close(); await state.clear()
        return await msg.answer(f"✅ Token Added\n• Token: {_label_from_meta(meta, mint, pending='Metadata pending')}\n• Dex: {meta.get('dexName') or '—'}\n\nNow posting buys automatically for this group.\nUse Edit to customize token settings.", reply_markup=main_menu_kb())
    await state.update_data(token_mint=mint); await state.set_state(AddTokenFlow.tg); await msg.answer('Send token Telegram link or type skip.')

@router.message(AddTokenFlow.tg)
async def add_token_tg(msg: Message, state: FSMContext, db: DB):
    if _is_ca_query_text(msg.text):
        if await _reply_group_ca(msg, db):
            return
    mint = (await state.get_data()).get('token_mint')
    conn = await db.connect(); await conn.execute("UPDATE tracked_tokens SET telegram_link=? WHERE mint=?", (_norm_tg(msg.text), mint)); await conn.commit(); await conn.close(); await state.clear(); await msg.answer('✅ Token saved.', reply_markup=main_menu_kb())

@router.callback_query(F.data == 'menu:view')
async def menu_view(cq: CallbackQuery, db: DB):
    mint = None
    if cq.message and cq.message.chat.type in ('group', 'supergroup'):
        mint = await _group_token(db, cq.message.chat.id)
    if mint:
        conn = await db.connect(); cur = await conn.execute("SELECT * FROM tracked_tokens WHERE mint=?", (mint,)); row = await cur.fetchone(); await conn.close()
        if row:
            await cq.message.answer(f"Token Details\nName: <b>{row['name'] or row['symbol'] or mint[:6]}</b>\nMint: <code>{mint}</code>\nTelegram: {row['telegram_link'] or '—'}", parse_mode='HTML'); return await cq.answer()
    tokens = await _tokens(db)
    await cq.message.answer('👀 Select a token below.' if tokens else 'No tracked tokens yet.', reply_markup=token_list_kb(tokens, 'viewtoken', back='menu:home') if tokens else None)
    await cq.answer()

@router.callback_query(F.data.startswith('viewtoken:'))
async def view_token(cq: CallbackQuery, db: DB):
    mint = cq.data.split(':', 1)[1]
    conn = await db.connect(); cur = await conn.execute("SELECT * FROM tracked_tokens WHERE mint=?", (mint,)); row = await cur.fetchone(); await conn.close()
    if not row:
        return await cq.answer('Token not found', show_alert=True)
    await cq.message.answer(f"Token Details\nName: <b>{row['name'] or row['symbol'] or mint[:6]}</b>\nMint: <code>{mint}</code>\nTelegram: {row['telegram_link'] or '—'}", parse_mode='HTML')
    await cq.answer()

@router.callback_query(F.data == 'menu:edit')
async def menu_edit(cq: CallbackQuery, state: FSMContext, db: DB):
    mint = await _group_token(db, cq.message.chat.id) if cq.message and cq.message.chat.type in ('group', 'supergroup') else None
    if mint:
        await _ensure_token_settings(db, mint); await state.clear(); await state.update_data(edit_page_mint=mint); text2, values = await _render_edit_page(db, mint); await cq.message.answer(text2, parse_mode='HTML', reply_markup=token_edit_page_kb(mint, 1, values)); return await cq.answer()
    tokens = await _tokens(db)
    await cq.message.answer('Hi, please select your token below.' if tokens else 'No tracked tokens yet.', reply_markup=token_list_kb(tokens, 'edittoken', back='menu:home') if tokens else None)
    await cq.answer()

@router.callback_query(F.data.startswith('edittoken:'))
async def edit_token(cq: CallbackQuery, state: FSMContext, db: DB):
    mint = cq.data.split(':', 1)[1]
    await _ensure_token_settings(db, mint)
    await state.clear()
    await state.update_data(edit_page_mint=mint)
    text2, values = await _render_edit_page(db, mint)
    await cq.message.answer(text2, parse_mode='HTML', reply_markup=token_edit_page_kb(mint, 1, values))
    await cq.answer()

@router.callback_query(F.data.startswith('editpage:'))
async def edit_page(cq: CallbackQuery, state: FSMContext, db: DB):
    data = await state.get_data()
    mint = data.get('edit_page_mint')
    if not mint:
        return await cq.answer('Open Edit again.', show_alert=True)
    text, values = await _render_edit_page(db, mint)
    await cq.message.answer(text, parse_mode='HTML', reply_markup=token_edit_page_kb(mint, 1, values))
    await cq.answer()

@router.callback_query(F.data.startswith('editset:'))
async def edit_set(cq: CallbackQuery, state: FSMContext):
    key = cq.data.split(':', 1)[1]
    data = await state.get_data()
    mint = data.get('edit_page_mint')
    if not mint:
        return await cq.answer('Open Edit again.', show_alert=True)
    await state.set_state(EditTokenFlow.value)
    await state.update_data(edit_mint=mint, edit_key=key, edit_page_mint=mint)
    prompts = {'buy_step': 'Send buy step number.', 'min_buy': 'Send minimum buy in TON.', 'link': 'Send Telegram link or type skip.', 'emoji': 'Send emoji.', 'media': 'Send a photo, GIF, or video to use as media, or type skip to clear it.'}
    await cq.message.answer(prompts.get(key, 'Send value.'))
    await cq.answer()

@router.message(EditTokenFlow.value)
async def edit_token_value(msg: Message, state: FSMContext, db: DB):
    if _is_ca_query_text(msg.text):
        if await _reply_group_ca(msg, db):
            return
    data = await state.get_data(); mint = data.get('edit_mint'); key = data.get('edit_key')
    if not mint:
        await state.clear(); return await msg.answer('Please open Edit again.')
    conn = await db.connect(); await conn.execute("INSERT OR IGNORE INTO token_settings(mint, created_at) VALUES(?,?)", (mint, int(time.time())))
    if key == 'link':
        await conn.execute("UPDATE tracked_tokens SET telegram_link=? WHERE mint=?", (_norm_tg(msg.text), mint))
    elif key == 'buy_step':
        await conn.execute("UPDATE token_settings SET buy_step=? WHERE mint=?", (max(1, int(float((msg.text or '1').strip()))), mint))
    elif key == 'min_buy':
        await conn.execute("UPDATE token_settings SET min_buy=? WHERE mint=?", (max(0.0, float((msg.text or '0').strip())), mint))
    elif key == 'emoji':
        await conn.execute("UPDATE token_settings SET emoji=? WHERE mint=?", ((((msg.text or '🟢').strip()) or '🟢')[:8], mint))
    elif key == 'media':
        txt = (msg.text or '').strip().lower()
        if txt == 'skip':
            await conn.execute("UPDATE token_settings SET media_file_id=NULL, media_kind='photo' WHERE mint=?", (mint,))
        elif msg.photo:
            await conn.execute("UPDATE token_settings SET media_file_id=?, media_kind='photo' WHERE mint=?", (msg.photo[-1].file_id, mint))
        elif getattr(msg, 'animation', None):
            await conn.execute("UPDATE token_settings SET media_file_id=?, media_kind='animation' WHERE mint=?", (msg.animation.file_id, mint))
        elif getattr(msg, 'video', None):
            await conn.execute("UPDATE token_settings SET media_file_id=?, media_kind='video' WHERE mint=?", (msg.video.file_id, mint))
        elif getattr(msg, 'document', None):
            await conn.execute("UPDATE token_settings SET media_file_id=?, media_kind='document' WHERE mint=?", (msg.document.file_id, mint))
        else:
            await conn.close(); return await msg.answer('Send a photo, GIF, or video, or type skip.')
    await conn.commit(); await conn.close(); await state.clear(); await state.update_data(edit_page_mint=mint); text, values = await _render_edit_page(db, mint); await msg.answer('✅ Token updated.'); await msg.answer(text, parse_mode='HTML', reply_markup=token_edit_page_kb(mint, 1, values))

@router.callback_query(F.data == 'menu:group')
async def menu_group(cq: CallbackQuery):
    await cq.message.answer('⚙️ Group settings are managed from the token you add to this group.'); await cq.answer()

@router.callback_query(F.data == 'menu:advert')
async def advert_menu(cq: CallbackQuery, db: DB, state: FSMContext):
    await state.clear(); tokens = await _tokens(db)
    if not tokens:
        await cq.message.answer('No tracked tokens yet. Use ➕ Add Token first.')
    else:
        await cq.message.answer('💎 SpyTON Ads\n\nSelect your token to continue.', reply_markup=token_list_kb(tokens, 'adtoken', back='menu:home'))
    await cq.answer()

@router.callback_query(F.data.startswith('adtoken:'))
async def advert_pick_token(cq: CallbackQuery, state: FSMContext):
    mint = cq.data.split(':', 1)[1]; meta = await fetch_token_meta(mint); label = meta.get('symbol') or meta.get('name') or mint[:6]
    await state.clear(); await state.set_state(AdvertFlow.link); await state.update_data(token_mint=mint, token_label=label)
    await cq.message.answer(f'💎 Fill in the advert form to finish.\nToken: <b>{label}</b>', parse_mode='HTML')
    await cq.message.answer('⬇️ Send your Telegram group/channel link'); await cq.answer()

@router.message(AdvertFlow.link)
async def advert_link(msg: Message, state: FSMContext, db: DB):
    if _is_ca_query_text(msg.text):
        if await _reply_group_ca(msg, db):
            return
    await state.update_data(link=(msg.text or '').strip()); await state.set_state(AdvertFlow.content); await msg.answer('⬇️ Enter your advert text.')

@router.message(AdvertFlow.content)
async def advert_content(msg: Message, state: FSMContext, db: DB):
    if _is_ca_query_text(msg.text):
        if await _reply_group_ca(msg, db):
            return
    await state.update_data(content=(msg.text or '').strip()); await state.set_state(AdvertFlow.duration); await msg.answer('Choose ads duration:', reply_markup=advert_duration_kb())

@router.callback_query(F.data.startswith('adpkg:'))
async def advert_duration(cq: CallbackQuery, state: FSMContext, db: DB, rpc: TonAPI):
    key = cq.data.split(':', 1)[1]
    if key not in ADS_PRICES:
        return await cq.answer()
    data = await state.get_data()
    price, seconds, label = ADS_PRICES[key]
    invoice_id = await _create_invoice(db, cq.from_user.id, cq.from_user.username, data['token_mint'], 'ad', data.get('link'), data.get('content'), price, seconds)
    text = await _invoice_text(db, invoice_id)
    await cq.message.answer(text, reply_markup=invoice_kb(invoice_id), disable_web_page_preview=True)
    await state.clear(); asyncio.create_task(_watch_invoice(cq.bot, db, rpc, cq.message.chat.id, invoice_id)); await cq.answer(f'Invoice created for {label}')

@router.callback_query(F.data == 'menu:trending')
async def trending_menu(cq: CallbackQuery, db: DB, state: FSMContext):
    await state.clear(); tokens = await _tokens(db)
    if not tokens:
        await cq.message.answer('No tracked tokens yet. Use ➕ Add Token first.')
    else:
        await cq.message.answer('📈 SpyTON Trending\n\nSelect your token to continue.', reply_markup=token_list_kb(tokens, 'trendtoken', back='menu:home'))
    await cq.answer()

@router.callback_query(F.data.startswith('trendtoken:'))
async def trending_pick_token(cq: CallbackQuery, state: FSMContext):
    mint = cq.data.split(':', 1)[1]
    meta = await fetch_token_meta(mint); label = meta.get('symbol') or meta.get('name') or mint[:6]
    await state.clear(); await state.set_state(TrendingFlow.link); await state.update_data(token_mint=mint, token_label=label)
    await cq.message.answer('⬇️ Send your Telegram group/channel link')
    await cq.answer()

@router.message(TrendingFlow.link)
async def trending_link(msg: Message, state: FSMContext, db: DB):
    if _is_ca_query_text(msg.text):
        if await _reply_group_ca(msg, db):
            return
    await state.update_data(link=(msg.text or '').strip())
    await msg.answer('Choose your trending slot:', reply_markup=trending_slot_kb())

@router.callback_query(F.data.startswith('trendslot:'))
async def trending_slot(cq: CallbackQuery, state: FSMContext):
    slot_name = cq.data.split(':', 1)[1]
    await state.update_data(slot_name=slot_name)
    await cq.message.answer(f'✅ Slot: <b>{slot_name.upper()}</b>\n\nChoose duration:', parse_mode='HTML', reply_markup=trending_duration_kb(slot_name))
    await cq.answer()

@router.callback_query(F.data.startswith('trenddur:'))
async def trending_duration(cq: CallbackQuery, state: FSMContext, db: DB, rpc: TonAPI):
    _, slot_name, dur = cq.data.split(':', 2)
    data = await state.get_data()
    if slot_name not in TREND_PRICES or dur not in TREND_PRICES[slot_name]:
        return await cq.answer()
    price, seconds, _ = TREND_PRICES[slot_name][dur]
    invoice_id = await _create_invoice(db, cq.from_user.id, cq.from_user.username, data['token_mint'], 'trending', data.get('link'), None, price, seconds, slot_name)
    text = await _invoice_text(db, invoice_id)
    await cq.message.answer(text, reply_markup=invoice_kb(invoice_id), disable_web_page_preview=True)
    await state.clear(); asyncio.create_task(_watch_invoice(cq.bot, db, rpc, cq.message.chat.id, invoice_id)); await cq.answer('Invoice created')

@router.callback_query(F.data.startswith('invoice:paid:'))
async def invoice_paid(cq: CallbackQuery, db: DB, rpc: TonAPI):
    invoice_id = int(cq.data.rsplit(':', 1)[1]); ok, message = await _check_invoice_payment(db, rpc, invoice_id)
    if ok and message.startswith('✅'):
        await cq.message.answer(message); return await cq.answer('Verified')
    await cq.answer(message, show_alert=True)

@router.message(Command('whoami'))
async def whoami(msg: Message):
    uid = msg.from_user.id if msg.from_user else 'unknown'; await msg.reply(f"Your Telegram ID: <code>{uid}</code>", parse_mode='HTML')

@router.message(Command('tokens'))
async def tokens_cmd(msg: Message, db: DB):
    rows = await _tokens(db)
    if not rows:
        return await msg.reply('No tracked tokens.')
    await msg.reply('Tracked tokens:\n' + '\n'.join([f"• {label} — <code>{mint}</code>" for mint, label in rows]), parse_mode='HTML')

@router.message(Command('forceadd'))
async def forceadd(msg: Message, command: CommandObject, db: DB):
    if not await _ensure_owner(msg): return
    if not command.args: return await msg.reply('Usage:\n<code>/forceadd MINT|https://t.me/yourlink</code>', parse_mode='HTML')
    mint, tg = _parse_forceadd_args(command.args)
    if not mint: return await msg.reply('❌ Missing token mint.')
    meta = await _upsert_tracked_token(db, mint, tg)
    label = _label_from_meta(meta, mint, pending="Metadata pending")
    await msg.reply(f"✅ Token added: {label}")

@router.message(Command('forcetrending'))
async def forcetrending(msg: Message, command: CommandObject, db: DB):
    if not await _ensure_owner(msg): return
    if not command.args: return await msg.reply('Usage:\n<code>/forcetrending MINT [hours] [telegram_link]</code>', parse_mode='HTML')
    mint, tg = _parse_forceadd_args(command.args); parts = command.args.split(); hours = 24
    for item in parts[1:]:
        if item.isdigit(): hours = int(item); break
    meta = await _upsert_tracked_token(db, mint, tg)
    conn = await db.connect()
    await conn.execute("UPDATE tracked_tokens SET post_mode='channel', force_trending=1, force_leaderboard=1, manual_rank=10, trending_slot='top10', trend_until_ts=?, telegram_link=COALESCE(?, telegram_link) WHERE mint=?", (int(time.time()) + hours * 3600, tg, mint))
    await conn.commit(); await conn.close()
    label = _label_from_meta(meta, mint, pending="Token")
    await msg.reply(f"✅ {label} forced into trending for {hours}h.")

@router.message(Command('forceleaderboard'))
async def forceleaderboard(msg: Message, command: CommandObject, db: DB):
    if not await _ensure_owner(msg): return
    if not command.args: return await msg.reply('Usage:\n<code>/forceleaderboard MINT</code>', parse_mode='HTML')
    mint = command.args.strip().split()[0]; await _upsert_tracked_token(db, mint); conn = await db.connect(); await conn.execute("UPDATE tracked_tokens SET force_leaderboard=1 WHERE mint=?", (mint,)); await conn.commit(); await conn.close(); await msg.reply('✅ Token forced into leaderboard.')



@router.message(Command('createleaderboard'))
async def createleaderboard(msg: Message, db: DB):
    if not await _ensure_owner(msg):
        return
    target_chat = settings.TRENDING_CHANNEL_TARGET if settings.TRENDING_CHANNEL else msg.chat.id
    text = '🏆 <b>SpyTON Trending Leaderboard</b>\n\nLoading leaderboard...'
    kb = __import__('bot.keyboards', fromlist=['leaderboard_kb']).leaderboard_kb()
    fixed_mid = int(getattr(settings, 'LEADERBOARD_MESSAGE_ID', 0) or 0)
    conn = await db.connect()
    try:
        if fixed_mid:
            await msg.bot.edit_message_text(text=text, chat_id=target_chat, message_id=fixed_mid, reply_markup=kb, parse_mode='HTML', disable_web_page_preview=True)
            await conn.execute("INSERT INTO state_kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", ('leaderboard_message_id', str(fixed_mid)))
            await conn.commit()
            await msg.reply(f'✅ Leaderboard target set to existing message.\nMessage ID: <code>{fixed_mid}</code>', parse_mode='HTML')
            return
        sent = await msg.bot.send_message(target_chat, text, reply_markup=kb, parse_mode='HTML', disable_web_page_preview=True)
        await conn.execute("INSERT INTO state_kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", ('leaderboard_message_id', str(sent.message_id)))
        await conn.commit()
        await msg.reply(f'✅ Leaderboard created in {target_chat}.\nMessage ID: <code>{sent.message_id}</code>', parse_mode='HTML')
    except Exception as e:
        await msg.reply(f'❌ Could not target leaderboard message. Make sure the channel ID is correct, the bot is admin, and LEADERBOARD_MESSAGE_ID belongs to a message sent by this bot.\n\nError: <code>{type(e).__name__}: {e}</code>', parse_mode='HTML', disable_web_page_preview=True)
    finally:
        await conn.close()

@router.message(Command('refreshleaderboard'))
async def refreshleaderboard(msg: Message):
    if not await _ensure_owner(msg):
        return
    await msg.reply('✅ Leaderboard refresher is running. It updates automatically every 30 seconds.')

@router.message(Command('removetrending'))
async def removetrending(msg: Message, command: CommandObject, db: DB):
    if not await _ensure_owner(msg): return
    if not command.args: return await msg.reply('Usage:\n<code>/removetrending MINT</code>', parse_mode='HTML')
    mint = command.args.strip().split()[0]; conn = await db.connect(); await conn.execute("UPDATE tracked_tokens SET force_trending=0, trend_until_ts=0, trending_slot=NULL WHERE mint=?", (mint,)); await conn.commit(); await conn.close(); await msg.reply('✅ Trending removed for token.')

@router.message(Command('disabletoken'))
async def disabletoken(msg: Message, command: CommandObject, db: DB):
    if not await _ensure_owner(msg): return
    if not command.args: return await msg.reply('Usage:\n<code>/disabletoken MINT</code>', parse_mode='HTML')
    mint = command.args.strip().split()[0]; conn = await db.connect(); await conn.execute("UPDATE tracked_tokens SET post_mode='disabled', force_trending=0 WHERE mint=?", (mint,)); await conn.commit(); await conn.close(); await msg.reply('✅ Token disabled.')

@router.message(Command('enabletoken'))
async def enabletoken(msg: Message, command: CommandObject, db: DB):
    if not await _ensure_owner(msg): return
    if not command.args: return await msg.reply('Usage:\n<code>/enabletoken MINT</code>', parse_mode='HTML')
    mint = command.args.strip().split()[0]; await _upsert_tracked_token(db, mint); conn = await db.connect(); await conn.execute("UPDATE tracked_tokens SET post_mode='channel' WHERE mint=?", (mint,)); await conn.commit(); await conn.close(); await msg.reply('✅ Token enabled for channel posting.')

@router.message(Command('setglobalad'))
async def setglobalad(msg: Message, command: CommandObject, db: DB):
    if not await _ensure_owner(msg): return
    if not command.args: return await msg.reply('Usage:\n<code>/setglobalad your ad text</code>', parse_mode='HTML')
    conn = await db.connect(); ads = AdsService(conn); await ads.set_owner_fallback(command.args.strip()); await conn.close(); await msg.reply('✅ Fallback ad text updated.')

@router.message(Command('listads'))
async def listads(msg: Message, db: DB):
    if not await _ensure_owner(msg): return
    conn = await db.connect(); cur = await conn.execute("SELECT id, text, link, start_ts, end_ts, kind FROM ads ORDER BY id DESC LIMIT 20"); rows = await cur.fetchall(); await conn.close()
    if not rows: return await msg.reply('No ads found.')
    now = int(time.time()); lines = []
    for r in rows:
        status = 'active' if r['start_ts'] <= now <= r['end_ts'] else ('upcoming' if now < r['start_ts'] else 'ended')
        lines.append(f"#{r['id']} [{status}] {r['kind']} — {r['text'][:40]}")
    await msg.reply('Ads:\n' + '\n'.join(lines))

@router.message(Command('addad'))
async def addad(msg: Message, command: CommandObject, db: DB):
    if not await _ensure_owner(msg): return
    if not command.args or '|' not in command.args: return await msg.reply('Usage:\n<code>/addad text|https://t.me/link|days</code>', parse_mode='HTML')
    parts = [x.strip() for x in command.args.strip().split('|')]
    if len(parts) < 3: return await msg.reply('Usage:\n<code>/addad text|https://t.me/link|days</code>', parse_mode='HTML')
    text_ad, link, days_s = parts[0], _norm_tg(parts[1]), parts[2]
    try: days = max(1, int(days_s))
    except Exception: return await msg.reply('❌ Days must be a number.')
    start_ts = int(time.time()); end_ts = start_ts + days * 86400; conn = await db.connect(); ads = AdsService(conn); tx_sig = f"owner_ad_{start_ts}_{msg.from_user.id}"; await ads.create_ad(int(msg.from_user.id), text_ad, link, start_ts, end_ts, tx_sig, 0.0, kind='ad'); await conn.close(); await msg.reply(f'✅ Ad created for {days} day(s).')

@router.message(Command('deletead'))
async def deletead(msg: Message, command: CommandObject, db: DB):
    if not await _ensure_owner(msg): return
    if not command.args: return await msg.reply('Usage:\n<code>/deletead ID</code>', parse_mode='HTML')
    try: ad_id = int(command.args.strip().split()[0])
    except Exception: return await msg.reply('❌ Invalid ad ID.')
    conn = await db.connect(); await conn.execute("DELETE FROM ads WHERE id=?", (ad_id,)); await conn.commit(); changes = conn.total_changes; await conn.close(); await msg.reply('✅ Ad deleted.' if changes else '❌ Ad not found.')

@router.message(Command('status'))
async def status(msg: Message, db: DB):
    if not await _ensure_owner(msg): return
    conn = await db.connect()
    cur = await conn.execute("SELECT COUNT(*) FROM tracked_tokens"); tokens = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*) FROM invoices WHERE status='pending'"); pending = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*) FROM tracked_tokens WHERE post_mode='channel'"); enabled = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*) FROM tracked_tokens WHERE force_trending=1 OR trend_until_ts>?", (int(time.time()),)); trending = (await cur.fetchone())[0]
    await conn.close(); await msg.reply(f'Tracked tokens: {tokens}\nChannel enabled: {enabled}\nTrending forced/live: {trending}\nPending invoices: {pending}')


@router.message(StateFilter('*'), Command('ca'))
async def token_contract_reply_cmd(msg: Message, db: DB):
    if msg.chat.type not in {"group", "supergroup"}:
        return
    conn = await db.connect()
    cur = await conn.execute("SELECT token_mint, COALESCE(NULLIF(symbol,''), NULLIF(name,''), token_mint) AS label FROM group_settings LEFT JOIN tracked_tokens ON tracked_tokens.mint=group_settings.token_mint WHERE group_id=? AND is_active=1 ORDER BY group_settings.id DESC LIMIT 1", (msg.chat.id,))
    row = await cur.fetchone()
    await conn.close()
    if not row:
        return await msg.reply('No token added for this group yet.')
    await msg.reply(f"Symbol: {row['label']}\n{row['token_mint']}")

@router.message(StateFilter("*"), F.text.func(lambda t: bool(t and t.strip().lower() in {"ca", "contract", "address"})))
async def token_contract_reply(msg: Message, db: DB):
    if msg.chat.type not in {"group", "supergroup"}:
        return
    conn = await db.connect()
    cur = await conn.execute("SELECT token_mint, COALESCE(NULLIF(symbol,''), NULLIF(name,''), token_mint) AS label FROM group_settings LEFT JOIN tracked_tokens ON tracked_tokens.mint=group_settings.token_mint WHERE group_id=? AND is_active=1 ORDER BY group_settings.id DESC LIMIT 1", (msg.chat.id,))
    row = await cur.fetchone()
    await conn.close()
    if not row:
        return await msg.reply('No token added for this group yet.')
    await msg.reply(f"Symbol: {row['label']}\n{row['token_mint']}")

@router.message()
async def txhash_fallback(msg: Message, state: FSMContext, db: DB, rpc: TonAPI):
    text = (msg.text or '').strip()
    if _is_ca_query_text(text):
        if await _reply_group_ca(msg, db):
            return
    if len(text) < 20 or ' ' in text or text.startswith('/'):
        return
    invoice_id = await _latest_pending_invoice_for_user(db, msg.from_user.id)
    if not invoice_id:
        return
    sig = _extract_tx_sig(text)
    conn = await db.connect(); cur = await conn.execute("SELECT status, amount_sol, memo FROM invoices WHERE id=?", (invoice_id,)); inv = await cur.fetchone(); await conn.close()
    if not inv or inv['status'] == 'paid':
        return
    used = await _used_signatures(db)
    if sig in used:
        return await msg.answer('This transaction hash was already used.')
    await msg.answer('Checking transaction hash...')
    res = await verify_ton_transfer(rpc, sig, settings.PAYMENT_WALLET, float(inv['amount_sol']), expected_memo=inv['memo'])
    if not res.ok or not res.signature:
        return await msg.answer(f'❌ Payment not detected. {res.reason}')
    if await _activate_invoice(db, int(invoice_id), res.signature, res.amount_ton):
        await msg.answer(await _activation_notice(db, int(invoice_id)))
    else:
        await msg.answer('✅ Already paid.')
