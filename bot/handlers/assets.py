"""AI Asset Studio and file upload handlers (textures, reference photos, models)."""
from io import BytesIO
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.filters import Command
from bot.keyboards import get_main_menu_keyboard
from assets.pixel_processor import process_to_pixel_art, generate_procedural_sword
from logger import get_logger

logger = get_logger("bot.handlers.assets")
router = Router(name="assets_router")

@router.message(Command("assets"))
@router.callback_query(F.data == "btn_asset_studio")
async def handle_assets_menu(event: Message | CallbackQuery):
    """Show AI Asset Studio options."""
    text = (
        "🎨 *AI ASSET STUDIO*\n\n"
        "Here you can generate, inspect, and convert assets for your Minecraft mods:\n\n"
        "• *Convert Photo to Pixel Art*: Send any image or photo directly to this chat!\n"
        "• *Procedural Textures*: Automatically synthesized 16x16 / 32x32 textures.\n"
        "• *Custom 3D Models*: Upload `.bbmodel` or Bedrock geometry files.\n"
        "• *Custom Audio*: Upload `.ogg` or `.wav` sound effects.\n\n"
        "👉 *Try it right now*: Upload a photo to see it converted into Minecraft pixel art!"
    )
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())

@router.message(F.photo)
async def handle_photo_upload(message: Message):
    """Convert any uploaded photo into a Minecraft 16x16 pixel art PNG."""
    photo = message.photo[-1]  # Highest resolution
    bot = message.bot
    file_info = await bot.get_file(photo.file_id)
    
    file_stream = BytesIO()
    await bot.download_file(file_info.file_path, file_stream)
    raw_bytes = file_stream.getvalue()

    await message.answer("🎨 *Converting your image into 16x16 Minecraft pixel art...*", parse_mode="Markdown")

    pixel_bytes = process_to_pixel_art(raw_bytes, target_size=16)
    preview_doc = BufferedInputFile(pixel_bytes, filename="minecraft_texture.png")
    
    await message.answer_document(
        document=preview_doc,
        caption="✨ Here is your converted Minecraft 16x16 pixel-art texture!\nYou can attach this to any item or block in your mod."
    )
