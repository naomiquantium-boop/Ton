from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import re


@dataclass
class BuyEvent:
    signature: str
    buyer: str
    got_tokens: float
    spent_ton: float
    spent_usd: float
    price_usd: float
    liquidity_usd: float
    market_cap_usd: float
    holders: int
    position_pct: str
    chart_url: str
    wallet_url: str
    tx_url: str
    ts: int


def _to_float(v) -> float:
    try:
        return float(v or 0)
    except Exception:
        return 0.0


def _extract_amounts(text: str) -> tuple[float, float]:
    nums = re.findall(r'([0-9]+(?:\.[0-9]+)?)', text or '')
    if len(nums) >= 2:
        return float(nums[0]), float(nums[1])
    if len(nums) == 1:
        return float(nums[0]), 0.0
    return 0.0, 0.0


def _sig_from_event(event: dict) -> str:
    return event.get('event_id') or event.get('tx_hash') or event.get('lt') or ''


def _wallet_url(addr: str) -> str:
    return f'https://tonviewer.com/{addr}' if addr else 'https://tonviewer.com'


def _tx_url(sig: str) -> str:
    return f'https://tonviewer.com/transaction/{sig}' if sig else 'https://tonviewer.com'


class BaseAdapter:
    source = 'base'

    def parse_tonapi_event(self, token: dict, event: dict) -> Optional[BuyEvent]:
        actions = event.get('actions') or []
        text = str(actions)
        if 'sell' in text.lower() or 'liquidity' in text.lower() or 'remove' in text.lower() or 'close' in text.lower():
            return None
        token_symbol = (token.get('symbol') or '').lower()
        token_address = (token.get('token_address') or '').lower()
        buyer = ''
        spent_ton = 0.0
        got_tokens = 0.0
        for act in actions:
            typ = (act.get('type') or '').lower()
            if typ in {'jetton_transfer', 'jetton_swap', 'smart_contract_exec'}:
                payload = str(act).lower()
                if token_symbol and token_symbol in payload or token_address and token_address in payload:
                    ton_guess, jetton_guess = _extract_amounts(str(act))
                    spent_ton = max(spent_ton, ton_guess)
                    got_tokens = max(got_tokens, jetton_guess)
                    buyer = buyer or (((act.get('sender') or {}).get('address')) or ((act.get('recipient') or {}).get('address')) or '')
        if spent_ton <= 0 or got_tokens <= 0:
            return None
        price_usd = event.get('price_usd') or token.get('last_price_usd') or 0.0
        if not price_usd and got_tokens:
            price_usd = max(0.0, (spent_ton * 1.35) / got_tokens)
        return BuyEvent(
            signature=_sig_from_event(event),
            buyer=buyer,
            got_tokens=got_tokens,
            spent_ton=spent_ton,
            spent_usd=spent_ton * 1.35,
            price_usd=_to_float(price_usd),
            liquidity_usd=_to_float(token.get('liquidity_usd') or 0),
            market_cap_usd=_to_float(token.get('market_cap_usd') or 0),
            holders=int(token.get('holders') or 0),
            position_pct='+0%',
            chart_url=token.get('chart_link') or '',
            wallet_url=_wallet_url(buyer),
            tx_url=_tx_url(_sig_from_event(event)),
            ts=int(event.get('timestamp') or event.get('lt') or 0),
        )

    def parse_toncenter_tx(self, token: dict, tx: dict) -> Optional[BuyEvent]:
        payload = str(tx).lower()
        if 'sell' in payload or 'liquidity' in payload or 'remove' in payload or 'close' in payload:
            return None
        token_symbol = (token.get('symbol') or '').lower()
        token_address = (token.get('token_address') or '').lower()
        if token_symbol and token_symbol not in payload and token_address and token_address not in payload:
            return None
        spent_ton, got_tokens = _extract_amounts(str(tx))
        if spent_ton <= 0 or got_tokens <= 0:
            return None
        sig = tx.get('hash') or tx.get('transaction_id', {}).get('hash') or ''
        buyer = tx.get('account') or tx.get('in_msg', {}).get('source') or ''
        return BuyEvent(
            signature=sig,
            buyer=buyer,
            got_tokens=got_tokens,
            spent_ton=spent_ton,
            spent_usd=spent_ton * 1.35,
            price_usd=_to_float(token.get('last_price_usd') or 0),
            liquidity_usd=_to_float(token.get('liquidity_usd') or 0),
            market_cap_usd=_to_float(token.get('market_cap_usd') or 0),
            holders=int(token.get('holders') or 0),
            position_pct='+0%',
            chart_url=token.get('chart_link') or '',
            wallet_url=_wallet_url(buyer),
            tx_url=_tx_url(sig),
            ts=int(tx.get('utime') or tx.get('now') or 0),
        )


class StonFiAdapter(BaseAdapter):
    source = 'stonfi'


class DeDustAdapter(BaseAdapter):
    source = 'dedust'


class BlumAdapter(BaseAdapter):
    source = 'blum'


class GasPumpAdapter(BaseAdapter):
    source = 'gaspump'


ADAPTERS = {
    'stonfi': StonFiAdapter(),
    'dedust': DeDustAdapter(),
    'blum': BlumAdapter(),
    'gaspump': GasPumpAdapter(),
}
