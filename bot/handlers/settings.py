"""Settings and system status handlers."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from bot.keyboards import get_main_menu_keyboard
from ai.model_manager import model_manager
from logger import get_logger

logger = get_logger("bot.handlers.settings")
router = Router(name="settings_router")

@router.message(Command("settings"))
@router.callback_query(F.data == "btn_settings")
async def handle_settings(event: Message | CallbackQuery):
    """Display real system and AI model status."""
    status = model_manager.get_hardware_status()
    
    text = (
        "⚙ *CYBER MINECRAFT SYSTEM STATUS*\n\n"
        f"• *AI Provider*: `{status['provider']}`\n"
        f"• *Model ID*: `{status['model_id']}`\n"
        f"• *Model In Memory*: `{'Yes (Loaded)' if status['is_loaded'] else 'Lazy / Standby'}`\n"
        f"• *Device*: `{status['device'].upper()}`\n"
        f"• *CPU Usage*: `{status['cpu_percent']}%`\n"
        f"• *RAM*: `{status['ram_used_mb']} MB / {status['ram_total_mb']} MB ({status['ram_percent']}%)`\n"
    )
    if status["vram_mb"] > 0:
        text += f"• *GPU*: `{status['gpu_name']}` ({status['vram_used_mb']} / {status['vram_mb']} MB VRAM)\n"

    text += f"• *Last Inference Latency*: `{status['last_latency_ms']} ms`\n\n"
    text += "_FastAPI and background workers are operating normally._"

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
