from __future__ import annotations
import aiohttp


class TonCenterClient:
    def __init__(self, base_url: str, api_key: str = ''):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))

    async def get_transactions(self, account: str, limit: int = 20) -> list[dict]:
        headers = {'X-API-Key': self.api_key} if self.api_key else {}
        params = {'account': account, 'limit': limit, 'sort': 'desc'}
        url = f"{self.base_url}/transactions"
        async with self.session.get(url, params=params, headers=headers) as resp:
            data = await resp.json(content_type=None)
            return data.get('transactions') or data.get('result') or []

    async def get_balance(self, account: str) -> float:
        headers = {'X-API-Key': self.api_key} if self.api_key else {}
        url = f"{self.base_url}/account"
        async with self.session.get(url, params={'address': account}, headers=headers) as resp:
            data = await resp.json(content_type=None)
            bal = (data.get('balance') if isinstance(data, dict) else 0) or 0
            try:
                return float(bal) / 1e9
            except Exception:
                return 0.0

    async def close(self):
        await self.session.close()


class TonAPIClient:
    def __init__(self, base_url: str, api_key: str = ''):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))

    def _headers(self):
        return {'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}

    async def get_account_events(self, account: str, limit: int = 20) -> list[dict]:
        url = f"{self.base_url}/accounts/{account}/events"
        async with self.session.get(url, params={'limit': limit}, headers=self._headers()) as resp:
            data = await resp.json(content_type=None)
            return data.get('events') or []

    async def get_trace(self, trace_id: str) -> dict:
        url = f"{self.base_url}/traces/{trace_id}"
        async with self.session.get(url, headers=self._headers()) as resp:
            return await resp.json(content_type=None)

    async def get_wallet_balance(self, account: str) -> float:
        url = f"{self.base_url}/accounts/{account}"
        async with self.session.get(url, headers=self._headers()) as resp:
            data = await resp.json(content_type=None)
            bal = data.get('balance') or 0
            try:
                return float(bal) / 1e9
            except Exception:
                return 0.0

    async def close(self):
        await self.session.close()
