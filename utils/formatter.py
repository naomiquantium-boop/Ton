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

def _compact_checks(count: int = 12) -> str:
    return " ".join(["✅"] * max(1, count))

def _strength_count(spent_ton: float) -> int:
    try:
        return max(3, min(26, int(round(float(spent_ton) / 2.5))))
    except Exception:
        return 12

def build_buy_message_group(token_symbol, emoji, spent_sol, spent_usd, spent_symbol="TON", spent_value=None, got_tokens=0.0, buyer="Unknown", tx_url=None, price_usd=None, mcap_usd=None, tg_url=None, ad_text=None, ad_link=None, chart_url=None, **kwargs) -> str:
    title = f'<b><a href="{_norm_url(tg_url) or _norm_url(chart_url) or _norm_url(tx_url) or ""}">{token_symbol}</a> Buy!</b>' if (_norm_url(tg_url) or _norm_url(chart_url) or _norm_url(tx_url)) else f'<b>{token_symbol} Buy!</b>'
    display_value = spent_value if spent_value is not None else spent_sol
    usd_part = f" (${fmt_num(spent_usd, 2)})" if spent_usd and spent_usd > 0 else ""
    buyer_short = short_addr(str(buyer))
    buyer_part = _a(buyer_short, tx_url)
    lines = [title, "", emoji_bar(emoji or "🟢", _strength_count(float(display_value or 0))), ""]
    lines.append(f"💵 {fmt_num(float(display_value or 0), 2)} {spent_symbol}{usd_part}")
    lines.append(f"🔁 {fmt_num(float(got_tokens or 0), 2)} {_a(token_symbol, tg_url)}")
    lines.append(f"👤 {buyer_part} | {_a('Txn', tx_url)}")
    if price_usd is not None:
        lines.append(f"🏷 Price: ${fmt_num(float(price_usd), 6)}")
    if mcap_usd is not None:
        lines.append(f"📊 MarketCap: ${fmt_num(float(mcap_usd), 0)}")
    lines.append("")
    lines.append(f'🤍 {_a("Listing", settings.LISTING_URL)} | 📈 {_a("Chart", chart_url or tx_url)}')
    lines.append("")
    lines.append(_ad_line(ad_text, ad_link))
    return "\n".join(lines)

def build_buy_message_channel(token_symbol, emoji, spent_sol, spent_usd, spent_symbol="TON", spent_value=None, got_tokens=0.0, buyer="Unknown", tx_url=None, price_usd=None, mcap_usd=None, tg_url=None, ad_text=None, ad_link=None, chart_url=None, **kwargs) -> str:
    title_link = _norm_url(tg_url) or _norm_url(chart_url) or _norm_url(tx_url)
    header = f'🪐 <a href="{title_link}">{token_symbol}</a> Buy!' if title_link else f'🪐 {token_symbol} Buy!'
    display_value = spent_value if spent_value is not None else spent_sol
    usd_part = f" (${fmt_num(spent_usd, 2)})" if spent_usd and spent_usd > 0 else ""
    lines = [header, "", _compact_checks(_strength_count(float(display_value or 0))), ""]
    lines.append(f"💵 {fmt_num(float(display_value or 0), 2)} {spent_symbol}{usd_part}")
    lines.append(f"🔁 {fmt_num(float(got_tokens or 0), 2)} {_a(token_symbol, tg_url)}")
    lines.append(f"👤 {_a(short_addr(str(buyer)), tx_url)} | {_a('Txn', tx_url)}")
    if price_usd is not None:
        lines.append(f"🏷 Price: ${fmt_num(float(price_usd), 6)}")
    if mcap_usd is not None:
        lines.append(f"📊 MarketCap: ${fmt_num(float(mcap_usd), 0)}")
    lines.append("")
    lines.append(f'🤍 {_a("Listing", settings.LISTING_URL)} | 📈 {_a("Chart", chart_url or tx_url)}')
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
