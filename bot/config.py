from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    BOT_TOKEN: str
    OWNER_ID: int
    POST_CHANNEL: str | int
    DATABASE_URL: str = 'sqlite+aiosqlite:////data/spyton_ton.db'

    TONCENTER_BASE_URL: str = 'https://toncenter.com/api/v3'
    TONCENTER_API_KEY: str = ''
    TONAPI_BASE_URL: str = 'https://tonapi.io/v2'
    TONAPI_API_KEY: str = ''
    ENABLE_TONAPI: bool = True
    ENABLE_TONCENTER: bool = True

    MERCHANT_WALLET: str = ''
    TRENDING_URL: str = 'https://t.me/SpyTONTrending'
    LISTING_URL: str = 'https://t.me/SpyTONListing'
    BUY_URL_TEMPLATE: str = 'https://t.me/SpyTONPortal'
    DEFAULT_AD_TEXT: str = 'Advertise here'
    POLL_INTERVAL_SEC: int = 6
    CHANNEL_MIN_BUY_TON: float = 0.3
    GROUP_MIN_BUY_TON: float = 0.01
    LEADERBOARD_MESSAGE_ID: int | None = None
    TRENDING_PRICES: dict[str, float] = Field(default_factory=lambda: {
        '1h': 2.5,
        '3h': 4.0,
        '6h': 6.0,
        '9h': 8.0,
        '12h': 10.0,
        '24h': 15.0,
    })
    AD_PRICES: dict[str, float] = Field(default_factory=lambda: {
        '1d': 8.0,
        '3d': 20.0,
        '7d': 42.0,
    })


settings = Settings()
