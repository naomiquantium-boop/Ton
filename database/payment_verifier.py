from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import time
from utils.ton_rpc import TonAPI


@dataclass
class PaymentResult:
    ok: bool
    reason: str
    amount_ton: float = 0.0
    slot: Optional[int] = None
    timestamp: Optional[int] = None
    signature: Optional[str] = None


def _nano_to_ton(v: int | str | float | None) -> float:
    try:
        return float(v or 0) / 1_000_000_000
    except Exception:
        return 0.0


def _extract_comment(tx: dict) -> str:
    for msg in (tx.get("in_msgs") or []):
        comment = msg.get("message_content") or msg.get("comment") or msg.get("body") or msg.get("decoded_comment")
        if isinstance(comment, str) and comment.strip():
            return comment.strip()
    return ""


def _extract_amount_to_wallet(tx: dict, expected_to: str) -> float:
    target = (expected_to or "").strip()
    best = 0.0
    for msg in (tx.get("in_msgs") or []):
        dst = (msg.get("destination") or msg.get("dst") or msg.get("destination_account") or "").strip()
        if target and dst and dst != target:
            continue
        best = max(best, _nano_to_ton(msg.get("value") or msg.get("amount")))
    if best > 0:
        return best
    return _nano_to_ton(tx.get("value_flow") or 0)


def _extract_hash(tx: dict) -> str | None:
    return tx.get("hash") or tx.get("transaction_id") or tx.get("tx_hash")


async def verify_ton_transfer(
    rpc: TonAPI,
    signature: str,
    expected_to: str,
    min_amount_ton: float,
    expected_memo: str | None = None,
    max_age_sec: int = 3 * 60 * 60,
) -> PaymentResult:
    txs = await rpc.get_account_transactions(expected_to, limit=50)
    for tx in txs:
        tx_hash = _extract_hash(tx)
        if not tx_hash or tx_hash != signature:
            continue
        ts = int(tx.get("now") or tx.get("utime") or time.time())
        if max_age_sec and time.time() - ts > max_age_sec:
            return PaymentResult(False, "Transaction is too old.", signature=tx_hash, timestamp=ts)
        memo = _extract_comment(tx)
        amount = _extract_amount_to_wallet(tx, expected_to)
        if expected_memo and memo != expected_memo:
            return PaymentResult(False, f"Memo/comment mismatch. Expected {expected_memo}.", amount_ton=amount, signature=tx_hash, timestamp=ts)
        if amount + 1e-9 < float(min_amount_ton):
            return PaymentResult(False, f"Payment found but amount is below required {min_amount_ton:g} TON.", amount_ton=amount, signature=tx_hash, timestamp=ts)
        return PaymentResult(True, "Payment verified.", amount_ton=amount, signature=tx_hash, timestamp=ts)
    return PaymentResult(False, "Transaction not found on the payment wallet yet.")


async def find_recent_payment(
    rpc: TonAPI,
    expected_to: str,
    min_amount_ton: float,
    used_signatures: set[str] | None = None,
    expected_memo: str | None = None,
) -> PaymentResult:
    used_signatures = used_signatures or set()
    try:
        txs = await rpc.get_account_transactions(expected_to, limit=50)
    except Exception:
        return PaymentResult(False, "Could not fetch wallet payments right now.")
    for tx in txs:
        sig = _extract_hash(tx)
        if not sig or sig in used_signatures:
            continue
        memo = _extract_comment(tx)
        if expected_memo and memo != expected_memo:
            continue
        amount = _extract_amount_to_wallet(tx, expected_to)
        if amount + 1e-9 < float(min_amount_ton):
            continue
        ts = int(tx.get("now") or tx.get("utime") or time.time())
        return PaymentResult(True, "Payment verified.", amount_ton=amount, signature=sig, timestamp=ts)
    return PaymentResult(False, "Payment not detected yet.")
