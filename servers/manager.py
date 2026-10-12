"""ServerManager: creation, start queue, console, players, properties, backups and files
for hosted Minecraft servers (Aternos-style control plane)."""
import asyncio
import os
import random
import shutil
import socket
import uuid
import zipfile
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from config import settings, SERVER_SOFTWARE
from core.security import validate_safe_path, safe_extract_zip
from storage.database import get_db
from storage.models import Server as DBServer, ServerBackup as DBServerBackup
from servers.runtime import (
    EmbeddedRuntime,
    JavaProcessRuntime,
    BedrockProcessRuntime,
    RuntimeContext,
    find_java_executable,
    read_state_list,
    write_state_list
)
from logger import get_logger

logger = get_logger("servers.manager")

CONSOLE_BUFFER_LINES = 500

class ServerStatus:
    OFFLINE = "offline"
    QUEUED = "queued"
    PREPARING = "preparing"
    STARTING = "starting"
    ONLINE = "online"
    STOPPING = "stopping"
    ERROR = "error"

def _int_in(lo: int, hi: int):
    """Validator factory accepting ints or numeric strings (form inputs arrive as strings)."""
    def _validate(v):
        try:
            n = int(v)
        except (TypeError, ValueError):
            return None
        return str(n) if lo <= n <= hi else None
    return _validate

# Properties that may be edited through the API, mapped to validator callables.
EDITABLE_PROPERTIES: Dict[str, Any] = {
    "motd": lambda v: str(v)[:128],
    "gamemode": lambda v: v if v in ("survival", "creative", "adventure", "spectator") else None,
    "difficulty": lambda v: v if v in ("peaceful", "easy", "normal", "hard") else None,
    "max-players": _int_in(1, 200),
    "pvp": lambda v: "true" if bool(v) and v != "false" else "false",
    "white-list": lambda v: "true" if bool(v) and v != "false" else "false",
    "level-seed": lambda v: str(v)[:64],
    "view-distance": _int_in(3, 32),
    "online-mode": lambda v: "true" if bool(v) and v != "false" else "false",
    "allow-nether": lambda v: "true" if bool(v) and v != "false" else "false",
    "allow-flight": lambda v: "true" if bool(v) and v != "false" else "false",
    "spawn-monsters": lambda v: "true" if bool(v) and v != "false" else "false",
}

class HostedServerState:
    """In-memory runtime state attached to a persistent server row."""
    
    def __init__(self, server_id: str):
        self.server_id = server_id
        self.console: deque = deque(maxlen=CONSOLE_BUFFER_LINES)
        self.runtime = None
        self.started_at: Optional[datetime] = None
        self.last_activity: Optional[datetime] = None
        self.queue_position: Optional[int] = None
        self.cancel_requested = False
        self.config_dirty = False

class ServerManager:
    """Manages the full lifecycle of hosted Minecraft servers."""
    
    def __init__(self):
        self.base_dir = (settings.DATA_DIR / "servers").resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._states: Dict[str, HostedServerState] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._workers: List[asyncio.Task] = []
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False

    # ------------------------------------------------------------------ paths
    def get_server_dir(self, server_id: str) -> Path:
        sdir = self.base_dir / server_id
        validate_safe_path(self.base_dir, sdir)
        sdir.mkdir(parents=True, exist_ok=True)
        return sdir

    def get_world_dir(self, server_id: str, world_name: str = "world") -> Path:
        wdir = self.get_server_dir(server_id) / world_name
        wdir.mkdir(parents=True, exist_ok=True)
        return wdir

    def get_backups_dir(self, server_id: str) -> Path:
        bdir = self.get_server_dir(server_id) / "backups"
        bdir.mkdir(parents=True, exist_ok=True)
        return bdir

    # ------------------------------------------------------------ lifecycle
    async def startup(self) -> None:
        """Reset stale statuses from a previous host run and start queue workers."""
        with get_db() as db:
            stale = db.query(DBServer).filter(DBServer.status != ServerStatus.OFFLINE).all()
            for s in stale:
                s.status = ServerStatus.OFFLINE
                s.address = None
                s.port = None
                s.status_detail = "Host restarted; server was reset to offline"
        # Recreate the queue so it binds to the current event loop (a fresh
        # loop must never reuse a queue bound to a previous one).
        self._queue = asyncio.Queue()
        self._running = True
        for i in range(max(1, settings.MAX_CONCURRENT_SERVERS)):
            self._workers.append(asyncio.create_task(self._worker_loop(i)))
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Cyber Host manager online with {settings.MAX_CONCURRENT_SERVERS} start-slot(s).")

    async def shutdown(self) -> None:
        """Stop workers and all running servers on host shutdown."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        for task in self._workers:
            task.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        online = [sid for sid, st in self._states.items() if st.runtime is not None]
        if online:
            await asyncio.gather(*(self.request_stop(sid, reason="host shutdown") for sid in online), return_exceptions=True)
        logger.info("Cyber Host manager stopped.")

    # -------------------------------------------------------------- console
    async def _console_log(self, server_id: str, line: str) -> None:
        state = self._states.setdefault(server_id, HostedServerState(server_id))
        state.console.append(line)
        logger.info(f"[server {server_id}] {line}")
        try:
            log_dir = self.get_server_dir(server_id) / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "latest.log", "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            logger.warning(f"Could not write console log file for {server_id}: {e}")

    def get_console(self, server_id: str, tail: int = 200) -> List[str]:
        state = self._states.get(server_id)
        if not state:
            return []
        lines = list(state.console)
        return lines[-max(1, tail):]

    # ------------------------------------------------------------------ CRUD
    def _db_get(self, db, server_id: str) -> Optional[DBServer]:
        return db.query(DBServer).filter(DBServer.id == server_id).first()

    def create_server(
        self,
        owner_id: str,
        name: str,
        software: str,
        mc_version: str,
        motd: str = "A Cyber Host server",
        level_seed: str = "",
        eula_accepted: bool = False,
        description: str = "",
        gamemode: str = "survival",
        difficulty: str = "normal",
        max_players: int = 20,
        pvp: bool = True,
        whitelist_enabled: bool = False,
    ) -> DBServer:
        """Create a persistent server record and its on-disk skeleton."""
        if software not in SERVER_SOFTWARE:
            raise ValueError(f"Unsupported software '{software}'. Choose from: {', '.join(SERVER_SOFTWARE)}")
        if mc_version not in SERVER_SOFTWARE[software]["versions"]:
            raise ValueError(f"{software} does not support version {mc_version}")
        if not eula_accepted:
            raise ValueError("You must accept the Minecraft EULA to create a server.")
        if not name or not name.strip():
            raise ValueError("Server name is required.")
        if gamemode not in ("survival", "creative", "adventure"):
            raise ValueError("Gamemode must be survival, creative or adventure.")
        if difficulty not in ("peaceful", "easy", "normal", "hard"):
            raise ValueError("Difficulty must be peaceful, easy, normal or hard.")
        if not isinstance(max_players, int) or not (1 <= max_players <= 200):
            raise ValueError("Max players must be between 1 and 200.")
        
        with get_db() as db:
            owned = db.query(DBServer).filter(DBServer.owner_id == owner_id).count()
            if owned >= settings.MAX_SERVERS_PER_OWNER:
                raise ValueError(f"Server limit reached ({settings.MAX_SERVERS_PER_OWNER} per owner).")
            server_id = f"srv_{uuid.uuid4().hex[:10]}"
            row = DBServer(
                id=server_id,
                owner_id=owner_id,
                name=name.strip()[:128],
                description=(description or "").strip()[:256] or None,
                software=software,
                mc_version=mc_version,
                motd=(motd or "A Cyber Host server")[:128],
                level_seed=(level_seed or "").strip()[:64] or None,
                eula_accepted=True,
                status=ServerStatus.OFFLINE,
                status_detail="Server is offline",
                ram_mb=settings.SERVER_RAM_MB,
                gamemode=gamemode,
                difficulty=difficulty,
                max_players=max_players,
                pvp=bool(pvp),
                whitelist_enabled=bool(whitelist_enabled),
            )
            db.add(row)
        
        sdir = self.get_server_dir(server_id)
        properties = self._build_properties(row)
        self._write_properties(sdir, properties)
        (sdir / "eula.txt").write_text(
            "#Accepted via Cyber Host\n" + datetime.utcnow().strftime("#%Y-%m-%d %H:%M:%S") + "\neula=true\n",
            encoding="utf-8"
        )
        self.get_world_dir(server_id, row.world_name)
        logger.info(f"Created server {server_id} ({software} {mc_version}) for {owner_id}")
        return row

    async def delete_server(self, server_id: str) -> bool:
        """Stop (if needed) and permanently remove a server and its files."""
        with get_db() as db:
            row = self._db_get(db, server_id)
            if not row:
                return False
            was_online = row.status == ServerStatus.ONLINE
        if was_online:
            await self.request_stop(server_id, reason="delete")
        with get_db() as db:
            row = self._db_get(db, server_id)
            if row:
                db.delete(row)
        sdir = self.base_dir / server_id
        if sdir.exists():
            shutil.rmtree(sdir, ignore_errors=True)
        self._states.pop(server_id, None)
        logger.info(f"Deleted server {server_id}")
        return True

    # ------------------------------------------------------------ start flow
    def _public_host(self) -> str:
        if settings.SERVER_PUBLIC_HOST:
            return settings.SERVER_PUBLIC_HOST
        if settings.PUBLIC_BASE_URL:
            return settings.PUBLIC_BASE_URL.split("://")[-1].split("/")[0].split(":")[0]
        return socket.gethostname() or "localhost"

    def _allocate_port(self) -> int:
        used = {st.port for sid, st in self._states.items() if st.runtime is not None}
        with get_db() as db:
            used.update(r[0] for r in db.query(DBServer.port).filter(DBServer.port.isnot(None)).all() if r[0])
        candidates = list(range(settings.SERVER_PORT_MIN, settings.SERVER_PORT_MAX + 1))
        random.shuffle(candidates)
        for port in candidates:
            if port in used:
                continue
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    sock.bind(("0.0.0.0", port))
                except OSError:
                    continue
            return port
        raise RuntimeError("No free ports available in the configured port range.")

    def _build_properties(self, row: DBServer) -> Dict[str, str]:
        return {
            "server-name": row.name,
            "level-name": row.world_name,
            "level-seed": row.level_seed or "",
            "gamemode": row.gamemode,
            "difficulty": row.difficulty,
            "max-players": str(row.max_players),
            "motd": row.motd,
            "pvp": "true" if row.pvp else "false",
            "white-list": "true" if row.whitelist_enabled else "false",
            "online-mode": "true",
            "view-distance": "10",
            "allow-nether": "true",
            "allow-flight": "false",
            "spawn-monsters": "true",
            "server-port": ""
        }

    @staticmethod
    def _write_properties(sdir: Path, properties: Dict[str, str]) -> None:
        lines = ["#Minecraft server properties (Cyber Host)", "#%s" % datetime.utcnow().strftime("%a %b %d %H:%M:%S %Z %Y")]
        for key, value in properties.items():
            lines.append(f"{key}={value}")
        (sdir / "server.properties").write_text("\n".join(lines) + "\n", encoding="utf-8")

    async def request_start(self, server_id: str) -> Dict[str, Any]:
        """Queue a start request (Aternos-style queue) and return queue info."""
        state = self._states.setdefault(server_id, HostedServerState(server_id))
        with get_db() as db:
            row = self._db_get(db, server_id)
            if not row:
                raise ValueError("Server not found")
            if not row.eula_accepted:
                raise ValueError("The Minecraft EULA has not been accepted for this server.")
            if row.status != ServerStatus.OFFLINE and row.status != ServerStatus.ERROR:
                raise ValueError(f"Server is {row.status}; only offline servers can be started.")
            state.queue_position = self._queue.qsize() + 1
            row.status = ServerStatus.QUEUED
            row.status_detail = f"Position {state.queue_position} in the start queue"
        state.cancel_requested = False
        await self._queue.put(server_id)
        logger.info(f"Server {server_id} queued for start (position {state.queue_position})")
        return {"server_id": server_id, "queue_position": state.queue_position}

    async def _worker_loop(self, worker_id: int) -> None:
        logger.info(f"Start-queue worker #{worker_id} running.")
        while self._running:
            try:
                server_id = await self._queue.get()
                try:
                    await self._do_start(server_id)
                except Exception as e:
                    logger.error(f"Start worker #{worker_id} failed on {server_id}: {e}", exc_info=True)
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Start worker #{worker_id} loop error: {e}")
                await asyncio.sleep(0.5)  # yield so a persistent error cannot spin the loop

    async def _do_start(self, server_id: str) -> None:
        state = self._states.setdefault(server_id, HostedServerState(server_id))
        state.queue_position = None
        with get_db() as db:
            row = self._db_get(db, server_id)
            if not row:
                return
            if state.cancel_requested:
                row.status = ServerStatus.OFFLINE
                row.status_detail = "Start cancelled from the queue"
                await self._console_log(server_id, f"[cyber/INFO]: Start cancelled before boot for '{row.name}'")
                return
            row.status = ServerStatus.PREPARING
            row.status_detail = "Preparing world files..."
            software, mc_version = row.software, row.mc_version

        port = self._allocate_port()
        address = f"{self._public_host()}:{port}"
        with get_db() as db:
            row = self._db_get(db, server_id)
            if not row:
                return
            row.address = address
            row.port = port
            row.status = ServerStatus.STARTING
            row.status_detail = f"Starting {software} {mc_version}..."
            row.last_started = datetime.utcnow()
            ram_mb = row.ram_mb
            world_name = row.world_name
            properties = self._build_properties(row)
            properties["server-port"] = str(port)
        self._write_properties(self.get_server_dir(server_id), properties)

        jar_ready = (self.get_server_dir(server_id) / "server.jar").exists()
        java_available = find_java_executable() is not None
        ctx = RuntimeContext(
            server_id=server_id,
            name=properties.get("server-name", server_id),
            software=software,
            mc_version=mc_version,
            server_dir=self.get_server_dir(server_id),
            world_dir=self.get_world_dir(server_id, world_name),
            port=port,
            ram_mb=ram_mb,
            properties=properties
        )
        if software == "bedrock":
            if (self.get_server_dir(server_id) / "bedrock_server").exists() or \
               (self.get_server_dir(server_id) / "bedrock_server.exe").exists():
                runtime = BedrockProcessRuntime(ctx, lambda line: self._console_log(server_id, line))
                await self._console_log(server_id, "[cyber/INFO]: Runtime selected: real Bedrock Dedicated Server process")
            else:
                runtime = EmbeddedRuntime(ctx, lambda line: self._console_log(server_id, line))
                await self._console_log(
                    server_id,
                    "[cyber/INFO]: Runtime selected: embedded console runtime (upload the official Bedrock Dedicated Server zip for real hosting)."
                )
        elif jar_ready and java_available:
            runtime = JavaProcessRuntime(ctx, lambda line: self._console_log(server_id, line))
            await self._console_log(server_id, "[cyber/INFO]: Runtime selected: real Java process (uploaded server.jar)")
        else:
            runtime = EmbeddedRuntime(ctx, lambda line: self._console_log(server_id, line))
            if jar_ready:
                await self._console_log(server_id, "[cyber/WARN]: Java not found; using the embedded console runtime.")
            else:
                await self._console_log(server_id, "[cyber/INFO]: Runtime selected: embedded console runtime (upload server.jar for real hosting).")

        state.runtime = runtime
        try:
            await runtime.start()
            state.started_at = datetime.utcnow()
            state.last_activity = datetime.utcnow()
            with get_db() as db:
                row = self._db_get(db, server_id)
                if row:
                    row.status = ServerStatus.ONLINE
                    row.status_detail = "Server is online"
            await self._console_log(server_id, f"[cyber/INFO]: Server address: {address}")
        except Exception as e:
            state.runtime = None
            with get_db() as db:
                row = self._db_get(db, server_id)
                if row:
                    row.status = ServerStatus.ERROR
                    row.status_detail = f"Failed to start: {str(e)[:180]}"
            await self._console_log(server_id, f"[cyber/ERROR]: Start failed: {e}")
    async def request_stop(self, server_id: str, reason: str = "operator") -> None:
        """Stop a server (or cancel a queued start) and persist its state."""
        state = self._states.get(server_id)
        auto_backup = False
        with get_db() as db:
            row = self._db_get(db, server_id)
            if not row:
                raise ValueError("Server not found")
            if row.status == ServerStatus.OFFLINE:
                return
            if row.status == ServerStatus.QUEUED and state:
                state.cancel_requested = True
                state.queue_position = None
                row.status_detail = "Cancelling queued start..."
                return
            row.status = ServerStatus.STOPPING
            row.status_detail = f"Stopping server ({reason})..."
            auto_backup = bool(row.auto_backup)
        await self._console_log(server_id, f"[cyber/INFO]: Stop requested ({reason})")
        if state and state.runtime:
            try:
                await state.runtime.stop()
            except Exception as e:
                logger.warning(f"Runtime stop error for {server_id}: {e}")
            state.runtime = None
        if state and auto_backup and state.started_at:
            # Only back up servers that were actually online (skip failed/cancelled boots).
            try:
                await self._run_backup(server_id, kind="auto")
            except Exception as e:
                await self._console_log(server_id, f"[cyber/WARN]: Auto-backup failed: {e}")
        if state:
            state.started_at = None
            state.config_dirty = False
        with get_db() as db:
            row = self._db_get(db, server_id)
            if row:
                row.status = ServerStatus.OFFLINE
                row.status_detail = "Server is offline"
                row.address = None
                row.port = None
        await self._console_log(server_id, "[cyber/INFO]: Server stopped. World saved.")

    async def restart_server(self, server_id: str) -> None:
        await self.request_stop(server_id, reason="restart")
        await self.request_start(server_id)

    # -------------------------------------------------------------- commands
    async def send_command(self, server_id: str, command: str) -> List[str]:
        """Send a console command to a running server and return its output."""
        command = command.strip()
        if not command:
            return []
        state = self._states.get(server_id)
        if not state or not state.runtime:
            raise ValueError("Server is not online; commands require a running server.")
        await self._console_log(server_id, f"> {command}")
        state.last_activity = datetime.utcnow()
        try:
            return await state.runtime.send_command(command)
        finally:
            if command.lower() == "stop":
                await self.request_stop(server_id, reason="console /stop")

    # --------------------------------------------------------------- players
    async def list_players(self, server_id: str, kind: str) -> List[dict]:
        """Read a player state list: ops, whitelist, or bans."""
        sdir = self.get_server_dir(server_id)
        filename = {"ops": "ops.json", "whitelist": "whitelist.json", "bans": "banned-players.json"}.get(kind)
        if not filename:
            raise ValueError("Unknown player list kind")
        return read_state_list(sdir, filename)

    async def manage_player(self, server_id: str, kind: str, action: str, player: str) -> str:
        """Add/remove a player on ops, whitelist, or bans through console commands."""
        commands = {
            ("ops", "add"): "op {p}",
            ("ops", "remove"): "deop {p}",
            ("whitelist", "add"): "whitelist add {p}",
            ("whitelist", "remove"): "whitelist remove {p}",
            ("bans", "add"): "ban {p}",
            ("bans", "remove"): "pardon {p}"
        }
        cmd = commands.get((kind, action))
        if not cmd:
            raise ValueError("Unsupported player management action")
        player = player.strip()
        if not player or len(player) > 32:
            raise ValueError("Player name must be 1-32 characters")
        state = self._states.get(server_id)
        if state and state.runtime:
            output = await self.send_command(server_id, cmd.format(p=player))
            return output[-1] if output else "Command sent"
        # Offline: apply directly to state files so the change survives the next start.
        await self._console_log(server_id, f"> {cmd.format(p=player)} (applied offline)")
        sdir = self.get_server_dir(server_id)
        filename = {"ops": "ops.json", "whitelist": "whitelist.json", "bans": "banned-players.json"}[kind]
        entries = read_state_list(sdir, filename)
        names = [e.get("name", "").lower() for e in entries]
        if action == "add" and player.lower() not in names:
            entry = {"uuid": f"offline:{player.lower()}", "name": player}
            if kind == "ops":
                entry["level"] = 4
            if kind == "bans":
                entry.update({"created": datetime.utcnow().isoformat(), "source": "Cyber Host", "reason": "Banned by an operator"})
            entries.append(entry)
            write_state_list(sdir, filename, entries)
            return f"Applied offline: {player} -> {kind} (added)"
        if action == "remove" and player.lower() in names:
            entries = [e for e in entries if e.get("name", "").lower() != player.lower()]
            write_state_list(sdir, filename, entries)
            return f"Applied offline: {player} -> {kind} (removed)"
        return f"Nothing changed: {player} is not in {kind}" if action == "remove" else f"Nothing changed: {player} already in {kind}"

    # ------------------------------------------------------------ properties
    async def get_properties(self, server_id: str) -> Dict[str, str]:
        """Parse the server.properties file into a dict."""
        props: Dict[str, str] = {}
        path = self.get_server_dir(server_id) / "server.properties"
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    props[k] = v
        return props

    async def set_properties(self, server_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and persist property updates; flags a restart if server is online."""
        validated: Dict[str, str] = {}
        for key, value in updates.items():
            if key not in EDITABLE_PROPERTIES:
                raise ValueError(f"Property '{key}' is not editable")
            converted = EDITABLE_PROPERTIES[key](value)
            if converted is None:
                raise ValueError(f"Invalid value for '{key}': {value}")
            validated[key] = converted
        props = await self.get_properties(server_id)
        props.update(validated)
        self._write_properties(self.get_server_dir(server_id), props)
        
        db_fields = {
            "motd": validated.get("motd"),
            "gamemode": validated.get("gamemode"),
            "difficulty": validated.get("difficulty"),
            "level_seed": validated.get("level-seed"),
        }
        with get_db() as db:
            row = self._db_get(db, server_id)
            if not row:
                raise ValueError("Server not found")
            for field, value in db_fields.items():
                if value is not None:
                    setattr(row, field, value if field != "level_seed" else (value or None))
            if "max-players" in validated:
                row.max_players = int(validated["max-players"])
            if "pvp" in validated:
                row.pvp = validated["pvp"] == "true"
            if "white-list" in validated:
                row.whitelist_enabled = validated["white-list"] == "true"
            state = self._states.get(server_id)
            if row.status == ServerStatus.ONLINE and state:
                state.config_dirty = True
                await self._console_log(server_id, "[cyber/WARN]: Settings saved. Restart the server to apply them.")
        return validated

    # --------------------------------------------------------------- backups
    async def _run_backup(self, server_id: str, kind: str = "manual") -> DBServerBackup:
        """Zip the world + config into the backups directory and record it."""
        sdir = self.get_server_dir(server_id)
        with get_db() as db:
            row = self._db_get(db, server_id)
            if not row:
                raise ValueError("Server not found")
            world_name = row.world_name
        bdir = self.get_backups_dir(server_id)
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        filename = f"backup-{stamp}-{kind}.zip"
        dest = bdir / filename
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            world = sdir / world_name
            if world.exists():
                zf.write(world, world_name)  # keep the dir entry even when the world is empty
                for fpath in sorted(world.rglob("*")):
                    zf.write(fpath, str(fpath.relative_to(sdir)))
            for name in ("server.properties", "ops.json", "whitelist.json"):
                fpath = sdir / name
                if fpath.exists():
                    zf.write(fpath, name)
        size = dest.stat().st_size
        with get_db() as db:
            row = DBServerBackup(server_id=server_id, filename=filename, size_bytes=size, kind=kind)
            db.add(row)
        await self._console_log(server_id, f"[cyber/INFO]: {kind.capitalize()} backup created: {filename} ({size // 1024} KB)")
        await self._prune_backups(server_id)
        return row

    async def create_backup(self, server_id: str) -> DBServerBackup:
        return await self._run_backup(server_id, kind="manual")

    async def _prune_backups(self, server_id: str) -> None:
        with get_db() as db:
            rows = (
                db.query(DBServerBackup)
                .filter(DBServerBackup.server_id == server_id)
                .order_by(DBServerBackup.created_at.desc())
                .all()
            )
            for stale in rows[settings.MAX_BACKUPS_PER_SERVER:]:
                fpath = self.get_backups_dir(server_id) / stale.filename
                if fpath.exists():
                    fpath.unlink(missing_ok=True)
                db.delete(stale)

    async def restore_backup(self, server_id: str, backup_id: int) -> None:
        """Restore a backup. Requires the server to be offline."""
        with get_db() as db:
            row = self._db_get(db, server_id)
            if not row:
                raise ValueError("Server not found")
            if row.status != ServerStatus.OFFLINE and row.status != ServerStatus.ERROR:
                raise ValueError("Stop the server before restoring a backup.")
            world_name = row.world_name
            backup = (
                db.query(DBServerBackup)
                .filter(DBServerBackup.id == backup_id, DBServerBackup.server_id == server_id)
                .first()
            )
            if not backup:
                raise ValueError("Backup not found")
            filename = backup.filename
        path = self.get_backups_dir(server_id) / filename
        if not path.exists():
            raise ValueError("Backup file is missing on disk")
        sdir = self.get_server_dir(server_id)
        world = sdir / world_name
        if world.exists():
            shutil.rmtree(world, ignore_errors=True)
        safe_extract_zip(path, sdir)
        await self._console_log(server_id, f"[cyber/INFO]: Backup restored: {filename}")

    async def delete_backup(self, server_id: str, backup_id: int) -> bool:
        with get_db() as db:
            backup = (
                db.query(DBServerBackup)
                .filter(DBServerBackup.id == backup_id, DBServerBackup.server_id == server_id)
                .first()
            )
            if not backup:
                return False
            filename = backup.filename
            db.delete(backup)
        path = self.get_backups_dir(server_id) / filename
        if path.exists():
            path.unlink(missing_ok=True)
        return True

    def get_backup_path(self, server_id: str, backup_id: int) -> Optional[Path]:
        with get_db() as db:
            backup = (
                db.query(DBServerBackup)
                .filter(DBServerBackup.id == backup_id, DBServerBackup.server_id == server_id)
                .first()
            )
            if not backup:
                return None
            filename = backup.filename
        path = self.get_backups_dir(server_id) / filename
        validate_safe_path(self.get_backups_dir(server_id), path)
        return path if path.exists() else None

    # ----------------------------------------------------------------- files
    def list_files(self, server_id: str, subpath: str = "") -> List[Dict[str, Any]]:
        """List files inside the server directory (path-traversal safe)."""
        base = self.get_server_dir(server_id)
        target = base / subpath if subpath else base
        validate_safe_path(base, target)
        entries: List[Dict[str, Any]] = []
        for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if entry.name in ("backups", "logs"):
                continue
            stat = entry.stat()
            entries.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size_bytes": stat.st_size if entry.is_file() else 0,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            })
        return entries

    def resolve_file(self, server_id: str, subpath: str) -> Optional[Path]:
        """Resolve a file path for download, strictly inside the server directory."""
        base = self.get_server_dir(server_id)
        target = base / subpath
        validate_safe_path(base, target)
        if target.is_file():
            return target
        return None

    # -------------------------------------------------------------- uploads
    def save_uploaded_jar(self, server_id: str, src_path: Path) -> int:
        """Move an uploaded server.jar into the server directory. Returns its size."""
        if src_path.suffix.lower() != ".jar":
            raise ValueError("Only .jar files are accepted as server software.")
        dest = self.get_server_dir(server_id) / "server.jar"
        validate_safe_path(self.get_server_dir(server_id), dest)
        shutil.move(str(src_path), str(dest))
        with get_db() as db:
            row = self._db_get(db, server_id)
            if row:
                row.jar_ready = True
        size = dest.stat().st_size
        logger.info(f"server.jar uploaded for {server_id} ({size // (1024 * 1024)} MB)")
        return size

    def save_uploaded_bedrock_zip(self, server_id: str, src_path: Path) -> int:
        """Extract an uploaded official Bedrock Dedicated Server zip into the server dir."""
        with get_db() as db:
            row = self._db_get(db, server_id)
            if not row or row.software != "bedrock":
                raise ValueError("Bedrock server software can only be uploaded to Bedrock servers.")
        sdir = self.get_server_dir(server_id)
        safe_extract_zip(src_path, sdir)
        binary = "bedrock_server.exe" if os.name == "nt" else "bedrock_server"
        if not (sdir / binary).exists():
            raise ValueError("The zip does not contain a bedrock_server binary. Upload the official BDS archive unmodified.")
        try:
            (sdir / binary).chmod(0o755)
        except OSError:
            pass
        size = src_path.stat().st_size
        logger.info(f"Bedrock server zip uploaded for {server_id} ({size // (1024 * 1024)} MB)")
        return size

    # ---------------------------------------------------------------- worlds
    _WORLD_MARKERS = ("level.dat", "db", "levelname.txt")

    def list_worlds(self, server_id: str) -> List[Dict[str, Any]]:
        """Discover world directories (Java or Bedrock) inside the server root."""
        base = self.get_server_dir(server_id)
        with get_db() as db:
            row = self._db_get(db, server_id)
            active = row.world_name if row else "world"
        worlds: List[Dict[str, Any]] = []
        for entry in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if not entry.is_dir():
                continue
            if entry.name in ("backups", "logs", "plugins", "mods", "cache", "config"):
                continue
            is_active = entry.name == active
            # A world folder must contain world data; the active world is always listed.
            if not is_active and not any((entry / marker).exists() for marker in self._WORLD_MARKERS):
                continue
            size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
            stat = entry.stat()
            worlds.append({
                "name": entry.name,
                "active": is_active,
                "size_bytes": size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
        return worlds

    def import_world_zip(self, server_id: str, src_path: Path, world_name: str) -> str:
        """Import an uploaded world archive into the server root as `world_name`."""
        world_name = world_name.strip()[:48]
        if not world_name or not world_name.replace("_", "").replace("-", "").replace(" ", "").isalnum():
            raise ValueError("World name must contain only letters, digits, dashes and underscores.")
        with get_db() as db:
            row = self._db_get(db, server_id)
            if not row:
                raise ValueError("Server not found")
            if row.status not in (ServerStatus.OFFLINE, ServerStatus.ERROR):
                raise ValueError("Stop the server before importing a world.")
        dest = self.get_server_dir(server_id) / world_name
        if dest.exists():
            raise ValueError(f"A folder named '{world_name}' already exists. Choose another name.")
        safe_extract_zip(src_path, dest)
        # Accept archives that wrap the world in a single top-level folder.
        children = list(dest.iterdir())
        if len(children) == 1 and children[0].is_dir() and any(
            (children[0] / m).exists() for m in self._WORLD_MARKERS
        ):
            inner = children[0]
            tmp = dest.parent / f".import_{uuid.uuid4().hex[:8]}"
            inner.rename(tmp)
            shutil.rmtree(dest, ignore_errors=True)
            tmp.rename(dest)
        if not any((dest / m).exists() for m in self._WORLD_MARKERS):
            shutil.rmtree(dest, ignore_errors=True)
            raise ValueError("The archive does not look like a Minecraft world (no level.dat / db / levelname.txt found).")
        return world_name

    def export_world_zip(self, server_id: str, world_name: str) -> Optional[Path]:
        """Zip a world directory for download; returns the archive path."""
        base = self.get_server_dir(server_id)
        world = base / world_name
        validate_safe_path(base, world)
        if not world.is_dir():
            return None
        out_dir = self.get_backups_dir(server_id)
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        dest = out_dir / f"world-{world_name}-{stamp}.zip"
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
            for fpath in sorted(world.rglob("*")):
                if fpath.is_file():
                    zf.write(fpath, str(fpath.relative_to(world)))
        return dest

    def delete_world(self, server_id: str, world_name: str) -> bool:
        """Delete a non-active world directory (server must be offline)."""
        with get_db() as db:
            row = self._db_get(db, server_id)
            if not row:
                raise ValueError("Server not found")
            if row.status not in (ServerStatus.OFFLINE, ServerStatus.ERROR):
                raise ValueError("Stop the server before deleting a world.")
            if row.world_name == world_name:
                raise ValueError("The active world cannot be deleted. Select another world first.")
        base = self.get_server_dir(server_id)
        world = base / world_name
        validate_safe_path(base, world)
        if not world.is_dir():
            return False
        shutil.rmtree(world, ignore_errors=True)
        return True

    def set_active_world(self, server_id: str, world_name: str) -> str:
        """Point the server at a different imported world (offline only)."""
        with get_db() as db:
            row = self._db_get(db, server_id)
            if not row:
                raise ValueError("Server not found")
            if row.status not in (ServerStatus.OFFLINE, ServerStatus.ERROR):
                raise ValueError("Stop the server before switching worlds.")
            base = self.get_server_dir(server_id)
            world = base / world_name
            validate_safe_path(base, world)
            if not world.is_dir():
                raise ValueError(f"World '{world_name}' does not exist on this server.")
            previous = row.world_name
            row.world_name = world_name
        # Rewrite properties so the next start boots the selected world.
        with get_db() as db:
            row = self._db_get(db, server_id)
            self._write_properties(self.get_server_dir(server_id), self._build_properties(row))
        return previous

    # ------------------------------------------------------------- monitoring
    async def _monitor_loop(self) -> None:
        """Periodic maintenance: playtime accounting and optional idle auto-shutdown."""
        while True:
            await asyncio.sleep(60)
            try:
                now = datetime.utcnow()
                with get_db() as db:
                    online = db.query(DBServer).filter(DBServer.status == ServerStatus.ONLINE).all()
                    for row in online:
                        row.playtime_seconds = (row.playtime_seconds or 0) + 60
                if settings.SERVER_IDLE_SHUTDOWN_MINUTES > 0:
                    for sid in [r.id for r in online]:
                        state = self._states.get(sid)
                        if state and state.last_activity:
                            idle_minutes = (now - state.last_activity).total_seconds() / 60
                            if idle_minutes >= settings.SERVER_IDLE_SHUTDOWN_MINUTES:
                                await self._console_log(sid, "[cyber/INFO]: Auto-shutdown: idle time limit reached.")
                                await self.request_stop(sid, reason="idle auto-shutdown")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Monitor loop error: {e}")

    # ----------------------------------------------------------- serialization
    def serialize(self, row: DBServer) -> Dict[str, Any]:
        """Serialize a DB server row plus live state for API/dashboard consumption."""
        state = self._states.get(row.id)
        uptime_seconds = 0
        if state and state.started_at and row.status == ServerStatus.ONLINE:
            uptime_seconds = int((datetime.utcnow() - state.started_at).total_seconds())
        return {
            "id": row.id,
            "owner_id": row.owner_id,
            "name": row.name,
            "description": row.description,
            "software": row.software,
            "mc_version": row.mc_version,
            "status": row.status,
            "status_detail": row.status_detail,
            "address": row.address,
            "port": row.port,
            "motd": row.motd,
            "gamemode": row.gamemode,
            "difficulty": row.difficulty,
            "max_players": row.max_players,
            "level_seed": row.level_seed,
            "pvp": row.pvp,
            "whitelist_enabled": row.whitelist_enabled,
            "ram_mb": row.ram_mb,
            "auto_backup": row.auto_backup,
            "jar_ready": row.jar_ready,
            "playtime_seconds": row.playtime_seconds or 0,
            "uptime_seconds": uptime_seconds,
            "queue_position": state.queue_position if state else None,
            "config_dirty": state.config_dirty if state else False,
            "last_started": row.last_started.isoformat() if row.last_started else None,
            "created_at": row.created_at.isoformat() if row.created_at else None
        }

# Global host manager
server_manager = ServerManager()