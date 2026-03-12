from __future__ import annotations
import aiohttp


async def fetch_jetton_meta(token_address: str, tonapi_base: str, tonapi_key: str = '') -> dict:
    headers = {'Authorization': f'Bearer {tonapi_key}'} if tonapi_key else {}
    url = f"{tonapi_base.rstrip('/')}/jettons/{token_address}"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status >= 400:
                return {'name': token_address[:8], 'symbol': token_address[:6], 'holders': 0}
            data = await resp.json()
            meta = data.get('metadata') or {}
            holders = data.get('holders_count') or data.get('holdersCount') or 0
            return {
                'name': meta.get('name') or data.get('name') or token_address[:8],
                'symbol': meta.get('symbol') or data.get('symbol') or token_address[:6],
                'holders': holders,
                'image': meta.get('image') or meta.get('image_url') or '',
            }
