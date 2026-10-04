"""Inline and reply keyboards for Telegram bot."""
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Main start menu inline buttons."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚔ Create New Mod", callback_data="btn_new_mod"),
                InlineKeyboardButton(text="📦 My Projects", callback_data="btn_my_projects")
            ],
            [
                InlineKeyboardButton(text="🎨 AI Asset Studio", callback_data="btn_asset_studio"),
                InlineKeyboardButton(text="🔨 Build Queue", callback_data="btn_build_queue")
            ],
            [
                InlineKeyboardButton(text="⚙ Settings & System", callback_data="btn_settings")
            ]
        ]
    )

def get_edition_keyboard() -> InlineKeyboardMarkup:
    """Edition selection buttons."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🟩 Bedrock (.mcaddon)", callback_data="edition_bedrock"),
                InlineKeyboardButton(text="☕ Java Fabric (.jar)", callback_data="edition_fabric")
            ],
            [
                InlineKeyboardButton(text="❌ Cancel", callback_data="btn_cancel")
            ]
        ]
    )

def get_project_actions_keyboard(project_id: str) -> InlineKeyboardMarkup:
    """Action buttons for a single mod project."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✏ Edit Mod", callback_data=f"act_edit_{project_id}"),
                InlineKeyboardButton(text="🔨 Rebuild", callback_data=f"act_build_{project_id}")
            ],
            [
                InlineKeyboardButton(text="⬇ Download File", callback_data=f"act_download_{project_id}"),
                InlineKeyboardButton(text="📜 Build Logs", callback_data=f"act_logs_{project_id}")
            ],
            [
                InlineKeyboardButton(text="📦 Versions", callback_data=f"act_versions_{project_id}"),
                InlineKeyboardButton(text="🗑 Delete", callback_data=f"act_delete_{project_id}")
            ]
        ]
    )

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel Operation", callback_data="btn_cancel")]
        ]
    )
