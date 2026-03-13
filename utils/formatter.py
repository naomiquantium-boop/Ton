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

def fmt_num(x: float, decimals: int = 2) -> str:
    try:
        return f"{x:,.{decimals}f}"
    except Exception:
        return str(x)

def _fmt_compact_int(n: Optional[int]) -> str:
    if n is None:
        return "—"
    try:
        x = float(n)
    except Exception:
        return "—"
    if x >= 1_000_000:
        return f"{x/1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
    if x >= 1_000:
        return f"{x/1_000:.2f}".rstrip("0").rstrip(".") + "K"
    return f"{int(x):,}"

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

def _checks(count: int = 26) -> str:
    return " ".join(["✅"] * max(1, count))

def _strength_count(spent_ton: float) -> int:
    try:
        return max(4, min(26, int(round(float(spent_ton) / 4.0))))
    except Exception:
        return 12

def _buy_style(token_symbol, spent_value, spent_usd, got_tokens, buyer, tx_url, price_usd=None, liquidity_usd=None, mcap_usd=None, holders=None, tg_url=None, ad_text=None, ad_link=None, chart_url=None, include_holders=False):
    title = token_symbol or 'TOKEN'
    header = f'| <a href="{_norm_url(tg_url) or _norm_url(chart_url) or _norm_url(tx_url) or ""}"><b>{title}</b></a> Buy!' if (_norm_url(tg_url) or _norm_url(chart_url) or _norm_url(tx_url)) else f'| <b>{title}</b> Buy!'
    usd_part = f" (${fmt_num(spent_usd, 2)})" if spent_usd and spent_usd > 0 else ""
    buyer_short = short_addr(str(buyer))
    buyer_html = _a(buyer_short, tx_url)
    token_html = _a(token_symbol, tg_url) if token_symbol else token_symbol
    lines = [header, '', _checks(_strength_count(float(spent_value or 0))), '']
    lines.append(f'◈ <b>{fmt_num(float(spent_value or 0), 2)} TON{usd_part}</b>')
    lines.append(f'🔁 <b>{fmt_num(float(got_tokens or 0), 2)} {token_html}</b>')
    if include_holders and holders is not None:
        lines.append(f'🔁 {_fmt_compact_int(int(holders))} Holders')
    lines.append(f'👤 {buyer_html} | {_a("Txn", tx_url)}')
    if price_usd is not None:
        lines.append(f'💵 Price: ${fmt_num(float(price_usd), 6)}')
    if liquidity_usd is not None:
        lines.append(f'💧 Liquidity: ${fmt_num(float(liquidity_usd), 0)}')
    if mcap_usd is not None:
        lines.append(f'💵 MCap: ${fmt_num(float(mcap_usd), 0)}')
    link_parts = [_a('TX', tx_url), _a('GT', chart_url), _a('DexS', chart_url), _a('Telegram', tg_url), _a('Trending', settings.BOOK_TRENDING_URL)]
    lines += ['', ' | '.join([p for p in link_parts if p]), '', _ad_line(ad_text, ad_link)]
    RETURN_PLACEHOLDER

def build_buy_message_group(token_symbol, emoji, spent_sol, spent_usd, spent_symbol="TON", spent_value=None, got_tokens=0.0, buyer="Unknown", tx_url=None, price_usd=None, mcap_usd=None, tg_url=None, ad_text=None, ad_link=None, chart_url=None, liquidity_usd=None, holders=None, **kwargs) -> str:
    display_value = spent_value if spent_value is not None else spent_sol
    return _buy_style(token_symbol, display_value, spent_usd, got_tokens, buyer, tx_url, price_usd=price_usd, liquidity_usd=liquidity_usd, mcap_usd=mcap_usd, holders=holders, tg_url=tg_url, ad_text=ad_text, ad_link=ad_link, chart_url=chart_url, include_holders=True)

def build_buy_message_channel(token_symbol, emoji, spent_sol, spent_usd, spent_symbol="TON", spent_value=None, got_tokens=0.0, buyer="Unknown", tx_url=None, price_usd=None, mcap_usd=None, tg_url=None, ad_text=None, ad_link=None, chart_url=None, liquidity_usd=None, holders=None, **kwargs) -> str:
    display_value = spent_value if spent_value is not None else spent_sol
    return _buy_style(token_symbol, display_value, spent_usd, got_tokens, buyer, tx_url, price_usd=price_usd, liquidity_usd=liquidity_usd, mcap_usd=mcap_usd, holders=holders, tg_url=tg_url, ad_text=ad_text, ad_link=ad_link, chart_url=chart_url, include_holders=True)

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
    RETURN_PLACEHOLDER
