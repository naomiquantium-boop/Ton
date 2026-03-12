from pydantic import BaseModel
import os


def _get(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None:
        raise RuntimeError(f"Missing env var: {name}")
    return v


class Settings(BaseModel):
    BOT_TOKEN: str = _get("BOT_TOKEN")
    OWNER_ID: int = int(_get("OWNER_ID"))
    BOT_USERNAME: str = _get("BOT_USERNAME", "SpyTONBot")
    POST_CHANNEL: str = _get("POST_CHANNEL", "@SpyTONTrending")
    LISTING_URL: str = _get("LISTING_URL", "https://t.me/SpyTONPortal")
    TRENDING_URL: str = _get("TRENDING_URL", "https://t.me/SpyTONTrending")
    LEADERBOARD_MESSAGE_ID: int = int(_get("LEADERBOARD_MESSAGE_ID", "0"))

    DATABASE_URL: str = _get("DATABASE_URL", "sqlite+aiosqlite:///data/buybot.db")

    TONCENTER_API_BASE: str = _get("TONCENTER_API_BASE", "https://toncenter.com/api/v3")
    TONCENTER_API_KEY: str = os.getenv("TONCENTER_API_KEY", "")
    TON_API_TIMEOUT: int = int(_get("TON_API_TIMEOUT", "20"))
    TON_VIEWER_TX_URL: str = _get("TON_VIEWER_TX_URL", "https://tonviewer.com/transaction/{tx}")

    PAYMENT_WALLET: str = _get("PAYMENT_WALLET")

    TOP3_2H_PRICE_TON: float = 7
    TOP3_4H_PRICE_TON: float = 14
    TOP3_8H_PRICE_TON: float = 21
    TOP3_24H_PRICE_TON: float = 35

    TOP10_2H_PRICE_TON: float = 5
    TOP10_4H_PRICE_TON: float = 10
    TOP10_8H_PRICE_TON: float = 17
    TOP10_24H_PRICE_TON: float = 30

    ADS_1D_PRICE_TON: float = 10
    ADS_3D_PRICE_TON: float = 25
    ADS_7D_PRICE_TON: float = 60

    POLL_INTERVAL_SEC: int = int(_get("POLL_INTERVAL_SEC", "4"))
    MIN_BUY_DEFAULT_TON: float = float(_get("MIN_BUY_DEFAULT_TON", "0.25"))

    TON_PRICE_URL: str = _get("TON_PRICE_URL", "https://api.coingecko.com/api/v3/simple/price?ids=the-open-network&vs_currencies=usd")
    BUY_URL_STONFI: str = "https://t.me/dtrade?start=11TYq7LInG_{mint}"
    BUY_URL_DEDUST: str = "https://t.me/dtrade?start=11TYq7LInG_{mint}"

    @property
    def BOOK_ADS_URL(self) -> str:
        return f"https://t.me/{self.BOT_USERNAME}?start=ads"

    @property
    def BOOK_TRENDING_URL(self) -> str:
        return f"https://t.me/{self.BOT_USERNAME}?start=trending"


settings = Settings()
