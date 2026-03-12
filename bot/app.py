from __future__ import annotations
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from bot.config import settings
from database.db import DB
from database.migrations import CREATE_TABLES
from bot.handlers import router as handlers_router
from bot.wizard import router as wizard_router
from services.buy_watcher import BuyWatcher
from services.leaderboard import LeaderboardUpdater
from services.payment_verifier import PaymentVerifier
from services.ton_providers import TonAPIClient, TonCenterClient


async def _migrate(db: DB):
    conn = await db.connect()
    try:
        for stmt in CREATE_TABLES:
            await conn.execute(stmt)
        await conn.commit()
    finally:
        await conn.close()


async def run():
    load_dotenv()
    db = DB(settings.DATABASE_URL)
    await _migrate(db)

    bot = Bot(token=settings.BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher(storage=MemoryStorage())

    toncenter = TonCenterClient(settings.TONCENTER_BASE_URL, settings.TONCENTER_API_KEY) if settings.ENABLE_TONCENTER else None
    tonapi = TonAPIClient(settings.TONAPI_BASE_URL, settings.TONAPI_API_KEY) if settings.ENABLE_TONAPI else None
    payment_verifier = PaymentVerifier(db, toncenter, tonapi, settings.MERCHANT_WALLET)

    dp.workflow_data.update({
        'db': db,
        'payment_verifier': payment_verifier,
    })

    dp.include_router(handlers_router)
    dp.include_router(wizard_router)

    watcher = BuyWatcher(bot=bot, db=db, toncenter=toncenter, tonapi=tonapi)
    lb = LeaderboardUpdater(bot=bot, db=db)
    task_watch = asyncio.create_task(watcher.run_forever())
    task_lb = asyncio.create_task(lb.run_forever())
    try:
        await dp.start_polling(bot)
    finally:
        task_watch.cancel()
        task_lb.cancel()
        await watcher.close()
        await lb.close()
        await bot.session.close()
