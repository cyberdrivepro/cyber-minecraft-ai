"""Conversational Mod Editor handlers for live versioned modifications."""
import uuid
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from bot.keyboards import get_cancel_keyboard, get_project_actions_keyboard
from storage.database import get_db
from storage.models import Project, ProjectVersion
from storage.storage_manager import storage
from jobs.queue import BuildJobItem, job_manager
from logger import get_logger

logger = get_logger("bot.handlers.editor")
router = Router(name="editor_router")

class EditStates(StatesGroup):
    waiting_for_instruction = State()

@router.message(Command("edit"))
async def handle_edit_cmd(message: Message, state: FSMContext):
    """Initiate /edit command."""
    parts = message.text.strip().split()
    user_id = str(message.from_user.id)
    
    if len(parts) >= 2:
        project_id = parts[1].strip()
    else:
        # Pick the most recently updated project
        with get_db() as db:
            proj = db.query(Project).filter(Project.user_id == user_id).order_by(Project.updated_at.desc()).first()
            if not proj:
                await message.answer("You don't have any projects to edit yet. Use `/newmod` first.", parse_mode="Markdown")
                return
            project_id = proj.id

    await _prompt_for_edit(message, state, project_id, user_id)

@router.callback_query(F.data.startswith("act_edit_"))
async def handle_edit_callback(callback: CallbackQuery, state: FSMContext):
    """Handle Edit Mod button callback."""
    project_id = callback.data.replace("act_edit_", "").strip()
    user_id = str(callback.from_user.id)
    await _prompt_for_edit(callback.message, state, project_id, user_id)
    await callback.answer()

async def _prompt_for_edit(message: Message, state: FSMContext, project_id: str, user_id: str):
    """Display prompt asking user for natural language edit instructions."""
    with get_db() as db:
        proj = db.query(Project).filter(Project.id == project_id, Project.user_id == user_id).first()

    if not proj:
        await message.answer(f"Project `{project_id}` not found.", parse_mode="Markdown")
        return

    await state.update_data(project_id=project_id, edition=proj.edition, current_version=proj.current_version)
    await state.set_state(EditStates.waiting_for_instruction)

    edit_text = (
        f"✏ *CONVERSATIONAL MOD EDITOR*\n\n"
        f"Project: *{proj.name}* (`{proj.id}`)\n"
        f"Active Version: `v{proj.current_version}`\n\n"
        f"What would you like to change in this mod?\n\n"
        f"💡 *Examples:*\n"
        f"• _\"Make damage 30\"_\n"
        f"• _\"Change plasma from blue to red\"_\n"
        f"• _\"Add crafting recipe with iron and sticks\"_\n"
        f"• _\"Make the boss twice as strong\"_\n"
        f"• _\"Remove explosion ability\"_\n\n"
        f"Type your modification below:"
    )
    await message.answer(edit_text, parse_mode="Markdown", reply_markup=get_cancel_keyboard())

@router.message(EditStates.waiting_for_instruction, F.text)
async def process_edit_instruction(message: Message, state: FSMContext):
    """Process natural language modification instruction and enqueue rebuild job."""
    data = await state.get_data()
    project_id = data["project_id"]
    edition = data.get("edition", "bedrock")
    curr_version = data.get("current_version", 1)
    new_version = curr_version + 1
    instruction = message.text.strip()
    await state.clear()

    user_id = str(message.from_user.id)
    job_id = f"job_edit_{uuid.uuid4().hex[:8]}"

    status_msg = await message.answer(
        f"⚡ *Applying Modification to v{new_version}...*\n\n"
        f"• Project: `{project_id}`\n"
        f"• Change: _{instruction}_\n"
        f"• Status: 🧠 Understanding modification...",
        parse_mode="Markdown"
    )

    async def on_progress(j: BuildJobItem):
        try:
            if j.status == "completed":
                ready_text = (
                    f"✅ *MOD UPDATED TO v{j.version}!*\n\n"
                    f"• Project ID: `{j.project_id}`\n"
                    f"• Version: `v{j.version}`\n\n"
                    f"Sending updated file now..."
                )
                await status_msg.edit_text(ready_text, parse_mode="Markdown", reply_markup=get_project_actions_keyboard(j.project_id))
                if j.artifact_path:
                    doc = FSInputFile(j.artifact_path)
                    await message.answer_document(
                        document=doc,
                        caption=f"🚀 Here is your updated mod file (v{j.version})!"
                    )
            elif j.status == "failed":
                fail_text = f"❌ *Update Failed*\n\nError: {j.error_message or 'Unknown error'}"
                await status_msg.edit_text(fail_text, parse_mode="Markdown", reply_markup=get_project_actions_keyboard(j.project_id))
            else:
                p_text = f"🔨 *Updating Mod* (`{j.project_id}` v{j.version})\n\nStage: {j.current_stage}"
                await status_msg.edit_text(p_text, parse_mode="Markdown")
        except Exception as e:
            logger.warning(f"Error in edit Telegram progress updater: {e}")

    job = BuildJobItem(
        job_id=job_id,
        project_id=project_id,
        user_id=user_id,
        version=new_version,
        prompt=instruction,
        edition=edition,
        is_edit=True
    )
    await job_manager.enqueue(job, progress_callback=on_progress)
