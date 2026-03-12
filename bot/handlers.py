from __future__ import annotations
import time
from types import SimpleNamespace
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import settings
from bot.i18n import t
from bot.keyboards import (
    main_menu_kb, language_kb, source_kb, token_list_kb,
    edit_token_kb, durations_kb, invoice_kb,
)
from services.ads_service import AdsService

router = Router(name='handlers')


class AddTokenFlow(StatesGroup):
    token_address = State()
    source = State()
    watch_address = State()
    telegram_link = State()
    chart_link = State()
    listing_link = State()


class EditFlow(StatesGroup):
    value = State()


class AdvertFlow(StatesGroup):
    pick_token = State()
    link = State()
    text = State()
    duration = State()


class TrendingFlow(StatesGroup):
    pick_token = State()
    link = State()
    duration = State()


class InvoiceFlow(StatesGroup):
    tx_hash = State()


def is_owner(message_or_query) -> bool:
    user = message_or_query.from_user.id if getattr(message_or_query, 'from_user', None) else 0
    return int(user) == int(settings.OWNER_ID)


async def get_lang(db, user_id: int) -> str:
    conn = await db.connect()
    try:
        cur = await conn.execute('SELECT language FROM user_prefs WHERE user_id=?', (user_id,))
        row = await cur.fetchone()
        return row['language'] if row else 'en'
    finally:
        await conn.close()


async def set_lang(db, user_id: int, lang: str):
    conn = await db.connect()
    try:
        await conn.execute('INSERT INTO user_prefs(user_id, language) VALUES(?, ?) ON CONFLICT(user_id) DO UPDATE SET language=excluded.language', (user_id, lang))
        await conn.commit()
    finally:
        await conn.close()


@router.message(CommandStart())
async def start(msg: Message, db, state: FSMContext):
    await state.clear()
    lang = await get_lang(db, msg.from_user.id)
    await msg.answer(t(lang, 'main_menu'), reply_markup=main_menu_kb(lang, owner=is_owner(msg)))


@router.callback_query(F.data == 'menu:home')
async def home(cb: CallbackQuery, db):
    lang = await get_lang(db, cb.from_user.id)
    await cb.message.answer(t(lang, 'main_menu'), reply_markup=main_menu_kb(lang, owner=is_owner(cb)))
    await cb.answer()


@router.callback_query(F.data == 'menu:language')
async def language_menu(cb: CallbackQuery, db):
    lang = await get_lang(db, cb.from_user.id)
    await cb.message.answer(t(lang, 'choose_language'), reply_markup=language_kb())
    await cb.answer()


@router.callback_query(F.data.startswith('lang:'))
async def save_language(cb: CallbackQuery, db):
    lang = cb.data.split(':', 1)[1]
    await set_lang(db, cb.from_user.id, lang)
    await cb.message.answer(t(lang, 'lang_saved'), reply_markup=main_menu_kb(lang, owner=is_owner(cb)))
    await cb.answer()


@router.callback_query(F.data == 'menu:add')
async def menu_add(cb: CallbackQuery, db, state: FSMContext):
    lang = await get_lang(db, cb.from_user.id)
    await state.set_state(AddTokenFlow.token_address)
    await cb.message.answer(t(lang, 'send_token_address'))
    await cb.answer()


@router.message(AddTokenFlow.token_address)
async def add_token_address(msg: Message, db, state: FSMContext):
    lang = await get_lang(db, msg.from_user.id)
    await state.update_data(token_address=msg.text.strip())
    await state.set_state(AddTokenFlow.source)
    await msg.answer(t(lang, 'choose_source'), reply_markup=source_kb())


@router.callback_query(F.data.startswith('source:'), AddTokenFlow.source)
async def add_token_source(cb: CallbackQuery, db, state: FSMContext):
    lang = await get_lang(db, cb.from_user.id)
    source = cb.data.split(':', 1)[1]
    await state.update_data(source=source)
    await state.set_state(AddTokenFlow.watch_address)
    await cb.message.answer(t(lang, 'send_watch_address'))
    await cb.answer()


@router.message(AddTokenFlow.watch_address)
async def add_watch_address(msg: Message, db, state: FSMContext):
    lang = await get_lang(db, msg.from_user.id)
    await state.update_data(watch_address=msg.text.strip())
    await state.set_state(AddTokenFlow.telegram_link)
    await msg.answer(t(lang, 'send_telegram_link'))


@router.message(AddTokenFlow.telegram_link)
async def add_telegram(msg: Message, db, state: FSMContext):
    lang = await get_lang(db, msg.from_user.id)
    val = None if msg.text.lower() == 'skip' else msg.text.strip()
    await state.update_data(telegram_link=val)
    await state.set_state(AddTokenFlow.chart_link)
    await msg.answer(t(lang, 'send_chart_link'))


@router.message(AddTokenFlow.chart_link)
async def add_chart(msg: Message, db, state: FSMContext):
    lang = await get_lang(db, msg.from_user.id)
    val = None if msg.text.lower() == 'skip' else msg.text.strip()
    await state.update_data(chart_link=val)
    await state.set_state(AddTokenFlow.listing_link)
    await msg.answer(t(lang, 'send_listing_link'))


@router.message(AddTokenFlow.listing_link)
async def add_listing(msg: Message, db, state: FSMContext):
    lang = await get_lang(db, msg.from_user.id)
    val = None if msg.text.lower() == 'skip' else msg.text.strip()
    data = await state.get_data()
    now = int(time.time())
    conn = await db.connect()
    try:
        await conn.execute(
            '''INSERT INTO tracked_tokens(token_address, source, watch_address, name, symbol, telegram_link, chart_link, listing_link, buy_link, created_at, updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(token_address) DO UPDATE SET source=excluded.source, watch_address=excluded.watch_address, telegram_link=excluded.telegram_link, chart_link=excluded.chart_link, listing_link=excluded.listing_link, updated_at=excluded.updated_at''',
            (data['token_address'], data['source'], data['watch_address'], data['token_address'][:8], data['token_address'][:6], data.get('telegram_link'), data.get('chart_link'), val, settings.BUY_URL_TEMPLATE, now, now),
        )
        await conn.execute('INSERT INTO token_settings(token_address) VALUES(?) ON CONFLICT(token_address) DO NOTHING', (data['token_address'],))
        await conn.commit()
    finally:
        await conn.close()
    await state.clear()
    await msg.answer(t(lang, 'token_added', symbol=data['token_address'][:6]), reply_markup=main_menu_kb(lang, owner=is_owner(msg)))


@router.callback_query(F.data == 'menu:view')
@router.callback_query(F.data == 'menu:edit')
async def menu_tokens(cb: CallbackQuery, db):
    lang = await get_lang(db, cb.from_user.id)
    action = 'edit' if cb.data.endswith('edit') else 'show'
    conn = await db.connect()
    try:
        cur = await conn.execute('SELECT token_address, symbol, name FROM tracked_tokens ORDER BY updated_at DESC')
        rows = await cur.fetchall()
    finally:
        await conn.close()
    if not rows:
        await cb.message.answer(t(lang, 'no_tokens'))
    else:
        await cb.message.answer(t(lang, 'select_token'), reply_markup=token_list_kb(rows, 'edit' if action == 'edit' else 'pick'))
    await cb.answer()


@router.callback_query(F.data.startswith('edit:'))
async def open_edit(cb: CallbackQuery, db):
    lang = await get_lang(db, cb.from_user.id)
    token_address = cb.data.split(':', 2)[2]
    await cb.message.answer('Customize your Token', reply_markup=edit_token_kb(lang, token_address))
    await cb.answer()


@router.callback_query(F.data.startswith('editv:'))
async def prompt_edit_value(cb: CallbackQuery, db, state: FSMContext):
    _, field, token_address = cb.data.split(':', 2)
    await state.set_state(EditFlow.value)
    await state.update_data(edit_field=field, token_address=token_address)
    prompts = {
        'buy_step': 'Send buy step.',
        'min_buy': 'Send minimum buy in TON.',
        'link': 'Send Telegram link.',
        'emoji': 'Send one emoji.',
        'media': 'Send photo/video/animation or type skip.',
    }
    await cb.message.answer(prompts.get(field, 'Send value.'))
    await cb.answer()


@router.message(EditFlow.value)
async def save_edit_value(msg: Message, db, state: FSMContext):
    data = await state.get_data()
    field = data['edit_field']
    token_address = data['token_address']
    conn = await db.connect()
    try:
        if field == 'buy_step':
            await conn.execute('UPDATE token_settings SET buy_step=? WHERE token_address=?', (float(msg.text.strip()), token_address))
        elif field == 'min_buy':
            await conn.execute('UPDATE token_settings SET min_buy_ton=? WHERE token_address=?', (float(msg.text.strip()), token_address))
        elif field == 'link':
            await conn.execute('UPDATE tracked_tokens SET telegram_link=?, updated_at=? WHERE token_address=?', (msg.text.strip(), int(time.time()), token_address))
        elif field == 'emoji':
            await conn.execute('UPDATE token_settings SET emoji=? WHERE token_address=?', (msg.text.strip(), token_address))
        elif field == 'media':
            file_id = None
            kind = 'photo'
            if msg.photo:
                file_id = msg.photo[-1].file_id
                kind = 'photo'
            elif msg.video:
                file_id = msg.video.file_id
                kind = 'video'
            elif msg.animation:
                file_id = msg.animation.file_id
                kind = 'animation'
            elif msg.text and msg.text.lower() == 'skip':
                file_id = None
                kind = 'photo'
            await conn.execute('UPDATE token_settings SET media_file_id=?, media_kind=? WHERE token_address=?', (file_id, kind, token_address))
        await conn.commit()
    finally:
        await conn.close()
    await state.clear()
    lang = await get_lang(db, msg.from_user.id)
    await msg.answer(t(lang, 'token_updated'), reply_markup=main_menu_kb(lang, owner=is_owner(msg)))


@router.callback_query(F.data == 'menu:trending')
async def menu_trending(cb: CallbackQuery, db, state: FSMContext):
    lang = await get_lang(db, cb.from_user.id)
    conn = await db.connect()
    try:
        cur = await conn.execute('SELECT token_address, symbol, name FROM tracked_tokens WHERE is_active=1 ORDER BY updated_at DESC')
        rows = await cur.fetchall()
    finally:
        await conn.close()
    await state.set_state(TrendingFlow.pick_token)
    await cb.message.answer(t(lang, 'select_token'), reply_markup=token_list_kb(rows, 'trendpick'))
    await cb.answer()


@router.callback_query(F.data.startswith('trendpick:'), TrendingFlow.pick_token)
async def trend_pick(cb: CallbackQuery, db, state: FSMContext):
    lang = await get_lang(db, cb.from_user.id)
    token_address = cb.data.split(':', 1)[1]
    await state.update_data(token_address=token_address)
    await state.set_state(TrendingFlow.link)
    await cb.message.answer(t(lang, 'send_ad_link'))
    await cb.answer()


@router.message(TrendingFlow.link)
async def trend_link(msg: Message, db, state: FSMContext):
    lang = await get_lang(db, msg.from_user.id)
    await state.update_data(target_link=msg.text.strip())
    await state.set_state(TrendingFlow.duration)
    await msg.answer('Choose your Trending package.', reply_markup=durations_kb('trending', lang))


@router.callback_query(F.data.startswith('duration:trending:'), TrendingFlow.duration)
async def trend_duration(cb: CallbackQuery, db, state: FSMContext, payment_verifier):
    lang = await get_lang(db, cb.from_user.id)
    key = cb.data.split(':')[2]
    amount = settings.TRENDING_PRICES[key]
    data = await state.get_data()
    invoice_id = await payment_verifier.create_invoice(cb.from_user.id, data['token_address'], 'trending', key, amount, target_link=data.get('target_link'))
    await state.clear()
    await state.set_state(InvoiceFlow.tx_hash)
    await state.update_data(invoice_id=invoice_id)
    text = f"{t(lang,'invoice_title')}\n\n{t(lang,'paying_for', kind='Trending')}\n\n{t(lang,'wallet')}:\n{settings.MERCHANT_WALLET}\n{t(lang,'wallet_balance')}: 0 TON\n\n{t(lang,'please_send', amount=f'{amount:g}')}"
    await cb.message.answer(text, reply_markup=invoice_kb(amount, lang))
    await cb.message.answer(t(lang, 'send_tx_hash'))
    await cb.answer()


@router.callback_query(F.data == 'menu:advert')
async def menu_advert(cb: CallbackQuery, db, state: FSMContext):
    lang = await get_lang(db, cb.from_user.id)
    conn = await db.connect()
    try:
        cur = await conn.execute('SELECT token_address, symbol, name FROM tracked_tokens WHERE is_active=1 ORDER BY updated_at DESC')
        rows = await cur.fetchall()
    finally:
        await conn.close()
    await state.set_state(AdvertFlow.pick_token)
    await cb.message.answer(t(lang, 'select_token'), reply_markup=token_list_kb(rows, 'adpick'))
    await cb.answer()


@router.callback_query(F.data.startswith('adpick:'), AdvertFlow.pick_token)
async def ad_pick(cb: CallbackQuery, db, state: FSMContext):
    lang = await get_lang(db, cb.from_user.id)
    await state.update_data(token_address=cb.data.split(':',1)[1])
    await state.set_state(AdvertFlow.link)
    await cb.message.answer(t(lang, 'send_ad_link'))
    await cb.answer()


@router.message(AdvertFlow.link)
async def ad_link(msg: Message, db, state: FSMContext):
    lang = await get_lang(db, msg.from_user.id)
    await state.update_data(target_link=msg.text.strip())
    await state.set_state(AdvertFlow.text)
    await msg.answer(t(lang, 'send_ad_text'))


@router.message(AdvertFlow.text)
async def ad_text(msg: Message, db, state: FSMContext):
    lang = await get_lang(db, msg.from_user.id)
    await state.update_data(ad_text=msg.text.strip())
    await state.set_state(AdvertFlow.duration)
    await msg.answer('How many days should this advert run?', reply_markup=durations_kb('advert', lang))


@router.callback_query(F.data.startswith('duration:advert:'), AdvertFlow.duration)
async def ad_duration(cb: CallbackQuery, db, state: FSMContext, payment_verifier):
    lang = await get_lang(db, cb.from_user.id)
    key = cb.data.split(':')[2]
    amount = settings.AD_PRICES[key]
    data = await state.get_data()
    invoice_id = await payment_verifier.create_invoice(cb.from_user.id, data['token_address'], 'advert', key, amount, target_link=data.get('target_link'), ad_text=data.get('ad_text'), ad_link=data.get('target_link'))
    await state.clear()
    await state.set_state(InvoiceFlow.tx_hash)
    await state.update_data(invoice_id=invoice_id)
    text = f"{t(lang,'invoice_title')}\n\n{t(lang,'paying_for', kind='Advert')}\n\n{t(lang,'wallet')}:\n{settings.MERCHANT_WALLET}\n{t(lang,'wallet_balance')}: 0 TON\n\n{t(lang,'please_send', amount=f'{amount:g}')}"
    await cb.message.answer(text, reply_markup=invoice_kb(amount, lang))
    await cb.message.answer(t(lang, 'send_tx_hash'))
    await cb.answer()


@router.message(InvoiceFlow.tx_hash)
async def verify_tx_hash(msg: Message, db, state: FSMContext, payment_verifier):
    data = await state.get_data()
    invoice_id = data.get('invoice_id')
    lang = await get_lang(db, msg.from_user.id)
    await msg.answer(t(lang, 'checking_tx'))
    ok, detail = await payment_verifier.verify_invoice(invoice_id, msg.text.strip())
    if ok:
        conn = await db.connect()
        try:
            cur = await conn.execute('SELECT * FROM invoices WHERE id=?', (invoice_id,))
            invoice = await cur.fetchone()
            if invoice['kind'] == 'trending':
                hours_map = {'1h': 3600, '3h': 3*3600, '6h': 6*3600, '9h': 9*3600, '12h': 12*3600, '24h': 24*3600}
                await conn.execute('UPDATE tracked_tokens SET force_trending=1, trend_until_ts=? WHERE token_address=?', (int(time.time()) + hours_map.get(invoice['duration_key'], 3600), invoice['token_address']))
            else:
                days_map = {'1d': 86400, '3d': 3*86400, '7d': 7*86400}
                await conn.execute('INSERT INTO ads(token_address, text, link, starts_at, ends_at, is_active, created_by) VALUES(?,?,?,?,?,?,?)', (invoice['token_address'], invoice['ad_text'] or settings.DEFAULT_AD_TEXT, invoice['ad_link'], int(time.time()), int(time.time()) + days_map.get(invoice['duration_key'], 86400), 1, msg.from_user.id))
            await conn.commit()
        finally:
            await conn.close()
        await state.clear()
        await msg.answer(t(lang, 'payment_verified', kind=detail, token='token'), reply_markup=main_menu_kb(lang, owner=is_owner(msg)))
    else:
        await msg.answer(t(lang, 'payment_not_found'))


@router.message(Command('status'))
async def owner_status(msg: Message, db):
    if not is_owner(msg):
        return await msg.reply('Owner only.')
    conn = await db.connect()
    try:
        cur = await conn.execute('SELECT COUNT(*) c FROM tracked_tokens')
        tokens = (await cur.fetchone())['c']
        cur = await conn.execute('SELECT COUNT(*) c FROM invoices WHERE is_paid=0')
        invoices = (await cur.fetchone())['c']
    finally:
        await conn.close()
    lang = await get_lang(db, msg.from_user.id)
    await msg.reply(t(lang, 'status', tokens=tokens, invoices=invoices))


@router.message(Command('whoami'))
async def owner_whoami(msg: Message, db):
    lang = await get_lang(db, msg.from_user.id)
    await msg.reply(t(lang, 'whoami', user_id=msg.from_user.id))


@router.message(Command('setglobalad'))
async def owner_set_global_ad(msg: Message, db):
    if not is_owner(msg):
        return await msg.reply('Owner only.')
    text = (msg.text or '').split(maxsplit=1)
    if len(text) < 2:
        return await msg.reply('Usage: /setglobalad <text>')
    await AdsService(db).set_global_ad(text[1], settings.TRENDING_URL)
    await msg.reply('Global ad updated.')


def _parse_pipes(text: str):
    return [p.strip() for p in text.split('|')]


@router.message(Command('forceadd'))
async def owner_forceadd(msg: Message, db):
    if not is_owner(msg):
        return await msg.reply('Owner only.')
    body = (msg.text or '').split(maxsplit=1)
    if len(body) < 2:
        return await msg.reply('Usage: /forceadd <token_address> | <source> | <watch_address> | <telegram_link optional>')
    parts = _parse_pipes(body[1])
    if len(parts) < 3:
        return await msg.reply('Usage: /forceadd <token_address> | <source> | <watch_address> | <telegram_link optional>')
    token_address, source, watch_address = parts[:3]
    telegram_link = parts[3] if len(parts) > 3 else None
    now = int(time.time())
    conn = await db.connect()
    try:
        await conn.execute('''INSERT INTO tracked_tokens(token_address, source, watch_address, name, symbol, telegram_link, listing_link, buy_link, created_at, updated_at)
                              VALUES(?,?,?,?,?,?,?,?,?,?)
                              ON CONFLICT(token_address) DO UPDATE SET source=excluded.source, watch_address=excluded.watch_address, telegram_link=excluded.telegram_link, updated_at=excluded.updated_at''',
                           (token_address, source, watch_address, token_address[:8], token_address[:6], telegram_link, settings.LISTING_URL, settings.BUY_URL_TEMPLATE, now, now))
        await conn.execute('INSERT INTO token_settings(token_address) VALUES(?) ON CONFLICT(token_address) DO NOTHING', (token_address,))
        await conn.commit()
    finally:
        await conn.close()
    await msg.reply(f'✅ Token added: {token_address[:6]}')


@router.message(Command('forcetrending'))
async def owner_forcetrending(msg: Message, db):
    if not is_owner(msg):
        return await msg.reply('Owner only.')
    body = (msg.text or '').split(maxsplit=1)
    if len(body) < 2:
        return await msg.reply('Usage: /forcetrending <token_address>')
    token_address = body[1].strip().split()[0]
    conn = await db.connect()
    try:
        await conn.execute('UPDATE tracked_tokens SET force_trending=1, trend_until_ts=? WHERE token_address=?', (int(time.time()) + 24*3600, token_address))
        await conn.commit()
    finally:
        await conn.close()
    await msg.reply('Trending forced.')


@router.message(Command('forceleaderboard'))
async def owner_forceleaderboard(msg: Message, db):
    if not is_owner(msg):
        return await msg.reply('Owner only.')
    body = (msg.text or '').split(maxsplit=2)
    if len(body) < 3:
        return await msg.reply('Usage: /forceleaderboard <token_address> <rank>')
    token_address, rank = body[1], int(body[2])
    conn = await db.connect()
    try:
        await conn.execute('UPDATE tracked_tokens SET force_leaderboard=1, manual_rank=? WHERE token_address=?', (rank, token_address))
        await conn.commit()
    finally:
        await conn.close()
    await msg.reply('Leaderboard rank forced.')


@router.message(Command('listads'))
async def owner_listads(msg: Message, db):
    if not is_owner(msg):
        return await msg.reply('Owner only.')
    conn = await db.connect()
    try:
        cur = await conn.execute('SELECT id, text, link, token_address, ends_at FROM ads ORDER BY id DESC LIMIT 20')
        rows = await cur.fetchall()
    finally:
        await conn.close()
    if not rows:
        return await msg.reply('No ads.')
    text = '\n'.join([f"#{r['id']} {r['token_address'] or 'GLOBAL'} — {r['text']}" for r in rows])
    await msg.reply(text)


@router.message(Command('addad'))
async def owner_addad(msg: Message, db):
    if not is_owner(msg):
        return await msg.reply('Owner only.')
    body = (msg.text or '').split(maxsplit=1)
    if len(body) < 2:
        return await msg.reply('Usage: /addad <text> | <link optional> | <days>')
    parts = _parse_pipes(body[1])
    text = parts[0]
    link = parts[1] if len(parts) > 1 else None
    days = int(parts[2]) if len(parts) > 2 else 1
    now = int(time.time())
    conn = await db.connect()
    try:
        await conn.execute('INSERT INTO ads(text, link, starts_at, ends_at, is_active, created_by) VALUES(?,?,?,?,?,?)', (text, link, now, now + days*86400, 1, msg.from_user.id))
        await conn.commit()
    finally:
        await conn.close()
    await msg.reply('Ad added.')


@router.message(Command('deletead'))
async def owner_deletead(msg: Message, db):
    if not is_owner(msg):
        return await msg.reply('Owner only.')
    body = (msg.text or '').split(maxsplit=1)
    if len(body) < 2:
        return await msg.reply('Usage: /deletead <ad_id>')
    conn = await db.connect()
    try:
        await conn.execute('DELETE FROM ads WHERE id=?', (int(body[1]),))
        await conn.commit()
    finally:
        await conn.close()
    await msg.reply('Ad deleted.')


@router.message(Command('removetrending'))
async def owner_remove_trending(msg: Message, db):
    if not is_owner(msg):
        return await msg.reply('Owner only.')
    token_address = (msg.text or '').split(maxsplit=1)[1].strip()
    conn = await db.connect()
    try:
        await conn.execute('UPDATE tracked_tokens SET force_trending=0, trend_until_ts=0 WHERE token_address=?', (token_address,))
        await conn.commit()
    finally:
        await conn.close()
    await msg.reply('Trending removed.')


@router.message(Command('disabletoken'))
@router.message(Command('enabletoken'))
async def owner_toggle_token(msg: Message, db):
    if not is_owner(msg):
        return await msg.reply('Owner only.')
    cmd = msg.text.split()[0]
    token_address = (msg.text or '').split(maxsplit=1)[1].strip()
    active = 0 if 'disable' in cmd else 1
    conn = await db.connect()
    try:
        await conn.execute('UPDATE tracked_tokens SET is_active=? WHERE token_address=?', (active, token_address))
        await conn.commit()
    finally:
        await conn.close()
    await msg.reply('Token updated.')
