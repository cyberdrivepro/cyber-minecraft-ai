"""Start and help command handlers."""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from bot.keyboards import get_main_menu_keyboard
from storage.database import get_db
from storage.models import User
from logger import get_logger

logger = get_logger("bot.handlers.start")
router = Router(name="start_router")

@router.message(CommandStart())
async def handle_start(message: Message, state: FSMContext):
    """Handle /start command and register user."""
    await state.clear()
    user_id = str(message.from_user.id)
    username = message.from_user.username or "unknown"
    first_name = message.from_user.first_name or "Crafter"

    # Register or update user in DB
    try:
        with get_db() as db:
            u = db.query(User).filter(User.id == user_id).first()
            if not u:
                u = User(id=user_id, username=username, first_name=first_name)
                db.add(u)
            else:
                u.username = username
                u.first_name = first_name
    except Exception as e:
        logger.warning(f"Failed to record user {user_id}: {e}")

    welcome_text = (
        f"🤖 *CYBER MINECRAFT AI MOD BUILDER*\n\n"
        f"Welcome, *{first_name}*! I can turn your natural language ideas into real, "
        f"playable Minecraft Bedrock Add-ons (`.mcaddon`) and Java Fabric mods (`.jar`).\n\n"
        f"✨ *Available Features:*\n"
        f"• Weapons, armor, tools, blocks & food\n"
        f"• Custom abilities, cooldowns & projectiles\n"
        f"• Mobs, bosses & shaped crafting recipes\n"
        f"• Procedural & custom AI pixel-art textures\n"
        f"• Conversational live mod editor (`/edit`)\n"
        f"• Automatic compilation error self-repair\n\n"
        f"Select an option below or type `/newmod` to begin!"
    )
    await message.answer(welcome_text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())

@router.message(Command("help"))
async def handle_help(message: Message):
    """Handle /help command."""
    help_text = (
        "📚 *CYBER MINECRAFT AI COMMAND GUIDE*\n\n"
        "*/start* - Show main cyber control menu\n"
        "*/newmod* - Create a brand new mod from prompt\n"
        "*/myprojects* - View and manage your mod library\n"
        "*/project <id>* - View detailed project specs and assets\n"
        "*/edit [id]* - Conversationally modify an existing mod\n"
        "*/build [id]* - Trigger fresh build pipeline\n"
        "*/download [id]* - Get the latest compiled file\n"
        "*/logs [id]* - View real-time build and repair logs\n"
        "*/assets* - Manage textures, models and audio\n"
        "*/settings* - Hardware stats and AI engine status\n"
        "*/cancel* - Cancel any ongoing wizard"
    )
    await message.answer(help_text, parse_mode="Markdown")
