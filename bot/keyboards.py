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
                InlineKeyboardButton(text="🖥 Host Servers", callback_data="btn_host_servers"),
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

def get_host_menu_keyboard() -> InlineKeyboardMarkup:
    """Cyber Host menu: manage hosted Minecraft servers."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🖥 My Servers", callback_data="btn_my_servers"),
                InlineKeyboardButton(text="➕ New Server", callback_data="btn_new_server")
            ]
        ]
    )

def get_server_actions_keyboard(server_id: str, status: str) -> InlineKeyboardMarkup:
    """Action buttons for a single hosted server, based on its status."""
    rows = []
    if status == "online":
        rows.append([
            InlineKeyboardButton(text="⬇ Backup", callback_data=f"srv_backup_{server_id}"),
            InlineKeyboardButton(text="🔄 Restart", callback_data=f"srv_restart_{server_id}"),
            InlineKeyboardButton(text="⏹ Stop", callback_data=f"srv_stop_{server_id}")
        ])
    elif status in ("offline", "error"):
        rows.append([
            InlineKeyboardButton(text="▶ Start", callback_data=f"srv_start_{server_id}"),
            InlineKeyboardButton(text="🗑 Delete", callback_data=f"srv_delete_{server_id}")
        ])
    rows.append([InlineKeyboardButton(text="🔄 Refresh", callback_data=f"srv_view_{server_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
