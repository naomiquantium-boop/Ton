from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup
from urllib.parse import quote
from bot.config import settings


def _buy_url(mint: str, dex: str | None = None) -> str:
    d = (dex or "").lower()
    if "dedust" in d:
        return settings.BUY_URL_DEDUST.format(mint=mint)
    return settings.BUY_URL_STONFI.format(mint=mint)


def buy_kb(mint: str, dex: str | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Buy", url=_buy_url(mint, dex))
    kb.button(text="Book Trending", url=settings.BOOK_TRENDING_URL)
    kb.adjust(2)
    return kb.as_markup()


def leaderboard_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Listing", url=settings.LISTING_URL)
    return kb.as_markup()


def main_menu_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🇺🇸 Language", callback_data="menu:lang")
    kb.button(text="✏️ Edit", callback_data="menu:edit")
    kb.button(text="➕ Add Token", callback_data="menu:add")
    kb.button(text="👀 View Tokens", callback_data="menu:view")
    kb.button(text="⚙️ Group Settings", callback_data="menu:group")
    kb.button(text="📈 Trending", callback_data="menu:trending")
    kb.button(text="💎 Ads", callback_data="menu:advert")
    kb.adjust(2, 2, 2, 1)
    return kb.as_markup()


def lang_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🇺🇸 English ✅", callback_data="lang:set:english")
    kb.button(text="🇷🇺 Russian", callback_data="lang:set:russian")
    kb.adjust(2)
    return kb.as_markup()


def token_list_kb(tokens: list[tuple[str, str]], prefix: str, back: str = "menu:home") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for mint, label in tokens:
        kb.button(text=f"✏️ {label}", callback_data=f"{prefix}:{mint}")
    kb.button(text="⬅️ Back", callback_data=back)
    kb.adjust(1)
    return kb.as_markup()


def token_edit_page_kb(mint: str, page: int, values: dict | None = None) -> InlineKeyboardMarkup:
    values = values or {}
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Page 1", callback_data=f"editpage:{mint}:1")
    rows = [
        ("ℹ️ Buy Step", "buy_step", f"✏️ ({values.get('buy_step', 1)})"),
        ("ℹ️ Min Buy", "min_buy", f"✏️ ({values.get('min_buy', 0)})"),
        ("ℹ️ Link", "link", "✏️ (set)" if values.get('telegram_link') else "✏️ ()"),
        ("ℹ️ Emoji", "emoji", f"✏️ ({values.get('emoji', '🟢')})"),
        ("ℹ️ Media", "media", "✏️ (📸)" if values.get('media_file_id') else "✏️ ()"),
    ]
    for left, key, right in rows:
        kb.button(text=left, callback_data=f"editset:{mint}:{key}")
        kb.button(text=right, callback_data=f"editset:{mint}:{key}")
    kb.button(text="⬅️ Back", callback_data="menu:home")
    kb.adjust(1, 2, 2, 2, 2, 2, 1)
    return kb.as_markup()


def trending_slot_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="TOP3", callback_data="trendslot:top3")
    kb.button(text="TOP10", callback_data="trendslot:top10")
    kb.button(text="⬅️ Back", callback_data="menu:home")
    kb.adjust(2, 1)
    return kb.as_markup()


def trending_duration_kb(slot_name: str) -> InlineKeyboardMarkup:
    plans = {
        "top3": [("2h", "2h — 7 TON"), ("4h", "4h — 14 TON"), ("8h", "8h — 21 TON"), ("24h", "24h — 35 TON")],
        "top10": [("2h", "2h — 5 TON"), ("4h", "4h — 10 TON"), ("8h", "8h — 17 TON"), ("24h", "24h — 30 TON")],
    }
    kb = InlineKeyboardBuilder()
    for key, label in plans.get(slot_name, []):
        kb.button(text=label, callback_data=f"trenddur:{slot_name}:{key}")
    kb.button(text="⬅️ Back", callback_data="menu:trending")
    kb.adjust(1)
    return kb.as_markup()


def advert_duration_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for key, label in [("1d", "1day — 10 TON"), ("3d", "3days — 25 TON"), ("7d", "7days — 60 TON")]:
        kb.button(text=label, callback_data=f"adpkg:{key}")
    kb.button(text="⬅️ Back", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()


def invoice_kb(invoice_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Verify Payment", callback_data=f"invoice:paid:{invoice_id}")
    kb.button(text="⬅️ Back Home", callback_data="menu:home")
    kb.adjust(1)
    return kb.as_markup()
