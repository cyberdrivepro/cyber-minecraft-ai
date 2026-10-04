"""Build, download, status, and log handlers."""
import uuid
from pathlib import Path
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import Command
from bot.keyboards import get_project_actions_keyboard, get_main_menu_keyboard
from storage.database import get_db
from storage.models import Project, ProjectVersion
from storage.storage_manager import storage
from jobs.queue import BuildJobItem, job_manager
from logger import get_logger

logger = get_logger("bot.handlers.build")
router = Router(name="build_router")

@router.message(Command("build"))
@router.message(Command("rebuild"))
async def handle_build_cmd(message: Message):
    """Trigger a rebuild of the specified or latest project."""
    parts = message.text.strip().split()
    user_id = str(message.from_user.id)
    if len(parts) >= 2:
        project_id = parts[1].strip()
    else:
        with get_db() as db:
            proj = db.query(Project).filter(Project.user_id == user_id).order_by(Project.updated_at.desc()).first()
            if not proj:
                await message.answer("No project specified. Usage: `/build <PROJECT_ID>`", parse_mode="Markdown")
                return
            project_id = proj.id

    await _trigger_rebuild(message, project_id, user_id)

@router.callback_query(F.data.startswith("act_build_"))
async def handle_build_callback(callback: CallbackQuery):
    """Handle Rebuild button callback."""
    project_id = callback.data.replace("act_build_", "").strip()
    user_id = str(callback.from_user.id)
    await _trigger_rebuild(callback.message, project_id, user_id)
    await callback.answer("Rebuilding...")

async def _trigger_rebuild(message: Message, project_id: str, user_id: str):
    with get_db() as db:
        proj = db.query(Project).filter(Project.id == project_id, Project.user_id == user_id).first()
    if not proj:
        await message.answer(f"Project `{project_id}` not found.", parse_mode="Markdown")
        return

    spec = storage.get_project_spec(user_id, project_id)
    if not spec:
        await message.answer("Project data missing on disk.", parse_mode="Markdown")
        return

    new_version = proj.current_version + 1
    job_id = f"job_rebuild_{uuid.uuid4().hex[:8]}"

    status_msg = await message.answer(
        f"🔨 *Rebuilding {proj.name} (v{new_version})...*\n\nStatus: 📦 Generating project...",
        parse_mode="Markdown"
    )

    async def on_progress(j: BuildJobItem):
        try:
            if j.status == "completed":
                await status_msg.edit_text(
                    f"✅ *REBUILD READY!*\n• Project: `{j.project_id}`\n• Version: `v{j.version}`",
                    parse_mode="Markdown",
                    reply_markup=get_project_actions_keyboard(j.project_id)
                )
                if j.artifact_path:
                    doc = FSInputFile(j.artifact_path)
                    await message.answer_document(doc, caption=f"🎉 Mod file v{j.version}")
            elif j.status == "failed":
                await status_msg.edit_text(f"❌ *Build Failed*\n{j.error_message}", parse_mode="Markdown")
            else:
                await status_msg.edit_text(f"🔨 *Building* (`{j.project_id}` v{j.version})\n\nStage: {j.current_stage}", parse_mode="Markdown")
        except Exception:
            pass

    job = BuildJobItem(
        job_id=job_id,
        project_id=project_id,
        user_id=user_id,
        version=new_version,
        prompt=spec.get("description", "Rebuild"),
        edition=proj.edition,
        is_edit=False
    )
    await job_manager.enqueue(job, progress_callback=on_progress)

@router.message(Command("download"))
async def handle_download_cmd(message: Message):
    """Send mod file to user."""
    parts = message.text.strip().split()
    user_id = str(message.from_user.id)
    if len(parts) >= 2:
        project_id = parts[1].strip()
    else:
        with get_db() as db:
            proj = db.query(Project).filter(Project.user_id == user_id).order_by(Project.updated_at.desc()).first()
            if not proj:
                await message.answer("Usage: `/download <PROJECT_ID>`", parse_mode="Markdown")
                return
            project_id = proj.id

    await _send_mod_file(message, project_id, user_id)

@router.callback_query(F.data.startswith("act_download_"))
async def handle_download_callback(callback: CallbackQuery):
    project_id = callback.data.replace("act_download_", "").strip()
    user_id = str(callback.from_user.id)
    await _send_mod_file(callback.message, project_id, user_id)
    await callback.answer()

async def _send_mod_file(message: Message, project_id: str, user_id: str):
    with get_db() as db:
        proj = db.query(Project).filter(Project.id == project_id, Project.user_id == user_id).first()
    if not proj:
        await message.answer(f"Project `{project_id}` not found.", parse_mode="Markdown")
        return

    ext = ".mcaddon" if proj.edition == "bedrock" else ".jar"
    artifact = storage.get_artifact(user_id, project_id, proj.current_version, ext)
    if not artifact or not artifact.exists():
        await message.answer(f"Mod file for v{proj.current_version} not found. Try `/build {project_id}` first.", parse_mode="Markdown")
        return

    doc = FSInputFile(str(artifact))
    await message.answer_document(
        document=doc,
        caption=f"⬇ *{proj.name}* (v{proj.current_version})\nPlatform: {proj.edition.capitalize()}"
    )

@router.message(Command("logs"))
async def handle_logs_cmd(message: Message):
    """Return recent build logs for a project."""
    parts = message.text.strip().split()
    user_id = str(message.from_user.id)
    if len(parts) >= 2:
        project_id = parts[1].strip()
    else:
        with get_db() as db:
            proj = db.query(Project).filter(Project.user_id == user_id).order_by(Project.updated_at.desc()).first()
            if not proj:
                await message.answer("Usage: `/logs <PROJECT_ID>`", parse_mode="Markdown")
                return
            project_id = proj.id

    await _show_logs(message, project_id, user_id)

@router.callback_query(F.data.startswith("act_logs_"))
async def handle_logs_callback(callback: CallbackQuery):
    project_id = callback.data.replace("act_logs_", "").strip()
    user_id = str(callback.from_user.id)
    await _show_logs(callback.message, project_id, user_id)
    await callback.answer()

async def _show_logs(message: Message, project_id: str, user_id: str):
    proj_dir = storage.get_project_dir(user_id, project_id)
    log_file = proj_dir / "build.log"
    if not log_file.exists():
        await message.answer(f"No logs found for project `{project_id}`.", parse_mode="Markdown")
        return

    with open(log_file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        recent = "".join(lines[-25:])

    await message.answer(
        f"📜 *Build Logs for {project_id} (recent lines):*\n```\n{recent[:3500]}\n```",
        parse_mode="Markdown"
    )

@router.message(Command("status"))
@router.callback_query(F.data == "btn_build_queue")
async def handle_status_cmd(event: Message | CallbackQuery):
    """Display real-time build queue metrics."""
    qsize = job_manager.queue.qsize()
    active_count = len(job_manager.active_jobs)
    completed_count = len(job_manager.completed_jobs)

    text = (
        "🔨 *BUILD QUEUE STATUS*\n\n"
        f"• Pending in Queue: `{qsize}`\n"
        f"• Active Builds: `{active_count}`\n"
        f"• Max Concurrency: `{job_manager.max_concurrent}`\n"
        f"• Completed Today: `{completed_count}`\n\n"
    )
    if job_manager.active_jobs:
        text += "*Active Jobs:*\n"
        for jid, item in job_manager.active_jobs.items():
            text += f"• `{jid}` ({item.project_id}): {item.current_stage}\n"
    else:
        text += "Queue is currently idle. Ready for new builds!"

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=get_main_menu_keyboard())
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown")
