"""FastAPI routes for the web dashboard, authentication, and core REST API."""
import psutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends, Response
from pydantic import BaseModel
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from config import settings, SERVER_SOFTWARE
from ai.model_manager import model_manager
from core.clock import utcnow
from core.auth import (
    register_user,
    authenticate,
    create_session,
    destroy_session,
    session_user_from_request,
    require_user,
    require_admin,
    login_rate_limited,
    record_login_attempt,
    audit,
    bootstrap_admin,
    SESSION_COOKIE,
)
from storage.database import get_db
from storage.models import (
    Project, BuildJob as DBBuildJob, Server as DBServer,
    User as DBUser, AuditEvent, Schedule as DBSchedule,
)
from storage.storage_manager import storage
from servers.manager import server_manager, ServerStatus
from jobs.queue import job_manager
from logger import get_logger

logger = get_logger("web.routes")
router = APIRouter()

templates_path = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_path))

templates.env.globals["APP_NAME"] = settings.APP_NAME
templates.env.globals["APP_SUBTITLE"] = settings.APP_SUBTITLE
templates.env.globals["APP_VERSION"] = settings.APP_VERSION


def _page_context(request: Request, **extra) -> dict:
    user = session_user_from_request(request)
    ctx = {
        "user": {"id": user.id, "username": user.username, "role": user.role} if user else None,
        "auth_required": settings.AUTH_REQUIRED,
        "year": utcnow().year,
    }
    ctx.update(extra)
    return ctx


def _guard_page(request: Request):
    """Redirect unauthenticated users to /login when auth is required."""
    if settings.AUTH_REQUIRED and session_user_from_request(request) is None:
        return RedirectResponse(url="/login", status_code=303)
    return None


# ------------------------------------------------------------------ auth api
@router.post("/api/auth/register")
async def api_register(req: Request):
    if not settings.ALLOW_REGISTRATION:
        raise HTTPException(status_code=403, detail="Registration is disabled on this instance.")
    body = await req.json()
    try:
        user = register_user(body.get("username", ""), body.get("password", ""), body.get("first_name", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit(user.id, "account_registered")
    token = create_session(user.id, req.headers.get("user-agent", ""))
    resp = JSONResponse({"success": True, "username": user.username})
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=7 * 24 * 3600)
    return resp


@router.post("/api/auth/login")
async def api_login(req: Request):
    body = await req.json()
    ip = req.client.host if req.client else ""
    if login_rate_limited(ip):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in 15 minutes.")
    user = authenticate(body.get("username", ""), body.get("password", ""))
    if not user:
        record_login_attempt(ip)
        audit(None, "login_failed", detail=str(body.get("username", ""))[:64], ip=ip)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_session(user.id, req.headers.get("user-agent", ""))
    audit(user.id, "login_success", ip=ip)
    resp = JSONResponse({"success": True, "username": user.username, "role": user.role})
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=7 * 24 * 3600)
    return resp


@router.post("/api/auth/logout")
async def api_logout(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    user = session_user_from_request(request)
    if token:
        destroy_session(token)
    if user:
        audit(user.id, "logout")
    resp = JSONResponse({"success": True})
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@router.get("/api/auth/me")
async def api_me(request: Request):
    user = session_user_from_request(request)
    if not user:
        return {"authenticated": False}
    return {"authenticated": True, "id": user.id, "username": user.username, "role": user.role}


# ------------------------------------------------------------------ auth pages
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if session_user_from_request(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context=_page_context(request))


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    if not settings.ALLOW_REGISTRATION:
        return RedirectResponse(url="/login", status_code=303)
    if session_user_from_request(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request=request, name="register.html", context=_page_context(request))


@router.get("/logout")
async def logout_page(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        destroy_session(token)
    resp = RedirectResponse(url="/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp

# -------------------------------------------------------------------- pages
@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Render the Cyber Control Center overview."""
    redirect = _guard_page(request)
    if redirect:
        return redirect
    with get_db() as db:
        user = session_user_from_request(request)
        query = db.query(DBServer)
        raw_servers = query.order_by(DBServer.created_at.desc()).all()
        servers = [server_manager.serialize(s) for s in raw_servers]
        projects = db.query(Project).order_by(Project.updated_at.desc()).limit(8).all()
        total_projects = db.query(Project).count()
        total_builds = db.query(DBBuildJob).count()
        success_builds = db.query(DBBuildJob).filter(DBBuildJob.status == "completed").count()
        user_count = db.query(DBUser).count()
        recent_audit = db.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(8).all()
        schedule_count = db.query(DBSchedule).filter(DBSchedule.enabled.is_(True)).count()

    hardware = model_manager.get_hardware_status()
    queue_len = job_manager.queue.qsize()
    online_servers = sum(1 for s in servers if s["status"] == "online")
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(str(settings.DATA_DIR))

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=_page_context(
            request,
            ai=hardware,
            projects=[
                {"id": p.id, "name": p.name, "edition": p.edition,
                 "current_version": p.current_version, "status": p.status}
                for p in projects
            ],
            projects_count=total_projects,
            total_builds=total_builds,
            success_builds=success_builds,
            queue_length=queue_len,
            max_concurrent=job_manager.max_concurrent,
            servers=servers,
            servers_count=len(servers),
            online_servers=online_servers,
            user_count=user_count,
            schedule_count=schedule_count,
            recent_audit=[
                {"action": a.action, "target": a.target, "user_id": a.user_id,
                 "created_at": a.created_at.strftime("%m-%d %H:%M") if a.created_at else ""}
                for a in recent_audit
            ],
            cpu_percent=psutil.cpu_percent(interval=0.1),
            ram_percent=vm.percent,
            ram_used_gb=round(vm.used / (1024 ** 3), 1),
            ram_total_gb=round(vm.total / (1024 ** 3), 1),
            disk_percent=disk.percent,
            disk_free_gb=round(disk.free / (1024 ** 3), 1),
        )
    )


@router.get("/servers", response_class=HTMLResponse)
async def servers_page(request: Request):
    redirect = _guard_page(request)
    if redirect:
        return redirect
    user = session_user_from_request(request)
    with get_db() as db:
        rows = db.query(DBServer).order_by(DBServer.created_at.desc()).all()
        servers = [server_manager.serialize(s) for s in rows]
    return templates.TemplateResponse(
        request=request, name="servers.html",
        context=_page_context(request, servers=servers)
    )


@router.get("/servers/new", response_class=HTMLResponse)
async def new_server_page(request: Request):
    redirect = _guard_page(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(
        request=request, name="server_new.html",
        context=_page_context(request, software=SERVER_SOFTWARE)
    )


@router.get("/ai", response_class=HTMLResponse)
async def ai_studio_page(request: Request):
    redirect = _guard_page(request)
    if redirect:
        return redirect
    with get_db() as db:
        projects = db.query(Project).order_by(Project.updated_at.desc()).limit(50).all()
        jobs = db.query(DBBuildJob).order_by(DBBuildJob.created_at.desc()).limit(20).all()
    hardware = model_manager.get_hardware_status()
    return templates.TemplateResponse(
        request=request, name="ai_studio.html",
        context=_page_context(
            request,
            ai=hardware,
            projects=[
                {"id": p.id, "user_id": p.user_id, "name": p.name, "edition": p.edition,
                 "current_version": p.current_version, "status": p.status,
                 "updated_at": p.updated_at.strftime("%Y-%m-%d %H:%M") if p.updated_at else ""}
                for p in projects
            ],
            jobs=[
                {"id": j.id, "project_id": j.project_id, "status": j.status,
                 "created_at": j.created_at.strftime("%Y-%m-%d %H:%M") if j.created_at else ""}
                for j in jobs
            ],
        )
    )


@router.get("/system", response_class=HTMLResponse)
async def system_page(request: Request):
    redirect = _guard_page(request)
    if redirect:
        return redirect
    import platform as _platform
    from servers.runtime import find_java_executable
    java_path = find_java_executable()
    return templates.TemplateResponse(
        request=request, name="system.html",
        context=_page_context(
            request,
            platform=f"{_platform.system()} {_platform.release()} ({_platform.machine()})",
            python_version=_platform.python_version(),
            data_dir=str(settings.DATA_DIR),
            database_url=settings.DATABASE_URL.split(":///")[-1] if settings.DATABASE_URL else "n/a",
            java_available="yes" if java_path else "not found — real server jars cannot run",
            java_path=java_path,
            ai=model_manager.get_hardware_status(),
            queue_length=job_manager.queue.qsize(),
            max_concurrent=job_manager.max_concurrent,
            telegram_configured=bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_BOT_TOKEN != "YOUR_TELEGRAM_BOT_TOKEN"),
        )
    )


@router.get("/links", response_class=HTMLResponse)
async def links_page(request: Request):
    redirect = _guard_page(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="links.html", context=_page_context(request))


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    redirect = _guard_page(request)
    if redirect:
        return redirect
    user = session_user_from_request(request)
    if user is None or user.role != "admin":
        return templates.TemplateResponse(request=request, name="denied.html", context=_page_context(request), status_code=403)
    return templates.TemplateResponse(request=request, name="admin.html", context=_page_context(request))


@router.get("/docs", response_class=HTMLResponse)
async def docs_page(request: Request):
    redirect = _guard_page(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request=request, name="docs.html", context=_page_context(request))

# ------------------------------------------------------------------ core API
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
async def list_projects(user=Depends(require_user)):
    """Return the current user's projects (admins see all)."""
    with get_db() as db:
        q = db.query(Project).order_by(Project.updated_at.desc())
        if user.role != "admin":
            q = q.filter(Project.user_id == user.id)
        projs = q.all()
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
async def get_job_info(job_id: str, user=Depends(require_user)):
    """Get status and logs for a build job."""
    job = job_manager.get_job(job_id)
    if job:
        return job.model_dump()

    with get_db() as db:
        db_job = db.query(DBBuildJob).filter(DBBuildJob.id == job_id).first()
        if not db_job:
            raise HTTPException(status_code=404, detail="Job not found")
        project = db.query(Project).filter(Project.id == db_job.project_id).first()
        if user.role != "admin" and project and project.user_id != user.id:
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
        "queue_length": job_manager.queue.qsize(),
        "hardware": model_manager.get_hardware_status()
    }

@router.get("/api/ai/providers")
async def ai_provider_status(user=Depends(require_user)):
    """Which AI providers are configured (booleans only — no secrets)."""
    return {
        "active_provider": settings.AI_PROVIDER,
        "local_model": settings.LOCAL_MODEL_ID,
        "local_loaded": model_manager.is_loaded,
        "providers": {
            "local": True,
            "huggingface_inference": bool(settings.HF_TOKEN),
            "groq": bool(settings.GROQ_API_KEY),
            "openrouter": bool(settings.OPENROUTER_API_KEY),
            "custom_openai": bool(settings.OPENAI_API_KEY),
        },
        "hardware": model_manager.get_hardware_status(),
    }

@router.post("/api/ai/load")
async def load_ai_model(user=Depends(require_user)):
    """Manually load AI model into memory."""
    ok = model_manager.load_model()
    audit(user.id, "ai_model_loaded")
    return {"success": ok, "message": "Model loaded into memory" if ok else "Failed to load model"}

@router.post("/api/ai/unload")
async def unload_ai_model(user=Depends(require_user)):
    """Manually unload AI model from memory."""
    ok = model_manager.unload_model()
    return {"success": ok, "message": "Model unloaded from memory"}

@router.get("/api/download/{user_id}/{project_id}/{version}")
async def download_artifact(user_id: str, project_id: str, version: int, user=Depends(require_user)):
    """Download compiled mod artifact (owner or admin only)."""
    if user.role != "admin" and user.id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
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

# ---------------------------------------------------------------- admin API
@router.get("/api/admin/overview")
async def admin_overview(user=Depends(require_admin)):
    """Platform-wide status for the admin dashboard."""
    with get_db() as db:
        from storage.models import ServerShare, DownloadToken, ScheduleRun
        return {
            "users": db.query(DBUser).count(),
            "servers": db.query(DBServer).count(),
            "servers_online": db.query(DBServer).filter(DBServer.status == ServerStatus.ONLINE).count(),
            "servers_error": db.query(DBServer).filter(DBServer.status == ServerStatus.ERROR).count(),
            "projects": db.query(Project).count(),
            "builds": db.query(DBBuildJob).count(),
            "builds_failed": db.query(DBBuildJob).filter(DBBuildJob.status == "failed").count(),
            "shares": db.query(ServerShare).count(),
            "active_links": db.query(DownloadToken).filter(DownloadToken.revoked.is_(False)).count(),
            "schedules": db.query(DBSchedule).filter(DBSchedule.enabled.is_(True)).count(),
            "queue_length": job_manager.queue.qsize(),
            "recent_audit": [
                {"id": a.id, "user_id": a.user_id, "action": a.action, "target": a.target,
                 "detail": a.detail, "ip": a.ip,
                 "created_at": a.created_at.isoformat() if a.created_at else None}
                for a in db.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(30).all()
            ],
        }


@router.get("/api/admin/users")
async def admin_list_users(user=Depends(require_admin)):
    with get_db() as db:
        users = db.query(DBUser).order_by(DBUser.created_at.desc()).limit(200).all()
        return [
            {"id": u.id, "username": u.username, "role": u.role,
             "telegram_linked": u.telegram_linked,
             "created_at": u.created_at.isoformat() if u.created_at else None}
            for u in users
        ]


class RoleUpdateRequest(BaseModel):
    role: str

@router.post("/api/admin/users/{user_id}/role")
async def admin_set_role(user_id: str, req: RoleUpdateRequest, user=Depends(require_admin)):
    if req.role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="Role must be 'user' or 'admin'.")
    if user_id == user.id:
        raise HTTPException(status_code=400, detail="You cannot change your own role.")
    with get_db() as db:
        target = db.query(DBUser).filter(DBUser.id == user_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        target.role = req.role
    audit(user.id, "admin_role_changed", target=user_id, detail=req.role)
    return {"success": True}
