from __future__ import annotations
import os
import httpx

DEX_TOKEN_URL = "https://api.dexscreener.com/latest/dex/tokens/{mint}"
DEX_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search?q={query}"
TONAPI_BASE = os.getenv('TONAPI_BASE', 'https://tonapi.io/v2').rstrip('/')
TONAPI_KEY = os.getenv('TONAPI_KEY', os.getenv('TON_API_KEY', '')).strip()


def _f(v):
    try:
        return float(v)
    except Exception:
        return 0.0


def _dex_priority(name: str) -> int:
    n = (name or '').lower()
    if 'ston' in n:
        return 3
    if 'dedust' in n:
        return 2
    return 1


def _looks_addressish(v: str | None) -> bool:
    s = (v or '').strip()
    if not s:
        return True
    if len(s) >= 24 and s.startswith(('EQ', 'UQ', 'kQ', '0:')):
        return True
    if len(s) <= 8 and s[:2] in {'EQ', 'UQ', 'kQ'}:
        return True
    return False


def _pick_pair(pairs: list[dict]) -> dict | None:
    if not pairs:
        return None
    pairs.sort(
        key=lambda p: (
            _dex_priority(p.get('dexId') or p.get('dexName') or ''),
            1 if (p.get('marketCap') is not None or p.get('fdv') is not None) else 0,
            _f((p.get('liquidity') or {}).get('usd')),
        ),
        reverse=True,
    )
    return pairs[0]


def _auth_headers() -> dict[str, str]:
    h: dict[str, str] = {}
    if TONAPI_KEY:
        h['Authorization'] = f'Bearer {TONAPI_KEY}'
        h['X-API-Key'] = TONAPI_KEY
    return h


def _clean_name_symbol(name: str | None, symbol: str | None) -> tuple[str | None, str | None]:
    name = (name or '').strip() or None
    symbol = (symbol or '').strip() or None
    if _looks_addressish(symbol) and name and not _looks_addressish(name):
        symbol = None
    if _looks_addressish(name) and symbol and not _looks_addressish(symbol):
        name = symbol
    if _looks_addressish(name):
        name = None
    if _looks_addressish(symbol):
        symbol = None
    return name, symbol


async def _fetch_tonapi_meta(c: httpx.AsyncClient, mint: str) -> dict:
    try:
        r = await c.get(f"{TONAPI_BASE}/jettons/{mint}", headers=_auth_headers())
        r.raise_for_status()
        data = r.json() or {}
    except Exception:
        return {}

    md = data.get('metadata') or {}
    symbol = md.get('symbol') or data.get('symbol') or data.get('ticker')
    name = md.get('name') or data.get('name') or data.get('title')
    name, symbol = _clean_name_symbol(name, symbol)
    image = md.get('image') or md.get('image_url') or data.get('image')
    decimals = md.get('decimals') or data.get('decimals')
    return {
        'name': name,
        'symbol': symbol,
        'image': image,
        'decimals': int(decimals) if str(decimals).isdigit() else None,
    }


async def fetch_token_meta(mint: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as c:
        tonapi_meta = await _fetch_tonapi_meta(c, mint)
        pair = None
        try:
            r = await c.get(DEX_TOKEN_URL.format(mint=mint))
            r.raise_for_status()
            data = r.json()
            pair = _pick_pair(data.get('pairs') or [])
        except Exception:
            pair = None
        if pair is None:
            try:
                r = await c.get(DEX_SEARCH_URL.format(query=mint))
                r.raise_for_status()
                data = r.json()
                pair = _pick_pair(data.get('pairs') or [])
            except Exception:
                pair = None

    if not pair:
        return {
            'name': tonapi_meta.get('name'),
            'symbol': tonapi_meta.get('symbol'),
            'priceUsd': None,
            'liquidityUsd': None,
            'mcapUsd': None,
            'dexUrl': None,
            'dexName': None,
            'buyUrl': f'https://t.me/dtrade?start=11TYq7LInG_{mint}',
            'image': tonapi_meta.get('image'),
            'decimals': tonapi_meta.get('decimals'),
        }

    base = pair.get('baseToken') or {}
    dex_name = pair.get('dexId') or pair.get('dexName') or ''
    price = pair.get('priceUsd')
    liq = (pair.get('liquidity') or {}).get('usd')
    market_cap = pair.get('marketCap')
    fdv = pair.get('fdv')
    dex_url = pair.get('url')
    mcap_val = market_cap if market_cap not in (None, '', 0, '0') else fdv

    name = tonapi_meta.get('name') or base.get('name')
    symbol = tonapi_meta.get('symbol') or base.get('symbol')
    name, symbol = _clean_name_symbol(name, symbol)

    return {
        'name': name,
        'symbol': symbol,
        'priceUsd': _f(price) if price is not None else None,
        'liquidityUsd': _f(liq) if liq is not None else None,
        'mcapUsd': _f(mcap_val) if mcap_val not in (None, '') else None,
        'dexUrl': dex_url,
        'dexName': dex_name,
        'buyUrl': f'https://t.me/dtrade?start=11TYq7LInG_{mint}',
        'image': tonapi_meta.get('image'),
        'decimals': tonapi_meta.get('decimals'),
    }
