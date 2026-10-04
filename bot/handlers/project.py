"""Project management handlers: creation, listing, inspection, and deletion."""
import uuid
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.keyboards import (
    get_edition_keyboard,
    get_project_actions_keyboard,
    get_cancel_keyboard,
    get_main_menu_keyboard
)
from storage.database import get_db
from storage.models import Project, ProjectVersion
from storage.storage_manager import storage
from jobs.queue import BuildJobItem, job_manager
from jobs.runner import execute_build_job
from logger import get_logger

logger = get_logger("bot.handlers.project")
router = Router(name="project_router")

class NewModStates(StatesGroup):
    waiting_for_edition = State()
    waiting_for_prompt = State()

@router.message(Command("newmod"))
@router.callback_query(F.data == "btn_new_mod")
async def start_new_mod(event: Message | CallbackQuery, state: FSMContext):
    """Initiate new mod creation wizard."""
    await state.clear()
    await state.set_state(NewModStates.waiting_for_edition)
    
    text = (
        "🛠 *NEW MINECRAFT MOD WIZARD*\n\n"
        "Choose the target Minecraft platform for your mod:"
    )
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=get_edition_keyboard())
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown", reply_markup=get_edition_keyboard())

@router.callback_query(NewModStates.waiting_for_edition, F.data.startswith("edition_"))
async def process_edition(callback: CallbackQuery, state: FSMContext):
    """Handle edition selection and prompt for mod description."""
    edition = "bedrock" if callback.data == "edition_bedrock" else "fabric"
    await state.update_data(edition=edition)
    await state.set_state(NewModStates.waiting_for_prompt)

    edition_name = "Bedrock Add-on (.mcaddon)" if edition == "bedrock" else "Java Fabric Mod (.jar)"
    prompt_msg = (
        f"🎯 Selected: *{edition_name}*\n\n"
        f"Now, describe the mod you want to create in natural language!\n\n"
        f"💡 *Example:*\n"
        f"_\"Create a ruby sword called Blood Ruby Sword. "
        f"Damage 14. Durability 1800. "
        f"Create a recipe using diamonds and redstone.\"_\n\n"
        f"Type your description below:"
    )
    await callback.message.edit_text(prompt_msg, parse_mode="Markdown", reply_markup=get_cancel_keyboard())
    await callback.answer()

@router.message(NewModStates.waiting_for_prompt, F.text)
async def process_prompt(message: Message, state: FSMContext):
    """Receive user's mod description and launch build job."""
    data = await state.get_data()
    edition = data.get("edition", "bedrock")
    user_prompt = message.text.strip()
    await state.clear()

    user_id = str(message.from_user.id)
    project_id = f"proj_{uuid.uuid4().hex[:8]}"
    job_id = f"job_{uuid.uuid4().hex[:8]}"

    status_msg = await message.answer(
        f"🚀 *Mod Creation Job Submitted!*\n\n"
        f"• Project ID: `{project_id}`\n"
        f"• Edition: *{edition.capitalize()}*\n"
        f"• Status: 🧠 Understanding request...\n\n"
        f"_Please wait while AI analyzes and builds your mod..._",
        parse_mode="Markdown"
    )

    # Progress updater callback to update the Telegram message in real time
    async def on_progress(j: BuildJobItem):
        try:
            if j.status == "completed":
                ready_text = (
                    f"✅ *MOD READY!*\n\n"
                    f"• Project ID: `{j.project_id}`\n"
                    f"• Version: `v{j.version}`\n"
                    f"• Status: {j.current_stage}\n\n"
                    f"Sending your download file now..."
                )
                await status_msg.edit_text(ready_text, parse_mode="Markdown", reply_markup=get_project_actions_keyboard(j.project_id))
                
                # Send file directly to chat
                if j.artifact_path:
                    doc = FSInputFile(j.artifact_path)
                    await message.answer_document(
                        document=doc,
                        caption=f"🎉 Here is your Minecraft mod file!\nEdition: {j.edition.capitalize()}"
                    )
            elif j.status == "failed":
                fail_text = (
                    f"❌ *Build Failed*\n\n"
                    f"• Project ID: `{j.project_id}`\n"
                    f"• Error: {j.error_message or 'Unknown error'}\n\n"
                    f"Use `/logs {j.project_id}` to inspect full logs or `/edit {j.project_id}` to modify."
                )
                await status_msg.edit_text(fail_text, parse_mode="Markdown", reply_markup=get_project_actions_keyboard(j.project_id))
            else:
                progress_text = (
                    f"🔨 *Building Mod* (`{j.project_id}`)\n\n"
                    f"Stage: {j.current_stage}\n"
                    f"Version: `v{j.version}`"
                )
                await status_msg.edit_text(progress_text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Failed to update Telegram message: {e}")

    # Create and enqueue job
    job = BuildJobItem(
        job_id=job_id,
        project_id=project_id,
        user_id=user_id,
        version=1,
        prompt=user_prompt,
        edition=edition,
        is_edit=False
    )
    await job_manager.enqueue(job, progress_callback=on_progress)

@router.message(Command("myprojects"))
@router.callback_query(F.data == "btn_my_projects")
async def list_my_projects(event: Message | CallbackQuery):
    """List all projects for the requesting user."""
    user_id = str(event.from_user.id)
    with get_db() as db:
        projs = db.query(Project).filter(Project.user_id == user_id).order_by(Project.updated_at.desc()).all()

    if not projs:
        msg = "📦 You haven't created any mods yet!\nUse `/newmod` to build your first mod."
        if isinstance(event, CallbackQuery):
            await event.message.edit_text(msg, reply_markup=get_main_menu_keyboard())
            await event.answer()
        else:
            await event.answer(msg, reply_markup=get_main_menu_keyboard())
        return

    text = "📦 *YOUR MINECRAFT MODS:*\n\n"
    for p in projs:
        text += (
            f"🔹 *{p.name}* (`{p.id}`)\n"
            f"   Platform: {p.edition.capitalize()} | Version: v{p.current_version}\n"
            f"   Status: `{p.status}` | Namespace: `{p.namespace}`\n\n"
        )
    text += "Use `/project <id>` or `/edit <id>` to manage a specific project."

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown")

@router.message(Command("project"))
async def view_project(message: Message):
    """View details and actions for a project."""
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Usage: `/project <PROJECT_ID>`", parse_mode="Markdown")
        return

    project_id = parts[1].strip()
    user_id = str(message.from_user.id)

    with get_db() as db:
        proj = db.query(Project).filter(Project.id == project_id, Project.user_id == user_id).first()

    if not proj:
        await message.answer(f"Project `{project_id}` not found.", parse_mode="Markdown")
        return

    spec = storage.get_project_spec(user_id, project_id)
    items_count = len(spec.get("items", [])) if spec else 0
    recipes_count = len(spec.get("recipes", [])) if spec else 0
    blocks_count = len(spec.get("blocks", [])) if spec else 0

    text = (
        f"⚔ *PROJECT: {proj.name}*\n\n"
        f"• ID: `{proj.id}`\n"
        f"• Platform: *{proj.edition.capitalize()}*\n"
        f"• Version: `v{proj.current_version}`\n"
        f"• Namespace: `{proj.namespace}`\n"
        f"• Status: `{proj.status}`\n"
        f"• Elements: {items_count} items, {recipes_count} recipes, {blocks_count} blocks\n\n"
        f"Select an action below:"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=get_project_actions_keyboard(proj.id))

@router.callback_query(F.data.startswith("act_delete_"))
async def delete_project_callback(callback: CallbackQuery):
    """Delete a mod project."""
    project_id = callback.data.replace("act_delete_", "").strip()
    user_id = str(callback.from_user.id)

    with get_db() as db:
        proj = db.query(Project).filter(Project.id == project_id, Project.user_id == user_id).first()
        if proj:
            db.delete(proj)

    storage.delete_project_data(user_id, project_id)
    await callback.message.edit_text(f"🗑 Project `{project_id}` deleted successfully.", parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
    await callback.answer("Project deleted.")

@router.message(Command("cancel"))
@router.callback_query(F.data == "btn_cancel")
async def cancel_handler(event: Message | CallbackQuery, state: FSMContext):
    """Cancel active operation."""
    await state.clear()
    msg = "❌ Operation cancelled. Back to main menu."
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(msg, reply_markup=get_main_menu_keyboard())
        await event.answer()
    else:
        await event.answer(msg, reply_markup=get_main_menu_keyboard())
