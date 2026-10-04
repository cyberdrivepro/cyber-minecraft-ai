"""Aiogram 3.x Telegram bot initialization and lifecycle management."""
import asyncio
from typing import Optional
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import settings
from logger import get_logger
from bot.handlers import all_routers

logger = get_logger("bot.bot")

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None
_bot_task: Optional[asyncio.Task] = None

def init_bot() -> Optional[Bot]:
    """Initialize bot instance if token is configured."""
    global bot, dp
    token = settings.TELEGRAM_BOT_TOKEN
    if not token or token == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.warning("TELEGRAM_BOT_TOKEN is not configured. Telegram bot service is running in standby.")
        return None

    bot = Bot(token=token)
    dp = Dispatcher(storage=MemoryStorage())
    
    for r in all_routers:
        dp.include_router(r)

    logger.info("Aiogram 3.x bot and dispatcher initialized successfully.")
    return bot

async def start_telegram_bot() -> None:
    """Start Telegram bot polling in the background."""
    global _bot_task
    b = init_bot()
    if not b or not dp:
        logger.info("Telegram polling skipped because no bot token was provided.")
        return

    async def _poll():
        try:
            logger.info("Starting Telegram bot polling...")
            await dp.start_polling(b, allowed_updates=dp.resolve_used_update_types())
        except asyncio.CancelledError:
            logger.info("Telegram polling cancelled.")
        except Exception as e:
            logger.error(f"Telegram polling error: {e}")

    _bot_task = asyncio.create_task(_poll())

async def stop_telegram_bot() -> None:
    """Stop Telegram bot polling."""
    global _bot_task, bot
    if _bot_task:
        _bot_task.cancel()
        try:
            await _bot_task
        except asyncio.CancelledError:
            pass
    if bot:
        await bot.session.close()
    logger.info("Telegram bot service stopped.")
