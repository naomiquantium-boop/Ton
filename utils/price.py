from __future__ import annotations
import httpx


async def ton_usd(url: str) -> float:
    async with httpx.AsyncClient(timeout=12.0) as c:
        r = await c.get(url)
        r.raise_for_status()
        data = r.json()
    try:
        return float((data.get("the-open-network") or {}).get("usd") or 0.0)
    except Exception:
        return 0.0
