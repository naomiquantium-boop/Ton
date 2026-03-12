from __future__ import annotations
import httpx



class TonAPI:
    def __init__(self, rpc_url: str, timeout: float = 20.0, api_key: str = ""):
        self.rpc_url = rpc_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=timeout)
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        h = {}
        if self.api_key:
            h["X-API-Key"] = self.api_key
        return h

    async def get_jetton_transfers(self, jetton_master: str, limit: int = 20, offset: int = 0) -> list[dict]:
        r = await self.client.get(
            f"{self.rpc_url}/jetton/transfers",
            params={"jetton_master": jetton_master, "limit": limit, "offset": offset, "sort": "desc"},
            headers=self._headers(),
        )
        r.raise_for_status()
        data = r.json()
        rows = data.get("jetton_transfers") or data.get("transfers") or data.get("data") or []
        return rows if isinstance(rows, list) else []

    async def get_account_transactions(self, address: str, limit: int = 20) -> list[dict]:
        r = await self.client.get(
            f"{self.rpc_url}/transactions",
            params={"account": address, "limit": limit, "sort": "desc"},
            headers=self._headers(),
        )
        r.raise_for_status()
        data = r.json()
        rows = data.get("transactions") or data.get("data") or []
        return rows if isinstance(rows, list) else []

    async def close(self):
        await self.client.aclose()
