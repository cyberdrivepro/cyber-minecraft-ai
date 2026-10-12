"""FastAPI routes for Cyber Host: hosted Minecraft server management API and UI.

Every endpoint enforces authentication (when enabled) and per-server
authorization: owners, users holding a share, and platform admins only.
"""
import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from config import settings, SERVER_SOFTWARE
from core.clock import utcnow
from servers.manager import server_manager, ServerStatus
from servers.runtime import find_java_executable
from servers.networking import diagnose_server, public_host
from servers.scheduler import scheduler, compute_next_run
from core.auth import (
    require_user,
    require_server_access,
    require_admin,
    session_user_from_request,
    audit,
    ROLE_LEVELS,
)
from core import tokens as download_tokens
from core.exceptions import SecurityError
from storage.database import get_db
from storage.models import (
    Server as DBServer,
    ServerBackup as DBServerBackup,
    Schedule as DBSchedule,
    ScheduleRun as DBScheduleRun,
    ServerShare as DBServerShare,
    User as DBUser,
)

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

COMMAND_RATE_LIMIT = 20  # commands per 10 seconds per user
_command_times: dict = {}


def _check_command_rate(user_id: str) -> None:
    import time as _time
    now = _time.monotonic()
    recent = [t for t in _command_times.get(user_id, []) if now - t < 10]
    if len(recent) >= COMMAND_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Command rate limit reached; slow down.")
    recent.append(now)
    _command_times[user_id] = recent


class CreateServerRequest(BaseModel):
    name: str
    description: Optional[str] = None
    software: str = "paper"
    mc_version: str = "1.21.4"
    motd: Optional[str] = None
    level_seed: Optional[str] = None
    eula_accepted: bool = False
    gamemode: str = "survival"
    difficulty: str = "normal"
    max_players: int = 20
    pvp: bool = True
    whitelist_enabled: bool = False

class CommandRequest(BaseModel):
    command: str

class PlayerRequest(BaseModel):
    kind: str  # ops, whitelist, bans
    action: str  # add, remove
    player: str

class PropertiesUpdateRequest(BaseModel):
    properties: dict

class ScheduleCreateRequest(BaseModel):
    name: str
    action: str  # backup, restart, stop, start, save, command
    payload: Optional[str] = None
    interval_minutes: Optional[int] = None
    daily_time: Optional[str] = None
    enabled: bool = True

class ScheduleUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    name: Optional[str] = None

class ShareRequest(BaseModel):
    username: str
    role: str = "viewer"


# ------------------------------------------------------------------ catalog
@router.get("/api/host/catalog")


async def host_catalog():
    """Software catalog + host capabilities for the create-server UI."""
    return {
        "software": SERVER_SOFTWARE,
        "max_servers_per_owner": settings.MAX_SERVERS_PER_OWNER,
        "max_concurrent_servers": settings.MAX_CONCURRENT_SERVERS,
        "java_available": find_java_executable() is not None,
        "public_host": public_host(),
        "public_host_configured": bool(settings.SERVER_PUBLIC_HOST),
    }

# --------------------------------------------------------------------- CRUD
@router.get("/api/servers")


async def list_servers(user=Depends(require_user)):
    """List servers the current user owns or has shared access to."""
    visible_ids = _visible_server_ids(user)
    with get_db() as db:
        rows = (
            db.query(DBServer)
            .filter(DBServer.id.in_(visible_ids))
            .order_by(DBServer.created_at.desc())
            .all() if visible_ids else []
        )
        return [server_manager.serialize(r) for r in rows]


def _visible_server_ids(user) -> List[str]:
    with get_db() as db:
        owned = [r[0] for r in db.query(DBServer.id).filter(DBServer.owner_id == user.id).all()]
        shared = [r[0] for r in db.query(DBServerShare.server_id).filter(DBServerShare.user_id == user.id).all()]
    if user.role == "admin":
        with get_db() as db:
            owned = [r[0] for r in db.query(DBServer.id).all()]
    return owned + shared


@router.post("/api/servers")


async def create_server(req: CreateServerRequest, user=Depends(require_user)):
    """Create a new hosted Minecraft server owned by the current user."""
    try:
        row = server_manager.create_server(
            owner_id=user.id,
            name=req.name,
            software=req.software,
            mc_version=req.mc_version,
            motd=req.motd or "A Cyber Host server",
            level_seed=req.level_seed or "",
            eula_accepted=req.eula_accepted,
            description=req.description or "",
            gamemode=req.gamemode,
            difficulty=req.difficulty,
            max_players=req.max_players,
            pvp=req.pvp,
            whitelist_enabled=req.whitelist_enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit(user.id, "server_created", target=row.id, detail=f"{req.software} {req.mc_version}")
    return server_manager.serialize(row)

@router.get("/api/servers/{server_id}")


async def get_server(server_id: str, user=Depends(require_user)):
    """Full server state: status, console tail, players, backups, files."""
    require_server_access(user, server_id, "viewer")
    return await _server_snapshot(server_id)


async def _server_snapshot(server_id: str) -> dict:
    with get_db() as db:
        row = db.query(DBServer).filter(DBServer.id == server_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Server not found")
        backups = (
            db.query(DBServerBackup)
            .filter(DBServerBackup.server_id == server_id)
            .order_by(DBServerBackup.created_at.desc())
            .all()
        )
        backup_list = [
            {"id": b.id, "filename": b.filename, "size_bytes": b.size_bytes, "kind": b.kind,
             "created_at": b.created_at.isoformat() if b.created_at else None}
            for b in backups
        ]
    data = server_manager.serialize(row)
    data["console"] = server_manager.get_console(server_id, tail=300)
    data["players"] = {
        "ops": await server_manager.list_players(server_id, "ops"),
        "whitelist": await server_manager.list_players(server_id, "whitelist"),
        "bans": await server_manager.list_players(server_id, "bans")
    }
    data["backups"] = backup_list
    data["files"] = server_manager.list_files(server_id)
    data["properties"] = await server_manager.get_properties(server_id)
    return data

@router.delete("/api/servers/{server_id}")


async def delete_server(server_id: str, user=Depends(require_user)):
    """Permanently delete a server and its files (owner or platform admin only)."""
    require_server_access(user, server_id, "owner")
    deleted = await server_manager.delete_server(server_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Server not found")
    audit(user.id, "server_deleted", target=server_id)
    return {"success": True, "message": f"Server {server_id} deleted"}

# ------------------------------------------------------------ power control
@router.post("/api/servers/{server_id}/start")


async def start_server(server_id: str, user=Depends(require_user)):
    """Queue a start request (Aternos-style queue)."""
    require_server_access(user, server_id, "viewer")
    try:
        result = await server_manager.request_start(server_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    audit(user.id, "server_start", target=server_id)
    return result

@router.post("/api/servers/{server_id}/stop")


async def stop_server(server_id: str, user=Depends(require_user)):
    require_server_access(user, server_id, "moderator")
    try:
        await server_manager.request_stop(server_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    audit(user.id, "server_stop", target=server_id)
    return {"success": True, "message": "Stop requested"}

@router.post("/api/servers/{server_id}/restart")


async def restart_server(server_id: str, user=Depends(require_user)):
    require_server_access(user, server_id, "moderator")
    try:
        await server_manager.restart_server(server_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    audit(user.id, "server_restart", target=server_id)
    return {"success": True, "message": "Restart queued"}

# ------------------------------------------------------------------ console
@router.get("/api/servers/{server_id}/console")


async def server_console(server_id: str, tail: int = 200, user=Depends(require_user)):
    require_server_access(user, server_id, "viewer")
    with get_db() as db:
        if not db.query(DBServer).filter(DBServer.id == server_id).first():
            raise HTTPException(status_code=404, detail="Server not found")
    return {"server_id": server_id, "lines": server_manager.get_console(server_id, tail=tail)}


@router.get("/api/servers/{server_id}/console/stream")


async def stream_console(server_id: str, user=Depends(require_user)):
    """Server-sent events stream of live console output (authenticated)."""
    require_server_access(user, server_id, "viewer")
    with get_db() as db:
        if not db.query(DBServer).filter(DBServer.id == server_id).first():
            raise HTTPException(status_code=404, detail="Server not found")

    async def event_stream():
        sent = 0
        idle_ticks = 0
        while idle_ticks < 3600:  # cap a connection at ~1h of silence
            lines = server_manager.get_console(server_id, tail=10000)
            fresh = lines[sent:]
            if fresh:
                sent = len(lines)
                idle_ticks = 0
                payload = "".join(f"data: {json.dumps(line)}\n\n" for line in fresh)
                yield payload
            else:
                idle_ticks += 1
                yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/servers/{server_id}/command")


async def server_command(server_id: str, req: CommandRequest, user=Depends(require_user)):
    require_server_access(user, server_id, "moderator")
    _check_command_rate(user.id)
    if len(req.command) > 256:
        raise HTTPException(status_code=400, detail="Command too long (max 256 characters).")
    try:
        output = await server_manager.send_command(server_id, req.command)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    audit(user.id, "console_command", target=server_id, detail=req.command[:200])
    return {"success": True, "output": output}

# ------------------------------------------------------------------ players
@router.get("/api/servers/{server_id}/players")


async def list_players(server_id: str, kind: str = "ops", user=Depends(require_user)):
    require_server_access(user, server_id, "viewer")
    try:
        return {"kind": kind, "players": await server_manager.list_players(server_id, kind)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/servers/{server_id}/players")


async def manage_player(server_id: str, req: PlayerRequest, user=Depends(require_user)):
    require_server_access(user, server_id, "moderator")
    try:
        message = await server_manager.manage_player(server_id, req.kind, req.action, req.player)
        players = await server_manager.list_players(server_id, req.kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit(user.id, f"player_{req.action}", target=server_id, detail=f"{req.kind}:{req.player}")
    return {"success": True, "message": message, "players": players}

# --------------------------------------------------------------- properties
@router.get("/api/servers/{server_id}/properties")


async def get_properties(server_id: str, user=Depends(require_user)):
    require_server_access(user, server_id, "viewer")
    return await server_manager.get_properties(server_id)

@router.put("/api/servers/{server_id}/properties")


async def set_properties(server_id: str, req: PropertiesUpdateRequest, user=Depends(require_user)):
    require_server_access(user, server_id, "admin")
    try:
        applied = await server_manager.set_properties(server_id, req.properties)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    audit(user.id, "properties_updated", target=server_id, detail=", ".join(sorted(applied)))
    return {"success": True, "applied": applied}

# ----------------------------------------------------------------- worlds
@router.get("/api/servers/{server_id}/worlds")


async def list_worlds(server_id: str, user=Depends(require_user)):
    require_server_access(user, server_id, "viewer")
    return server_manager.list_worlds(server_id)


@router.post("/api/servers/{server_id}/worlds/import")


async def import_world(server_id: str, file: UploadFile = File(...), name: str = "imported", user=Depends(require_user)):
    """Import a world zip archive (server must be offline)."""
    require_server_access(user, server_id, "admin")
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="World imports must be .zip archives.")
    max_bytes = settings.SERVER_JAR_MAX_MB * 1024 * 1024
    tmp_path = Path("/tmp") / f"world_{uuid.uuid4().hex}.zip"
    size = 0
    try:
        with open(tmp_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail=f"Archive exceeds the {settings.SERVER_JAR_MAX_MB} MB upload limit.")
                out.write(chunk)
        world_name = server_manager.import_world_zip(server_id, tmp_path, name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        tmp_path.unlink(missing_ok=True)
    audit(user.id, "world_imported", target=server_id, detail=world_name)
    return {"success": True, "world": world_name}


@router.post("/api/servers/{server_id}/worlds/{world_name}/link")


async def world_download_link(server_id: str, world_name: str, user=Depends(require_user)):
    """Create a secure expiring download link for a world export."""
    require_server_access(user, server_id, "viewer")
    path = server_manager.export_world_zip(server_id, world_name)
    if not path:
        raise HTTPException(status_code=404, detail="World not found")
    token = download_tokens.create_token(user.id, "world", str(path), server_id=server_id)
    return {"success": True, "url": f"/api/dl/{token}", "expires_in_hours": settings.DOWNLOAD_TOKEN_TTL_HOURS}


@router.post("/api/servers/{server_id}/worlds/{world_name}/activate")


async def activate_world(server_id: str, world_name: str, user=Depends(require_user)):
    require_server_access(user, server_id, "admin")
    try:
        previous = server_manager.set_active_world(server_id, world_name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    audit(user.id, "world_activated", target=server_id, detail=f"{previous} -> {world_name}")
    return {"success": True, "previous": previous, "active": world_name}


@router.delete("/api/servers/{server_id}/worlds/{world_name}")


async def delete_world(server_id: str, world_name: str, user=Depends(require_user)):
    require_server_access(user, server_id, "owner")
    try:
        deleted = server_manager.delete_world(server_id, world_name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="World not found")
    audit(user.id, "world_deleted", target=server_id, detail=world_name)
    return {"success": True}

# ------------------------------------------------------------------ backups
@router.get("/api/servers/{server_id}/backups")


async def list_backups(server_id: str, user=Depends(require_user)):
    require_server_access(user, server_id, "viewer")
    with get_db() as db:
        rows = (
            db.query(DBServerBackup)
            .filter(DBServerBackup.server_id == server_id)
            .order_by(DBServerBackup.created_at.desc())
            .all()
        )
        return [
            {"id": b.id, "filename": b.filename, "size_bytes": b.size_bytes, "kind": b.kind,
             "created_at": b.created_at.isoformat() if b.created_at else None}
            for b in rows
        ]

@router.post("/api/servers/{server_id}/backups")


async def create_backup(server_id: str, user=Depends(require_user)):
    require_server_access(user, server_id, "moderator")
    try:
        row = await server_manager.create_backup(server_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    audit(user.id, "backup_created", target=server_id, detail=row.filename)
    return {"success": True, "backup": {"id": row.id, "filename": row.filename, "size_bytes": row.size_bytes}}

@router.post("/api/servers/{server_id}/backups/{backup_id}/restore")


async def restore_backup(server_id: str, backup_id: int, user=Depends(require_user)):
    require_server_access(user, server_id, "owner")
    try:
        await server_manager.restore_backup(server_id, backup_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    audit(user.id, "backup_restored", target=server_id, detail=str(backup_id))
    return {"success": True, "message": "Backup restored"}

@router.get("/api/servers/{server_id}/backups/{backup_id}/download")


async def download_backup(server_id: str, backup_id: int, user=Depends(require_user)):
    """Direct authorized download (session-authenticated)."""
    require_server_access(user, server_id, "viewer")
    path = server_manager.get_backup_path(server_id, backup_id)
    if not path:
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(path=str(path), filename=path.name, media_type="application/zip")


@router.post("/api/servers/{server_id}/backups/{backup_id}/link")


async def backup_download_link(server_id: str, backup_id: int, user=Depends(require_user)):
    """Create a secure expiring download link for a backup."""
    require_server_access(user, server_id, "viewer")
    path = server_manager.get_backup_path(server_id, backup_id)
    if not path:
        raise HTTPException(status_code=404, detail="Backup not found")
    token = download_tokens.create_token(user.id, "backup", str(path), server_id=server_id)
    return {"success": True, "url": f"/api/dl/{token}", "expires_in_hours": settings.DOWNLOAD_TOKEN_TTL_HOURS}

@router.delete("/api/servers/{server_id}/backups/{backup_id}")


async def delete_backup(server_id: str, backup_id: int, user=Depends(require_user)):
    require_server_access(user, server_id, "owner")
    deleted = await server_manager.delete_backup(server_id, backup_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Backup not found")
    return {"success": True}

# -------------------------------------------------------------- public links
@router.get("/api/dl/{token}")


async def public_download(token: str):
    """Token-based download endpoint. No session required; the token itself
    carries authorization, expiry and download limits."""
    path = download_tokens.resolve_token(token)
    if not path:
        raise HTTPException(status_code=404, detail="Link is invalid, expired or revoked")
    return FileResponse(path=str(path), filename=path.name)


@router.get("/api/links")


async def list_links(user=Depends(require_user)):
    """List download links created by the current user."""
    return download_tokens.list_tokens(user.id)


@router.delete("/api/links/{token}")


async def revoke_link(token: str, user=Depends(require_user)):
    try:
        revoked = download_tokens.revoke_token(token, user.id)
    except SecurityError:
        raise HTTPException(status_code=403, detail="Only the link owner can revoke this token")
    if not revoked:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"success": True}

# --------------------------------------------------------------- networking
@router.get("/api/servers/{server_id}/network")


async def server_network(server_id: str, user=Depends(require_user)):
    """Run real connectivity diagnostics and report connection addresses."""
    require_server_access(user, server_id, "viewer")
    report = diagnose_server(server_id)
    if "error" in report:
        raise HTTPException(status_code=404, detail=report["error"])
    return report

# ---------------------------------------------------------------- schedules
@router.get("/api/servers/{server_id}/schedules")


async def list_schedules(server_id: str, user=Depends(require_user)):
    require_server_access(user, server_id, "viewer")
    with get_db() as db:
        rows = (
            db.query(DBSchedule)
            .filter(DBSchedule.server_id == server_id)
            .order_by(DBSchedule.created_at.desc())
            .all()
        )
        return [_serialize_schedule(s) for s in rows]


def _serialize_schedule(s: DBSchedule) -> dict:
    return {
        "id": s.id,
        "server_id": s.server_id,
        "name": s.name,
        "action": s.action,
        "payload": s.payload,
        "interval_minutes": s.interval_minutes,
        "daily_time": s.daily_time,
        "enabled": s.enabled,
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


@router.post("/api/servers/{server_id}/schedules")


async def create_schedule(server_id: str, req: ScheduleCreateRequest, user=Depends(require_user)):
    require_server_access(user, server_id, "admin")
    if req.action not in ("backup", "restart", "stop", "start", "save", "command"):
        raise HTTPException(status_code=400, detail="Unsupported schedule action.")
    if not req.interval_minutes and not req.daily_time:
        raise HTTPException(status_code=400, detail="Provide interval_minutes or daily_time (HH:MM).")
    if req.interval_minutes and (req.interval_minutes < 5 or req.interval_minutes > 60 * 24 * 30):
        raise HTTPException(status_code=400, detail="interval_minutes must be between 5 and 43200.")
    if req.daily_time:
        try:
            hh, mm = (int(x) for x in req.daily_time.split(":"))
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                raise ValueError
        except ValueError:
            raise HTTPException(status_code=400, detail="daily_time must be a valid HH:MM time.")
    with get_db() as db:
        if not db.query(DBServer).filter(DBServer.id == server_id).first():
            raise HTTPException(status_code=404, detail="Server not found")
        count = db.query(DBSchedule).filter(DBSchedule.server_id == server_id).count()
        if count >= 20:
            raise HTTPException(status_code=400, detail="Schedule limit reached (20 per server).")
        schedule = DBSchedule(
            server_id=server_id,
            name=req.name.strip()[:128] or "Schedule",
            action=req.action,
            payload=(req.payload or "")[:256] or None,
            interval_minutes=req.interval_minutes,
            daily_time=req.daily_time,
            enabled=req.enabled,
            created_by=user.id,
        )
        db.add(schedule)
        db.flush()
        db.refresh(schedule)
        schedule.next_run_at = compute_next_run(schedule, utcnow())
        data = _serialize_schedule(schedule)
    audit(user.id, "schedule_created", target=server_id, detail=f"{req.action} {req.name}")
    return {"success": True, "schedule": data}


@router.patch("/api/schedules/{schedule_id}")


async def update_schedule(schedule_id: int, req: ScheduleUpdateRequest, user=Depends(require_user)):
    with get_db() as db:
        schedule = db.query(DBSchedule).filter(DBSchedule.id == schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        require_server_access(user, schedule.server_id, "admin")
        if req.enabled is not None:
            schedule.enabled = req.enabled
        if req.name is not None and req.name.strip():
            schedule.name = req.name.strip()[:128]
        schedule.next_run_at = compute_next_run(schedule, utcnow())
        data = _serialize_schedule(schedule)
    audit(user.id, "schedule_updated", target=str(schedule_id))
    return {"success": True, "schedule": data}


@router.delete("/api/schedules/{schedule_id}")


async def delete_schedule(schedule_id: int, user=Depends(require_user)):
    with get_db() as db:
        schedule = db.query(DBSchedule).filter(DBSchedule.id == schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        require_server_access(user, schedule.server_id, "owner")
        db.query(DBScheduleRun).filter(DBScheduleRun.schedule_id == schedule_id).delete()
        db.delete(schedule)
    audit(user.id, "schedule_deleted", target=str(schedule_id))
    return {"success": True}


@router.get("/api/schedules/{schedule_id}/runs")


async def schedule_runs(schedule_id: int, user=Depends(require_user)):
    with get_db() as db:
        schedule = db.query(DBSchedule).filter(DBSchedule.id == schedule_id).first()
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        require_server_access(user, schedule.server_id, "viewer")
        runs = (
            db.query(DBScheduleRun)
            .filter(DBScheduleRun.schedule_id == schedule_id)
            .order_by(DBScheduleRun.started_at.desc())
            .limit(25)
            .all()
        )
        return [
            {
                "id": r.id,
                "status": r.status,
                "detail": r.detail,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in runs
        ]

# ------------------------------------------------------------------- shares
@router.get("/api/servers/{server_id}/shares")


async def list_shares(server_id: str, user=Depends(require_user)):
    require_server_access(user, server_id, "admin")
    with get_db() as db:
        shares = db.query(DBServerShare).filter(DBServerShare.server_id == server_id).all()
        return [
            {"id": s.id, "user_id": s.user_id, "role": s.role,
             "created_at": s.created_at.isoformat() if s.created_at else None}
            for s in shares
        ]


@router.post("/api/servers/{server_id}/shares")


async def create_share(server_id: str, req: ShareRequest, user=Depends(require_user)):
    require_server_access(user, server_id, "owner")
    if req.role not in ("viewer", "moderator", "admin"):
        raise HTTPException(status_code=400, detail="Role must be viewer, moderator or admin.")
    with get_db() as db:
        if not db.query(DBServer).filter(DBServer.id == server_id).first():
            raise HTTPException(status_code=404, detail="Server not found")
        target = db.query(DBUser).filter(DBUser.username == req.username.strip().lower()).first()
        if not target:
            raise HTTPException(status_code=404, detail="No account with that username exists")
        if target.id == user.id:
            raise HTTPException(status_code=400, detail="You already own this server")
        existing = db.query(DBServerShare).filter(
            DBServerShare.server_id == server_id, DBServerShare.user_id == target.id
        ).first()
        if existing:
            raise HTTPException(status_code=409, detail="That user already has access")
        share = DBServerShare(server_id=server_id, user_id=target.id, role=req.role, granted_by=user.id)
        db.add(share)
        db.flush()
        data = {"id": share.id, "user_id": target.id, "role": req.role}
    audit(user.id, "server_shared", target=server_id, detail=f"{req.username}:{req.role}")
    return {"success": True, "share": data}


@router.delete("/api/servers/{server_id}/shares/{share_id}")


async def delete_share(server_id: str, share_id: int, user=Depends(require_user)):
    require_server_access(user, server_id, "owner")
    with get_db() as db:
        share = db.query(DBServerShare).filter(
            DBServerShare.id == share_id, DBServerShare.server_id == server_id
        ).first()
        if not share:
            raise HTTPException(status_code=404, detail="Share not found")
        db.delete(share)
    audit(user.id, "share_revoked", target=server_id, detail=str(share_id))
    return {"success": True}

# -------------------------------------------------------------------- files
@router.get("/api/servers/{server_id}/files")


async def list_files(server_id: str, path: str = "", user=Depends(require_user)):
    require_server_access(user, server_id, "viewer")
    try:
        return server_manager.list_files(server_id, path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/servers/{server_id}/files/download")


async def download_file(server_id: str, path: str, user=Depends(require_user)):
    require_server_access(user, server_id, "viewer")
    target = server_manager.resolve_file(server_id, path)
    if not target:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=str(target), filename=target.name)


class FileWriteRequest(BaseModel):
    content: str

TEXT_SUFFIXES = (".txt", ".json", ".properties", ".yml", ".yaml", ".toml", ".mcmeta", ".cfg", ".conf", ".csv", ".log", ".md", ".js", ".py")
MAX_TEXT_FILE_BYTES = 512 * 1024

@router.get("/api/servers/{server_id}/files/read")


async def read_text_file(server_id: str, path: str, user=Depends(require_user)):
    """Read a safe text-based file for the built-in editor."""
    require_server_access(user, server_id, "viewer")
    target = server_manager.resolve_file(server_id, path)
    if not target:
        raise HTTPException(status_code=404, detail="File not found")
    if target.suffix.lower() not in TEXT_SUFFIXES or target.stat().st_size > MAX_TEXT_FILE_BYTES:
        raise HTTPException(status_code=415, detail="Only text files up to 512 KB can be opened in the editor.")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="File is not valid UTF-8 text.")
    return {"path": path, "content": content}


@router.put("/api/servers/{server_id}/files/write")


async def write_text_file(server_id: str, path: str, req: FileWriteRequest, user=Depends(require_user)):
    """Write a safe text-based file (creates a .bak backup of the previous version)."""
    require_server_access(user, server_id, "admin")
    if len(req.content.encode("utf-8")) > MAX_TEXT_FILE_BYTES:
        raise HTTPException(status_code=413, detail="File content exceeds the 512 KB editor limit.")
    base = server_manager.get_server_dir(server_id)
    from core.security import validate_safe_path
    target = validate_safe_path(base, base / path)
    if target.suffix.lower() not in TEXT_SUFFIXES:
        raise HTTPException(status_code=415, detail="Only text files can be written through the editor.")
    if target.exists():
        backup = target.with_suffix(target.suffix + ".bak")
        backup.write_bytes(target.read_bytes())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(req.content, encoding="utf-8")
    audit(user.id, "file_written", target=server_id, detail=path)
    return {"success": True, "path": path}


class MkdirRequest(BaseModel):
    path: str

@router.post("/api/servers/{server_id}/files/mkdir")


async def make_directory(server_id: str, req: MkdirRequest, user=Depends(require_user)):
    require_server_access(user, server_id, "admin")
    base = server_manager.get_server_dir(server_id)
    from core.security import validate_safe_path
    target = validate_safe_path(base, base / req.path)
    if target.exists():
        raise HTTPException(status_code=409, detail="A file or folder with that name already exists.")
    target.mkdir(parents=True, exist_ok=False)
    audit(user.id, "directory_created", target=server_id, detail=req.path)
    return {"success": True}


@router.delete("/api/servers/{server_id}/files")


async def delete_file(server_id: str, path: str, user=Depends(require_user)):
    """Delete a file or directory inside the server root."""
    require_server_access(user, server_id, "admin")
    if not path or path in (".", "/"):
        raise HTTPException(status_code=400, detail="Refusing to delete the server root.")
    base = server_manager.get_server_dir(server_id)
    from core.security import validate_safe_path
    target = validate_safe_path(base, base / path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)
    else:
        target.unlink(missing_ok=True)
    audit(user.id, "file_deleted", target=server_id, detail=path)
    return {"success": True}

# ------------------------------------------------------------------- upload
@router.post("/api/servers/{server_id}/upload")


async def upload_server_software(server_id: str, file: UploadFile = File(...), user=Depends(require_user)):
    """Upload real server software: server.jar (Java) or the BDS zip (Bedrock)."""
    require_server_access(user, server_id, "admin")
    with get_db() as db:
        row = db.query(DBServer).filter(DBServer.id == server_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Server not found")
        software = row.software
        is_bedrock = software == "bedrock"

    if is_bedrock:
        if not file.filename or not file.filename.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="Bedrock servers need the official BDS .zip archive.")
    else:
        if not file.filename or not file.filename.lower().endswith(".jar"):
            raise HTTPException(status_code=400, detail="Only .jar files are accepted as Java server software.")

    max_bytes = settings.SERVER_JAR_MAX_MB * 1024 * 1024
    suffix = ".zip" if is_bedrock else ".jar"
    tmp_path = Path("/tmp") / f"upload_{uuid.uuid4().hex}{suffix}"
    size = 0
    try:
        with open(tmp_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail=f"File exceeds the {settings.SERVER_JAR_MAX_MB} MB upload limit.")
                out.write(chunk)
        if is_bedrock:
            server_manager.save_uploaded_bedrock_zip(server_id, tmp_path)
            message = "Bedrock Dedicated Server installed; real BDS runtime enabled"
        else:
            server_manager.save_uploaded_jar(server_id, tmp_path)
            message = "server.jar uploaded; real Java runtime enabled"
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        tmp_path.unlink(missing_ok=True)
    audit(user.id, "server_software_uploaded", target=server_id, detail=file.filename)
    return {"success": True, "size_bytes": size, "message": message}

@router.post("/api/servers/{server_id}/files/upload")


async def upload_server_file(server_id: str, file: UploadFile = File(...), path: str = "",
                             user=Depends(require_user)):
    """Upload any file (mod .jar, plugin .jar, behavior pack, config…) into a
    folder inside the server directory. The target folder is created when missing."""
    require_server_access(user, server_id, "admin")
    if not file.filename or not file.filename.strip():
        raise HTTPException(status_code=400, detail="No file name supplied.")
    base = server_manager.get_server_dir(server_id)
    from core.security import validate_safe_path
    try:
        target_dir = validate_safe_path(base, base / path) if path else base
        target = validate_safe_path(base, target_dir / Path(file.filename).name)
    except SecurityError:
        raise HTTPException(status_code=400, detail="Invalid target folder.")
    if target.is_dir():
        raise HTTPException(status_code=409, detail="A folder with that name already exists.")
    target_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = settings.SERVER_JAR_MAX_MB * 1024 * 1024
    size = 0
    try:
        with open(target, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds the {settings.SERVER_JAR_MAX_MB} MB upload limit.")
                out.write(chunk)
    finally:
        if size == 0 and target.is_file():
            target.unlink(missing_ok=True)
    audit(user.id, "file_uploaded", target=server_id, detail=f"{path}/{file.filename}" if path else file.filename)
    return {"success": True, "filename": target.name, "path": path, "size_bytes": size}

# ------------------------------------------------------------------ UI page
@router.get("/servers/{server_id}", response_class=HTMLResponse)
async def server_page(request: Request, server_id: str):
    """Render the server control page."""
    user = session_user_from_request(request)
    if settings.AUTH_REQUIRED and user is None:
        return templates.TemplateResponse(request=request, name="login.html", context={
            "next": f"/servers/{server_id}", "error": "Please sign in to continue."}, status_code=401)
    from core.auth import ServiceAccount
    if user is None:
        user = ServiceAccount()  # type: ignore[assignment]
    role = require_server_access(user, server_id, "viewer")
    with get_db() as db:
        row = db.query(DBServer).filter(DBServer.id == server_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Server not found")
        context = server_manager.serialize(row)
        share_count = db.query(DBServerShare).filter(DBServerShare.server_id == server_id).count()
    context["role"] = role
    context["max_backups"] = settings.MAX_BACKUPS_PER_SERVER
    context["share_count"] = share_count
    context["user"] = {"id": user.id, "username": user.username, "role": user.role}
    return templates.TemplateResponse(request=request, name="server.html", context={"server": context})
