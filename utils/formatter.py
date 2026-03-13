from __future__ import annotations
from bot.config import settings
from typing import Optional

RANK_EMOJIS = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣", 9: "9️⃣", 10: "🔟"}

def short_addr(a: str, left: int = 4, right: int = 4) -> str:
    if not a:
        return "Unknown"
    if len(a) <= left + right + 3:
        return a
    return f"{a[:left]}...{a[-right:]}"

def emoji_bar(emoji: str, count: int = 3) -> str:
    return " ".join([emoji] * max(1, count))

def fmt_num(x: float, decimals: int = 2) -> str:
    try:
        return f"{x:,.{decimals}f}"
    except Exception:
        return str(x)

def _fmt_token_amount(x: float) -> str:
    try:
        return f"{float(x):,.2f}"
    except Exception:
        return str(x)

def _fmt_usd(x: float | None, decimals: int = 0) -> str | None:
    if x is None:
        return None
    try:
        return f"${float(x):,.{decimals}f}"
    except Exception:
        return None

def _norm_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    u = url.strip()
    if not u:
        return None
    if u.startswith("@"):
        return f"https://t.me/{u[1:]}"
    if u.startswith("t.me/"):
        return "https://" + u
    if u.startswith("http://"):
        return "https://" + u[len("http://"):]
    return u

def _a(label: str, url: Optional[str]) -> str:
    u = _norm_url(url)
    if not u:
        return label
    return f'<a href="{u}">{label}</a>'

def _default_ad_line() -> str:
    return f'ad: <a href="{settings.BOOK_ADS_URL}">Promote here with SpyTON Ads</a>'

def _ad_line(ad_text: str | None, ad_link: str | None = None) -> str:
    if ad_text and ad_text.strip():
        if ad_link:
            return f'ad: <a href="{_norm_url(ad_link)}">{ad_text}</a>'
        return f"ad: {ad_text}"
    return _default_ad_line()

def _strength_count(spent_ton: float) -> int:
    try:
        return max(3, min(26, int(round(float(spent_ton) / 4))))
    except Exception:
        return 8

def build_buy_message_group(token_symbol, emoji, spent_sol, spent_usd, spent_symbol="TON", spent_value=None, got_tokens=0.0, buyer="Unknown", tx_url=None, price_usd=None, mcap_usd=None, tg_url=None, ad_text=None, ad_link=None, chart_url=None, liquidity_usd=None, holders=None, **kwargs) -> str:
    title_link = _norm_url(tg_url) or _norm_url(chart_url) or _norm_url(tx_url)
    header = f'<a href="{title_link}"><b>{token_symbol}</b></a> Buy!' if title_link else f'<b>{token_symbol}</b> Buy!'
    display_value = float(spent_value if spent_value is not None else spent_sol or 0)
    lines = [header, emoji_bar(emoji or "🟢", _strength_count(display_value)), ""]
    lines.append(f"Spent: <b>{fmt_num(display_value, 2)} {spent_symbol}</b>")
    lines.append(f"Got: <b>{_fmt_token_amount(float(got_tokens or 0))} {token_symbol}</b>")
    lines.append("")
    lines.append(f"{_a(short_addr(str(buyer)), tx_url)} | {_a('Txn', tx_url)}")
    lines.append("")
    if price_usd is not None:
        lines.append(f"Price: {_fmt_usd(price_usd, 6)}")
    if liquidity_usd is not None:
        lines.append(f"Liquidity: {_fmt_usd(liquidity_usd, 0)}")
    if mcap_usd is not None:
        lines.append(f"MCap: {_fmt_usd(mcap_usd, 0)}")
    if holders is not None:
        lines.append(f"Holders: {fmt_num(float(holders), 0)}")
    parts = []
    if tx_url:
        parts.append(_a('TX', tx_url))
    if chart_url:
        parts.append(_a('DexS', chart_url))
    if tg_url:
        parts.append(_a('Telegram', tg_url))
    parts.append(_a('Trending', settings.BOOK_TRENDING_URL))
    lines.append(" | ".join(parts))
    lines.append("")
    lines.append(_ad_line(ad_text, ad_link))
    return "\n".join(lines)

def build_buy_message_channel(token_symbol, emoji, spent_sol, spent_usd, spent_symbol="TON", spent_value=None, got_tokens=0.0, buyer="Unknown", tx_url=None, price_usd=None, mcap_usd=None, tg_url=None, ad_text=None, ad_link=None, chart_url=None, liquidity_usd=None, holders=None, **kwargs) -> str:
    title_link = _norm_url(tg_url) or _norm_url(chart_url) or _norm_url(tx_url)
    header = f'| <a href="{title_link}"><b>{token_symbol}</b></a> Buy!' if title_link else f'| <b>{token_symbol}</b> Buy!'
    display_value = float(spent_value if spent_value is not None else spent_sol or 0)
    usd_part = f" (${fmt_num(spent_usd, 2)})" if spent_usd else ""
    lines = [header, emoji_bar(emoji or "🟢", _strength_count(display_value)), ""]
    lines.append(f"◈ <b>{fmt_num(display_value, 2)} {spent_symbol}{usd_part}</b>")
    lines.append(f"🔁 <b>{_fmt_token_amount(float(got_tokens or 0))} {_a(token_symbol, tg_url)}</b>")
    lines.append(f"👤 {_a(short_addr(str(buyer)), tx_url)} | {_a('Txn', tx_url)}")
    if price_usd is not None:
        lines.append(f"💵 Price: {_fmt_usd(price_usd, 6)}")
    if liquidity_usd is not None:
        lines.append(f"💧 Liquidity: {_fmt_usd(liquidity_usd, 0)}")
    if mcap_usd is not None:
        lines.append(f"💵 MCap: {_fmt_usd(mcap_usd, 0)}")
    if holders is not None:
        lines.append(f"👥 Holders: {fmt_num(float(holders), 0)}")
    parts = []
    if tx_url:
        parts.append(_a('TX', tx_url))
    if chart_url:
        parts.append(_a('GT', chart_url))
        parts.append(_a('DexS', chart_url))
    if tg_url:
        parts.append(_a('Telegram', tg_url))
    parts.append(_a('Trending', settings.BOOK_TRENDING_URL))
    lines.append(" | ".join(parts))
    lines.append("")
    lines.append(_ad_line(ad_text, ad_link))
    return "\n".join(lines)

def build_leaderboard_message(rows: list[tuple], footer_handle: str | None = None) -> str:
    lines = ["🟢 SPYTON TRENDING", ""]
    visible_rows = list(rows[:10])
    for row in visible_rows:
        if len(row) >= 6:
            rank, label, metric, pct, tg_url, chart_url = row[:6]
        else:
            rank, label, metric, pct, chart_url = row[:5]
            tg_url = None
        sign = "+" if pct > 0 else ""
        pct_text = f"{sign}{pct:.1f}%" if abs(pct) < 10 and abs(pct) > 0 else f"{sign}{pct:.0f}%"
        token_part = _a(label, tg_url) if tg_url else label
        metric_part = _a(metric, chart_url or settings.LISTING_URL)
        lines.append(f'{RANK_EMOJIS.get(rank, str(rank))} {token_part} | {metric_part} | {pct_text}')
    lines.append("")
    footer = footer_handle or settings.LEADERBOARD_FOOTER_HANDLE
    lines.append(f"<blockquote>💬 To trend add {footer} in your group</blockquote>")
    return "\n".join(lines)
