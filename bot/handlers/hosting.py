"""Cyber Host handlers: hosted Minecraft server management via Telegram."""
from typing import Optional, Union

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.keyboards import get_host_menu_keyboard, get_server_actions_keyboard, get_cancel_keyboard
from servers.manager import server_manager
from storage.database import get_db
from storage.models import Server as DBServer
from logger import get_logger

logger = get_logger("bot.handlers.hosting")
router = Router(name="hosting_router")

class NewServerStates(StatesGroup):
    waiting_for_name = State()

def _server_text(row: DBServer) -> str:
    address = f"`{row.address}`" if row.address else "_offline — start to get an address_"
    uptime = ""
    if row.status == "online" and row.last_started:
        from datetime import datetime
        seconds = int((datetime.utcnow() - row.last_started).total_seconds())
        uptime = f"\n• Session uptime: {seconds // 60}m {seconds % 60}s"
    return (
        f"🖥 *SERVER: {row.name}*\n\n"
        f"• ID: `{row.id}`\n"
        f"• Software: *{row.software.capitalize()} {row.mc_version}*\n"
        f"• Status: `{row.status}` — {row.status_detail}\n"
        f"• Address: {address}{uptime}\n"
        f"• Players: max {row.max_players} | Gamemode: {row.gamemode} | Difficulty: {row.difficulty}\n"
        f"• Playtime: {(row.playtime_seconds or 0) // 3600}h {(row.playtime_seconds or 0) % 3600 // 60}m"
    )

@router.message(Command("host"))
@router.callback_query(F.data == "btn_host_servers")
async def host_menu(event: Union[Message, CallbackQuery], state: FSMContext):
    """Show the Cyber Host menu."""
    await state.clear()
    text = (
        "🖥 *CYBER HOST — FREE MINECRAFT SERVERS*\n\n"
        "Host your own Minecraft server right from this bot:\n"
        "• Paper, Vanilla, Fabric, Forge & Bedrock\n"
        "• Console, players, backups & settings\n"
        "• Aternos-style start queue with dynamic address\n\n"
        "Use `/server <id>` to open a specific server."
    )
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=get_host_menu_keyboard())
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown", reply_markup=get_host_menu_keyboard())

@router.message(Command("servers"))
@router.callback_query(F.data == "btn_my_servers")
async def list_servers(event: Union[Message, CallbackQuery]):
    """List the user's hosted servers."""
    user_id = str(event.from_user.id)
    with get_db() as db:
        servers = (
            db.query(DBServer)
            .filter(DBServer.owner_id == user_id)
            .order_by(DBServer.created_at.desc())
            .all()
        )
        web_servers = db.query(DBServer).filter(DBServer.owner_id == "web_admin").count()

    if not servers:
        msg = (
            "🖥 You don't have any servers yet!\n\n"
            "Tap **➕ New Server** to create your first free Minecraft server in seconds."
        )
        if isinstance(event, CallbackQuery):
            await event.message.edit_text(msg, reply_markup=get_host_menu_keyboard())
            await event.answer()
        else:
            await event.answer(msg, reply_markup=get_host_menu_keyboard())
        return

    text = "🖥 *YOUR HOSTED SERVERS:*\n\n"
    for s in servers:
        icon = "🟢" if s.status == "online" else ("🟡" if s.status in ("queued", "preparing", "starting") else "⚫")
        text += (
            f"{icon} *{s.name}* (`{s.id}`)\n"
            f"   {s.software.capitalize()} {s.mc_version} | Status: `{s.status}`\n"
            f"   {s.address or 'no address (offline)'}\n\n"
        )
    text += f"_Plus {web_servers} server(s) created from the web dashboard._"

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=get_host_menu_keyboard())
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown")

@router.message(Command("newserver"))
@router.callback_query(F.data == "btn_new_server")
async def new_server(event: Union[Message, CallbackQuery], state: FSMContext):
    """Start the server creation wizard."""
    await state.clear()
    await state.set_state(NewServerStates.waiting_for_name)
    text = (
        "🖥 *NEW FREE SERVER*\n\n"
        "Send me your server name and software in one message:\n\n"
        "_Example:_ `My Survival World paper`\n\n"
        "• Software options: `paper`, `vanilla`, `fabric`, `forge`, `bedrock`\n"
        "• Default version is the latest; EULA is accepted on creation."
    )
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=get_cancel_keyboard())
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown", reply_markup=get_cancel_keyboard())

@router.message(NewServerStates.waiting_for_name, F.text)
async def process_server_name(message: Message, state: FSMContext):
    """Create the server from '<name> <software>' input."""
    parts = message.text.strip().rsplit(maxsplit=1)
    name = parts[0][:64]
    software = parts[1].lower() if len(parts) > 1 else "paper"
    await state.clear()
    user_id = str(message.from_user.id)
    latest_version = {
        "paper": "1.21.4", "vanilla": "1.21.4", "fabric": "1.21.4", "forge": "1.21.4", "bedrock": "1.21.50"
    }.get(software)
    if not latest_version:
        await message.answer(f"❌ Unsupported software `{software}`. Options: paper, vanilla, fabric, forge, bedrock.")
        return
    try:
        row = server_manager.create_server(
            owner_id=user_id,
            name=name,
            software=software,
            mc_version=latest_version,
            motd=f"{name} — hosted on Cyber Host",
            eula_accepted=True
        )
    except ValueError as e:
        await message.answer(f"❌ {e}")
        return
    await message.answer(
        f"✅ *Server created!*\n\n{_server_text(row)}\n\nTap *Start* below to queue it in the host queue.",
        parse_mode="Markdown",
        reply_markup=get_server_actions_keyboard(row.id, row.status)
    )

@router.message(Command("server"))
async def view_server_cmd(message: Message):
    """Open a specific server via /server <id>."""
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Usage: `/server <SERVER_ID>` or `/servers` for the list.", parse_mode="Markdown")
        return
    with get_db() as db:
        row = db.query(DBServer).filter(DBServer.id == parts[1].strip()).first()
    if not row:
        await message.answer(f"Server `{parts[1].strip()}` not found. Use `/servers` to list yours.", parse_mode="Markdown")
        return
    await message.answer(_server_text(row), parse_mode="Markdown", reply_markup=get_server_actions_keyboard(row.id, row.status))

async def _load_server(callback: CallbackQuery, server_id: str) -> Optional[DBServer]:
    with get_db() as db:
        return db.query(DBServer).filter(DBServer.id == server_id).first()

@router.callback_query(F.data.startswith("srv_view_"))
async def view_server_callback(callback: CallbackQuery):
    server_id = callback.data.replace("srv_view_", "").strip()
    row = await _load_server(callback, server_id)
    if not row:
        await callback.message.edit_text(f"Server `{server_id}` not found.", parse_mode="Markdown")
        await callback.answer()
        return
    await callback.message.edit_text(_server_text(row), parse_mode="Markdown", reply_markup=get_server_actions_keyboard(row.id, row.status))
    await callback.answer()

@router.callback_query(F.data.startswith("srv_start_"))
async def start_server_callback(callback: CallbackQuery):
    server_id = callback.data.replace("srv_start_", "").strip()
    try:
        info = await server_manager.request_start(server_id)
        await callback.answer(f"Queued at position {info['queue_position']}!")
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return
    row = await _load_server(callback, server_id)
    if row:
        await callback.message.edit_text(_server_text(row), parse_mode="Markdown", reply_markup=get_server_actions_keyboard(row.id, row.status))

@router.callback_query(F.data.startswith("srv_stop_"))
async def stop_server_callback(callback: CallbackQuery):
    server_id = callback.data.replace("srv_stop_", "").strip()
    try:
        await server_manager.request_stop(server_id)
        await callback.answer("Server stopping...")
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return
    row = await _load_server(callback, server_id)
    if row:
        await callback.message.edit_text(_server_text(row), parse_mode="Markdown", reply_markup=get_server_actions_keyboard(row.id, row.status))

@router.callback_query(F.data.startswith("srv_restart_"))
async def restart_server_callback(callback: CallbackQuery):
    server_id = callback.data.replace("srv_restart_", "").strip()
    try:
        await server_manager.restart_server(server_id)
        await callback.answer("Restart queued!")
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return
    row = await _load_server(callback, server_id)
    if row:
        await callback.message.edit_text(_server_text(row), parse_mode="Markdown", reply_markup=get_server_actions_keyboard(row.id, row.status))

@router.callback_query(F.data.startswith("srv_backup_"))
async def backup_server_callback(callback: CallbackQuery):
    server_id = callback.data.replace("srv_backup_", "").strip()
    try:
        row = await server_manager.create_backup(server_id)
        await callback.answer(f"Backup created: {row.filename}")
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)

@router.callback_query(F.data.startswith("srv_delete_"))
async def delete_server_callback(callback: CallbackQuery):
    server_id = callback.data.replace("srv_delete_", "").strip()
    deleted = await server_manager.delete_server(server_id)
    if deleted:
        await callback.message.edit_text(f"🗑 Server `{server_id}` deleted.", parse_mode="Markdown", reply_markup=get_host_menu_keyboard())
        await callback.answer("Server deleted.")
    else:
        await callback.answer("Server not found.", show_alert=True)
