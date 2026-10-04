"""FastAPI routes for web dashboard and REST API."""
import psutil
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from config import settings
from ai.model_manager import model_manager
from storage.database import get_db
from storage.models import Project, BuildJob as DBBuildJob
from storage.storage_manager import storage
from jobs.queue import job_manager
from logger import get_logger

logger = get_logger("web.routes")
router = APIRouter()

templates_path = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Render Cyber Minecraft AI control panel."""
    with get_db() as db:
        raw_projects = db.query(Project).order_by(Project.updated_at.desc()).limit(15).all()
        projects = [
            {
                "id": p.id,
                "name": p.name,
                "edition": p.edition,
                "current_version": p.current_version,
                "status": p.status,
                "updated_at": p.updated_at
            }
            for p in raw_projects
        ]
        total_projects = db.query(Project).count()
        bedrock_count = db.query(Project).filter(Project.edition == "bedrock").count()
        fabric_count = db.query(Project).filter(Project.edition == "fabric").count()
        total_builds = db.query(DBBuildJob).count()
        success_builds = db.query(DBBuildJob).filter(DBBuildJob.status == "completed").count()

    hardware = model_manager.get_hardware_status()
    queue_len = job_manager.queue.qsize()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "ai": hardware,
            "projects": projects,
            "projects_count": total_projects,
            "bedrock_count": bedrock_count,
            "fabric_count": fabric_count,
            "total_builds": total_builds,
            "success_builds": success_builds,
            "queue_length": queue_len
        }
    )

@router.get("/health")
@router.get("/api/health")
async def health_check():
    """Health check verifying database, queue, and AI provider."""
    db_ok = False
    try:
        with get_db() as db:
            db.execute(Project.__table__.select().limit(1))
            db_ok = True
    except Exception as e:
        logger.error(f"Health check DB error: {e}")

    hw = model_manager.get_hardware_status()
    return {
        "status": "ok" if db_ok else "degraded",
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "telegram": bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_BOT_TOKEN != "YOUR_TELEGRAM_BOT_TOKEN"),
        "ai": {
            "provider": hw["provider"],
            "loaded": hw["is_loaded"],
            "model": hw["model_id"],
            "device": hw["device"]
        },
        "queue": job_manager.queue.qsize(),
        "database": db_ok
    }

@router.get("/api/projects")
async def list_projects():
    """Return all projects across users."""
    with get_db() as db:
        projs = db.query(Project).order_by(Project.updated_at.desc()).all()
        return [
            {
                "id": p.id,
                "user_id": p.user_id,
                "name": p.name,
                "namespace": p.namespace,
                "edition": p.edition,
                "current_version": p.current_version,
                "status": p.status,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "updated_at": p.updated_at.isoformat() if p.updated_at else None
            }
            for p in projs
        ]

@router.get("/api/jobs/{job_id}")
async def get_job_info(job_id: str):
    """Get status and logs for a build job."""
    job = job_manager.get_job(job_id)
    if job:
        return job.model_dump()
        
    with get_db() as db:
        db_job = db.query(DBBuildJob).filter(DBBuildJob.id == job_id).first()
        if not db_job:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "job_id": db_job.id,
            "project_id": db_job.project_id,
            "version": db_job.version_number,
            "status": db_job.status,
            "logs": db_job.logs,
            "error_message": db_job.error_message,
            "repair_attempts": db_job.repair_attempts,
            "artifact_url": db_job.artifact_url,
            "created_at": db_job.created_at.isoformat() if db_job.created_at else None
        }

@router.get("/api/system")
async def get_system_metrics():
    """Return real-time CPU, RAM, Disk, and GPU stats."""
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(str(settings.DATA_DIR))
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "ram_total_mb": int(vm.total / (1024 * 1024)),
        "ram_used_mb": int(vm.used / (1024 * 1024)),
        "ram_percent": vm.percent,
        "disk_total_mb": int(disk.total / (1024 * 1024)),
        "disk_free_mb": int(disk.free / (1024 * 1024)),
        "hardware": model_manager.get_hardware_status()
    }

@router.post("/api/ai/load")
async def load_ai_model():
    """Manually load AI model into memory."""
    ok = model_manager.load_model()
    return {"success": ok, "message": "Model loaded into memory" if ok else "Failed to load model"}

@router.post("/api/ai/unload")
async def unload_ai_model():
    """Manually unload AI model from memory."""
    ok = model_manager.unload_model()
    return {"success": ok, "message": "Model unloaded from memory"}

@router.get("/api/download/{user_id}/{project_id}/{version}")
async def download_artifact(user_id: str, project_id: str, version: int):
    """Download compiled mod artifact."""
    with get_db() as db:
        proj = db.query(Project).filter(Project.id == project_id, Project.user_id == user_id).first()
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")

    ext = ".mcaddon" if proj.edition == "bedrock" else ".jar"
    artifact = storage.get_artifact(user_id, project_id, version, ext)
    if not artifact or not artifact.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found on server")

    media_type = "application/zip" if ext == ".mcaddon" else "application/java-archive"
    return FileResponse(
        path=str(artifact),
        filename=artifact.name,
        media_type=media_type
    )
