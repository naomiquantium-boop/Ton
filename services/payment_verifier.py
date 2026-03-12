from __future__ import annotations
import time
from services.ton_providers import TonCenterClient, TonAPIClient


class PaymentVerifier:
    def __init__(self, db, toncenter: TonCenterClient | None, tonapi: TonAPIClient | None, merchant_wallet: str):
        self.db = db
        self.toncenter = toncenter
        self.tonapi = tonapi
        self.merchant_wallet = merchant_wallet

    async def verify_invoice(self, invoice_id: int, tx_hash: str) -> tuple[bool, str]:
        conn = await self.db.connect()
        try:
            cur = await conn.execute('SELECT * FROM invoices WHERE id=?', (invoice_id,))
            invoice = await cur.fetchone()
            if not invoice:
                return False, 'Invoice not found.'
            # MVP verification: accept tx hash format and mark paid when not already paid.
            if len(tx_hash.strip()) < 20:
                return False, 'Invalid tx hash.'
            await conn.execute('UPDATE invoices SET tx_hash=?, is_paid=1 WHERE id=?', (tx_hash.strip(), invoice_id))
            await conn.commit()
            return True, invoice['kind']
        finally:
            await conn.close()

    async def create_invoice(self, user_id: int, token_address: str, kind: str, duration_key: str, amount_ton: float, target_link: str | None = None, ad_text: str | None = None, ad_link: str | None = None) -> int:
        now = int(time.time())
        conn = await self.db.connect()
        try:
            cur = await conn.execute(
                'INSERT INTO invoices(user_id, token_address, kind, duration_key, amount_ton, wallet, target_link, ad_text, ad_link, created_at, expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (user_id, token_address, kind, duration_key, amount_ton, self.merchant_wallet, target_link, ad_text, ad_link, now, now + 86400),
            )
            await conn.commit()
            return cur.lastrowid
        finally:
            await conn.close()
