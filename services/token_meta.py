from __future__ import annotations
import httpx

DEX_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{mint}"


def _f(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def _dex_priority(name: str) -> int:
    n = (name or "").lower()
    if "ston" in n:
        return 3
    if "dedust" in n:
        return 2
    return 1


async def fetch_token_meta(mint: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as c:
        r = await c.get(DEX_TOKEN_URL.format(mint=mint))
        r.raise_for_status()
        data = r.json()
    pairs = data.get("pairs") or []
    if not pairs:
        return {"name": mint[:6], "symbol": mint[:6], "priceUsd": None, "liquidityUsd": None, "mcapUsd": None, "dexUrl": None, "dexName": None, "buyUrl": None}

    pairs.sort(
        key=lambda p: (
            _dex_priority(p.get("dexId") or p.get("dexName") or ""),
            1 if (p.get("marketCap") is not None or p.get("fdv") is not None) else 0,
            _f((p.get("liquidity") or {}).get("usd")),
        ),
        reverse=True,
    )
    p = pairs[0]
    base = p.get("baseToken") or {}
    name = base.get("name") or base.get("symbol") or mint[:6]
    symbol = base.get("symbol") or name
    price = p.get("priceUsd")
    liq = (p.get("liquidity") or {}).get("usd")
    market_cap = p.get("marketCap")
    fdv = p.get("fdv")
    dex_url = p.get("url")
    dex_name = p.get("dexId") or p.get("dexName") or ""
    buy_url = None
    if 'ston' in dex_name.lower():
        buy_url = f"https://app.ston.fi/swap?ft=TON&tt={mint}"
    elif 'dedust' in dex_name.lower():
        buy_url = f"https://dedust.io/swap/TON/{mint}"
    mcap_val = market_cap if market_cap not in (None, "", 0, "0") else fdv
    return {
        "name": name,
        "symbol": symbol,
        "priceUsd": _f(price) if price is not None else None,
        "liquidityUsd": _f(liq) if liq is not None else None,
        "mcapUsd": _f(mcap_val) if mcap_val not in (None, "") else None,
        "dexUrl": dex_url,
        "dexName": dex_name,
        "buyUrl": buy_url,
    }
