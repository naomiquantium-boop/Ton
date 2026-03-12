from __future__ import annotations
import base64
import binascii
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

    @staticmethod
    def tx_hash_to_hex(tx_hash: str | None) -> str | None:
        if not tx_hash:
            return None
        s = str(tx_hash).strip()
        if not s:
            return None
        low = s.lower()
        if all(c in '0123456789abcdef' for c in low) and len(low) == 64:
            return low
        padded = s + ('=' * ((4 - len(s) % 4) % 4))
        try:
            raw = base64.urlsafe_b64decode(padded)
            if len(raw) == 32:
                return raw.hex()
        except Exception:
            pass
        try:
            raw = base64.b64decode(padded)
            if len(raw) == 32:
                return raw.hex()
        except Exception:
            pass
        try:
            raw = binascii.unhexlify(s)
            if len(raw) == 32:
                return raw.hex()
        except Exception:
            pass
        return None

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

    async def get_transaction_by_hash(self, tx_hash: str) -> dict | None:
        if not tx_hash:
            return None
        r = await self.client.get(
            f"{self.rpc_url}/transactions",
            params={"hash": tx_hash, "limit": 1, "sort": "desc"},
            headers=self._headers(),
        )
        r.raise_for_status()
        data = r.json()
        rows = data.get("transactions") or data.get("data") or []
        return rows[0] if isinstance(rows, list) and rows else None

    async def close(self):
        await self.client.aclose()
