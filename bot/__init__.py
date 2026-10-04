"""Bot package initialization."""
from bot.bot import init_bot, start_telegram_bot, stop_telegram_bot, bot, dp

__all__ = [
    "init_bot",
    "start_telegram_bot",
    "stop_telegram_bot",
    "bot",
    "dp",
]
