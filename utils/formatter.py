from __future__ import annotations
from html import escape


def short_addr(addr: str, head: int = 4, tail: int = 4) -> str:
    if not addr:
        return 'Unknown'
    if len(addr) <= head + tail + 3:
        return addr
    return f'{addr[:head]}...{addr[-tail:]}'


def fmt_num(v: float) -> str:
    if v >= 1_000_000_000:
        return f'{v/1_000_000_000:.0f}B'
    if v >= 1_000_000:
        return f'{v/1_000_000:.0f}M'
    if v >= 1_000:
        return f'{v/1_000:.0f}K'
    if float(v).is_integer():
        return f'{int(v)}'
    return f'{v:,.2f}'


def strength_row(emoji: str, spent_ton: float, step: float) -> str:
    count = max(1, min(24, int(spent_ton / max(step, 0.01))))
    return ''.join([emoji] * count)


def build_channel_post(token: dict, event: dict, settings: dict, ad_text: str, ad_link: str | None, trending_url: str) -> str:
    title = escape(token.get('symbol') or token.get('name') or 'Token')
    token_link = token.get('telegram_link') or ''
    token_title = f'<a href="{escape(token_link)}">{title}</a>' if token_link else title
    wallet_line = f'<a href="{escape(event["wallet_url"])}">{escape(short_addr(event["buyer"]))}</a>: {event.get("position_pct", '0%')} | <a href="{escape(event["tx_url"])}">Txn</a>'
    amount_line = strength_row(settings.get('emoji', '✅'), event['spent_ton'], settings.get('buy_step', 1))
    holders = fmt_num(event.get('holders', 0))
    links = []
    listing = token.get('listing_link')
    if listing:
        links.append(f'💎 <a href="{escape(listing)}">Listing</a>')
    buy_link = token.get('buy_link') or trending_url
    links.append(f'🐸 <a href="{escape(buy_link)}">Buy</a>')
    chart = token.get('chart_link') or event.get('chart_url') or ''
    if chart:
        links.append(f'📊 <a href="{escape(chart)}">Chart</a>')
    ad = f'<a href="{escape(ad_link)}">{escape(ad_text)}</a>' if ad_link else escape(ad_text)
    return (
        f'{token_title} Buy!\n\n'
        f'{amount_line}\n\n'
        f'◭ {event["spent_ton"]:.2f} TON (${event["spent_usd"]:.2f})\n'
        f'🔁 {event["got_tokens"]:,.2f} {title}\n'
        f'🔁 {holders} Holders\n'
        f'👤 {wallet_line}\n'
        f'💵 Price: ${event["price_usd"]:.6f}\n'
        f'💵 MarketCap: ${event["market_cap_usd"]:,.0f}\n\n'
        f'{" | ".join(links)}\n'
        f'ad: {ad}'
    )


def build_group_post(token: dict, event: dict, settings: dict, ad_text: str, ad_link: str | None, trending_url: str) -> str:
    title = escape(token.get('symbol') or token.get('name') or 'Token')
    token_link = token.get('telegram_link') or ''
    token_title = f'<a href="{escape(token_link)}">{title}</a>' if token_link else title
    wallet_line = f'<a href="{escape(event["wallet_url"])}">{escape(short_addr(event["buyer"]))}</a> | <a href="{escape(event["tx_url"])}">Txn</a>'
    amount_line = strength_row(settings.get('emoji', '🦞'), event['spent_ton'], settings.get('buy_step', 1))
    links = [f'<a href="{escape(event["tx_url"])}">TX</a>']
    if token.get('listing_link'):
        links.append(f'<a href="{escape(token["listing_link"])}">GT</a>')
    chart = token.get('chart_link') or event.get('chart_url') or ''
    if chart:
        links.append(f'<a href="{escape(chart)}">DexS</a>')
    if token_link:
        links.append(f'<a href="{escape(token_link)}">Telegram</a>')
    links.append(f'<a href="{escape(trending_url)}">Trending</a>')
    ad = f'<a href="{escape(ad_link)}">{escape(ad_text)}</a>' if ad_link else escape(ad_text)
    return (
        f'{token_title} Buy!\n'
        f'{amount_line}\n\n'
        f'Spent: <b>{event["spent_ton"]:.2f} TON</b>\n'
        f'Got: <b>{event["got_tokens"]:,.2f} {title}</b>\n\n'
        f'{wallet_line}\n\n'
        f'Price: ${event["price_usd"]:.6f}\n'
        f'Liquidity: ${event["liquidity_usd"]:,.0f}\n'
        f'MCap: ${event["market_cap_usd"]:,.0f}\n'
        f'Holders: {fmt_num(event.get("holders", 0))}\n'
        f'{" | ".join(links)}\n\n'
        f'ad: {ad}'
    )


def build_leaderboard(tokens: list[dict], footer: str) -> str:
    lines = ['🟢 SPYTON TRENDING\n']
    for idx, token in enumerate(tokens[:10], 1):
        rank = ['1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣','7️⃣','8️⃣','9️⃣','🔟'][idx-1]
        title = token.get('symbol') or token.get('name') or 'TOKEN'
        mcap = fmt_num(token.get('market_cap_usd', 0))
        change = token.get('trend_change_pct', 0)
        sign = '+' if change > 0 else ''
        token_link = token.get('chart_link') or ''
        title_text = f'<a href="{escape(token_link)}">{escape(title)}</a>' if token_link else escape(title)
        lines.append(f'{rank} {title_text} | {mcap} | {sign}{change:.0f}%')
        if idx == 3:
            lines.append('──────────────')
    lines.append(f'\n<blockquote>{escape(footer)}</blockquote>')
    return '\n'.join(lines)
