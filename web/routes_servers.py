"""FastAPI routes for Cyber Host: hosted Minecraft server management API and UI."""
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from config import settings, SERVER_SOFTWARE
from servers.manager import server_manager
from servers.runtime import find_java_executable
from storage.database import get_db
from storage.models import Server as DBServer, ServerBackup as DBServerBackup

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

class CreateServerRequest(BaseModel):
    name: str
    software: str = "paper"
    mc_version: str = "1.21.4"
    motd: Optional[str] = None
    level_seed: Optional[str] = None
    eula_accepted: bool = False

class CommandRequest(BaseModel):
    command: str

class PlayerRequest(BaseModel):
    kind: str  # ops, whitelist, bans
    action: str  # add, remove
    player: str

class PropertiesUpdateRequest(BaseModel):
    properties: dict

# ------------------------------------------------------------------ catalog
@router.get("/api/host/catalog")
async def host_catalog():
    """Software catalog + host capabilities for the create-server UI."""
    return {
        "software": SERVER_SOFTWARE,
        "max_servers_per_owner": settings.MAX_SERVERS_PER_OWNER,
        "max_concurrent_servers": settings.MAX_CONCURRENT_SERVERS,
        "java_available": find_java_executable() is not None
    }

# --------------------------------------------------------------------- CRUD
@router.get("/api/servers")
async def list_servers():
    """List all hosted servers with live status."""
    with get_db() as db:
        rows = db.query(DBServer).order_by(DBServer.created_at.desc()).all()
        return [server_manager.serialize(r) for r in rows]

@router.post("/api/servers")
async def create_server(req: CreateServerRequest):
    """Create a new hosted Minecraft server."""
    try:
        row = server_manager.create_server(
            owner_id="web_admin",
            name=req.name,
            software=req.software,
            mc_version=req.mc_version,
            motd=req.motd or "A Cyber Host server",
            level_seed=req.level_seed or "",
            eula_accepted=req.eula_accepted
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return server_manager.serialize(row)

@router.get("/api/servers/{server_id}")
async def get_server(server_id: str):
    """Full server state: status, console tail, players, backups, files."""
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
async def delete_server(server_id: str):
    """Permanently delete a server and its files."""
    deleted = await server_manager.delete_server(server_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Server not found")
    return {"success": True, "message": f"Server {server_id} deleted"}

# ------------------------------------------------------------ power control
@router.post("/api/servers/{server_id}/start")
async def start_server(server_id: str):
    """Queue a start request (Aternos-style queue)."""
    try:
        return await server_manager.request_start(server_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

@router.post("/api/servers/{server_id}/stop")
async def stop_server(server_id: str):
    try:
        await server_manager.request_stop(server_id)
        return {"success": True, "message": "Stop requested"}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

@router.post("/api/servers/{server_id}/restart")
async def restart_server(server_id: str):
    try:
        await server_manager.restart_server(server_id)
        return {"success": True, "message": "Restart queued"}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

# ------------------------------------------------------------------ console
@router.get("/api/servers/{server_id}/console")
async def server_console(server_id: str, tail: int = 200):
    with get_db() as db:
        if not db.query(DBServer).filter(DBServer.id == server_id).first():
            raise HTTPException(status_code=404, detail="Server not found")
    return {"server_id": server_id, "lines": server_manager.get_console(server_id, tail=tail)}

@router.post("/api/servers/{server_id}/command")
async def server_command(server_id: str, req: CommandRequest):
    try:
        output = await server_manager.send_command(server_id, req.command)
        return {"success": True, "output": output}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

# ------------------------------------------------------------------ players
@router.get("/api/servers/{server_id}/players")
async def list_players(server_id: str, kind: str = "ops"):
    try:
        return {"kind": kind, "players": await server_manager.list_players(server_id, kind)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/servers/{server_id}/players")
async def manage_player(server_id: str, req: PlayerRequest):
    try:
        message = await server_manager.manage_player(server_id, req.kind, req.action, req.player)
        players = await server_manager.list_players(server_id, req.kind)
        return {"success": True, "message": message, "players": players}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# --------------------------------------------------------------- properties
@router.get("/api/servers/{server_id}/properties")
async def get_properties(server_id: str):
    return await server_manager.get_properties(server_id)

@router.put("/api/servers/{server_id}/properties")
async def set_properties(server_id: str, req: PropertiesUpdateRequest):
    try:
        applied = await server_manager.set_properties(server_id, req.properties)
        return {"success": True, "applied": applied}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# ------------------------------------------------------------------ backups
@router.get("/api/servers/{server_id}/backups")
async def list_backups(server_id: str):
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
async def create_backup(server_id: str):
    try:
        row = await server_manager.create_backup(server_id)
        return {"success": True, "backup": {"id": row.id, "filename": row.filename, "size_bytes": row.size_bytes}}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/api/servers/{server_id}/backups/{backup_id}/restore")
async def restore_backup(server_id: str, backup_id: int):
    try:
        await server_manager.restore_backup(server_id, backup_id)
        return {"success": True, "message": "Backup restored"}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

@router.get("/api/servers/{server_id}/backups/{backup_id}/download")
async def download_backup(server_id: str, backup_id: int):
    path = server_manager.get_backup_path(server_id, backup_id)
    if not path:
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(path=str(path), filename=path.name, media_type="application/zip")

@router.delete("/api/servers/{server_id}/backups/{backup_id}")
async def delete_backup(server_id: str, backup_id: int):
    deleted = await server_manager.delete_backup(server_id, backup_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Backup not found")
    return {"success": True}

# -------------------------------------------------------------------- files
@router.get("/api/servers/{server_id}/files")
async def list_files(server_id: str, path: str = ""):
    try:
        return server_manager.list_files(server_id, path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/api/servers/{server_id}/files/download")
async def download_file(server_id: str, path: str):
    target = server_manager.resolve_file(server_id, path)
    if not target:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=str(target), filename=target.name)

# ------------------------------------------------------------------- upload
@router.post("/api/servers/{server_id}/upload")
async def upload_server_jar(server_id: str, file: UploadFile = File(...)):
    """Upload a real server.jar to enable the real Java runtime."""
    if not file.filename or not file.filename.lower().endswith(".jar"):
        raise HTTPException(status_code=400, detail="Only .jar files are accepted as server software.")
    max_bytes = settings.SERVER_JAR_MAX_MB * 1024 * 1024
    tmp_path = Path("/tmp") / f"upload_{uuid.uuid4().hex}.jar"
    size = 0
    try:
        with open(tmp_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status_code=413, detail=f"File exceeds the {max_bytes // (1024 * 1024)} MB upload limit.")
                out.write(chunk)
        server_manager.save_uploaded_jar(server_id, tmp_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    return {"success": True, "size_bytes": size, "message": "server.jar uploaded; real Java runtime enabled"}

# ------------------------------------------------------------------ UI page
@router.get("/servers/{server_id}", response_class=HTMLResponse)
async def server_page(request: Request, server_id: str):
    """Render the Aternos-style server control page."""
    with get_db() as db:
        row = db.query(DBServer).filter(DBServer.id == server_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Server not found")
        context = server_manager.serialize(row)
    context["max_backups"] = settings.MAX_BACKUPS_PER_SERVER
    return templates.TemplateResponse(request=request, name="server.html", context={"server": context})
