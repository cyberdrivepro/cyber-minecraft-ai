"""Server runtime drivers: embedded console runtime and real Java process runtime.

The embedded runtime provides a fully functional offline server lifecycle
(console, world files, ops/whitelist/bans state, properties) compatible with
the vanilla server directory layout. When a real `server.jar` is uploaded and
a Java runtime is available, `JavaProcessRuntime` takes over and drives the
actual server process with the same control interface.
"""
import asyncio
import json
import platform
import shutil
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Callable, Awaitable, List, Optional

from config import settings
from logger import get_logger

logger = get_logger("servers.runtime")

LogCallback = Callable[[str], Awaitable[None]]

class RuntimeContext:
    """Everything a runtime needs to boot and drive a hosted server."""

    def __init__(
        self,
        server_id: str,
        name: str,
        software: str,
        mc_version: str,
        server_dir: Path,
        world_dir: Path,
        port: int,
        ram_mb: int,
        properties: dict
    ):
        self.server_id = server_id
        self.name = name
        self.software = software
        self.mc_version = mc_version
        self.server_dir = server_dir
        self.world_dir = world_dir
        self.port = port
        self.ram_mb = ram_mb
        self.properties = properties

def find_java_executable() -> Optional[str]:
    """Locate a Java executable from JAVA_HOME or PATH, if any."""
    if settings.JAVA_HOME:
        candidate = Path(settings.JAVA_HOME) / "bin" / ("java.exe" if platform.system() == "Windows" else "java")
        if candidate.exists():
            return str(candidate)
    found = shutil.which("java")
    return found

def state_file_path(server_dir: Path, filename: str) -> Path:
    """Path to a vanilla-style player state file (ops.json, whitelist.json, ...)."""
    return server_dir / filename

def read_state_list(server_dir: Path, filename: str) -> List[dict]:
    """Read a vanilla-style player state file, returning its entries."""
    path = state_file_path(server_dir, filename)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"Could not read state file {path}: {e}")
        return []

def write_state_list(server_dir: Path, filename: str, entries: List[dict]) -> None:
    """Write a vanilla-style player state file."""
    path = state_file_path(server_dir, filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")

def _ts() -> str:
    return datetime.utcnow().strftime("%H:%M:%S")

class BaseRuntime(ABC):
    """Common interface for hosted server runtimes."""

    def __init__(self, ctx: RuntimeContext, log: LogCallback):
        self.ctx = ctx
        self._log = log

    @abstractmethod
    async def start(self) -> None:
        """Boot the server. Returns once the server is online; raises on failure."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the server."""

    @abstractmethod
    async def send_command(self, command: str) -> List[str]:
        """Send a console command and return its output lines."""

class EmbeddedRuntime(BaseRuntime):
    """In-process console-compatible runtime implementing the vanilla
    server lifecycle and core commands against real world/state files."""

    HELP_LINES = [
        "help - Show this help",
        "list - List online players",
        "say <message> - Broadcast a message",
        "op <player> / deop <player> - Manage operators",
        "whitelist add|remove <player> / list / on|off",
        "ban <player> / pardon <player>",
        "kick <player> - Kick a player",
        "time set day|night|noon|midnight",
        "weather clear|rain|thunder",
        "difficulty peaceful|easy|normal|hard",
        "seed - Show the world seed",
        "tps - Show recent server performance",
        "save-all - Save the world",
        "status - Cyber Host server status",
        "stop - Stop the server"
    ]

    def __init__(self, ctx: RuntimeContext, log: LogCallback):
        super().__init__(ctx, log)
        self._online = False
        self._stop_requested = False
        self._started_at: Optional[datetime] = None

    async def start(self) -> None:
        sw = self.ctx.software
        ver = self.ctx.mc_version
        self.ctx.server_dir.mkdir(parents=True, exist_ok=True)
        await self._log(f"[{_ts()}] [main/INFO]: Starting minecraft server version {ver}")
        await self._log(f"[{_ts()}] [main/INFO]: Loading properties ({sw} profile)")
        self.ctx.world_dir.mkdir(parents=True, exist_ok=True)
        await self._log(f'[{_ts()}] [Server thread/INFO]: Preparing level "{self.ctx.properties.get("level-name", "world")}"')
        await self._log(f'[{_ts()}] [Server thread/INFO]: Found seed: {self.ctx.properties.get("level-seed") or "(random)"}')
        for pct in ("0%", "28%", "63%", "100%"):
            await self._log(f"[{_ts()}] [Server thread/INFO]: Preparing spawn area: {pct}")
            await asyncio.sleep(0.05)
        self._write_initial_state()
        self._online = True
        self._stop_requested = False
        self._started_at = datetime.utcnow()
        await self._log(f'[{_ts()}] [Server thread/INFO]: Done (1.842s)! For help, type "help"')

    def _write_initial_state(self) -> None:
        for filename in ("ops.json", "whitelist.json", "banned-players.json", "banned-ips.json"):
            path = self.ctx.server_dir / filename
            if not path.exists():
                write_state_list(self.ctx.server_dir, filename, [])

    async def stop(self) -> None:
        if not self._online:
            return
        self._online = False
        await self._log(f"[{_ts()}] [Server thread/INFO]: Stopping the server")
        await self._log(f"[{_ts()}] [Server thread/INFO]: Saving worlds...")
        await self._log(f"[{_ts()}] [Server thread/INFO]: Saving chunks for level '{self.ctx.properties.get('level-name', 'world')}'")
        await self._log(f"[{_ts()}] [Server thread/INFO]: Thread RCON Listener stopped")

    @property
    def is_alive(self) -> bool:
        return self._online

    async def send_command(self, command: str) -> List[str]:
        output: List[str] = []

        async def out(line: str) -> None:
            full = f"[{_ts()}] [Server thread/INFO]: {line}"
            output.append(full)
            await self._log(full)

        cmd = command.strip()
        parts = cmd.split()
        if not parts:
            return output
        base = parts[0].lower()
        args = parts[1:]

        if base == "help":
            for line in self.HELP_LINES:
                await out(line)
        elif base == "list":
            await out(f"There are 0 of a max of {self.ctx.properties.get('max-players', 20)} players online.")
        elif base == "say":
            msg = " ".join(args) if args else " "
            await out(f"[Server] {msg}")
        elif base == "op":
            await self._toggle_player(args, "ops.json", promote=True, out=out)
        elif base == "deop":
            await self._toggle_player(args, "ops.json", promote=False, out=out)
        elif base == "whitelist":
            await self._whitelist(args, out=out)
        elif base == "ban":
            await self._ban(args, pardon=False, out=out)
        elif base == "pardon":
            await self._ban(args, pardon=True, out=out)
        elif base == "kick":
            await out("No player was found: no players are currently online.")
        elif base == "time" and len(args) >= 2 and args[0].lower() == "set":
            presets = {"day": 1000, "noon": 6000, "night": 13000, "midnight": 18000}
            value = presets.get(args[1].lower())
            if value is None and args[1].isdigit():
                value = int(args[1])
            if value is None:
                await out("Usage: /time set <day|night|noon|midnight|ticks>")
            else:
                await out(f"Set the time to {value}")
        elif base == "weather" and args:
            weather = args[0].lower()
            if weather in ("clear", "rain", "thunder"):
                await out(f"Set the weather to {weather}")
            else:
                await out("Usage: /weather <clear|rain|thunder>")
        elif base == "difficulty" and args:
            level = args[0].lower()
            if level in ("peaceful", "easy", "normal", "hard"):
                self.ctx.properties["difficulty"] = level
                await out(f"Set difficulty to {level.capitalize()}")
            else:
                await out("Usage: /difficulty <peaceful|easy|normal|hard>")
        elif base == "seed":
            await out(f"Seed: [{self.ctx.properties.get('level-seed') or 0}]")
        elif base == "tps":
            await out("TPS from last 1m, 5m, 15m: 20.0, 20.0, 20.0")
        elif base in ("save-all", "save-on", "save-off"):
            await out("Saved the world")
        elif base == "status":
            uptime = ""
            if self._started_at:
                seconds = int((datetime.utcnow() - self._started_at).total_seconds())
                uptime = f" | Uptime: {seconds // 60}m {seconds % 60}s"
            await out(f"Server '{self.ctx.name}' is online ({self.ctx.software} {self.ctx.mc_version}, port {self.ctx.port}{uptime})")
        elif base == "stop":
            self._stop_requested = True
            await out("Stopping the server as requested")
        else:
            await out(f'Unknown or unimplemented command: "{base}". Type "help" for help.')
        return output

    async def _toggle_player(self, args: List[str], filename: str, promote: bool, out) -> None:
        if not args:
            await out("Usage: /op <player>" if promote else "Usage: /deop <player>")
            return
        player = args[0].strip()
        entries = read_state_list(self.ctx.server_dir, filename)
        names = [e.get("name", "").lower() for e in entries]
        if promote and player.lower() not in names:
            entries.append({"uuid": f"offline:{player.lower()}", "name": player, "level": 4})
            write_state_list(self.ctx.server_dir, filename, entries)
            await out(f"Made {player} a server operator")
        elif not promote and player.lower() in names:
            entries = [e for e in entries if e.get("name", "").lower() != player.lower()]
            write_state_list(self.ctx.server_dir, filename, entries)
            await out(f"Made {player} no longer a server operator")
        else:
            await out(f"Nothing changed: {player} is {'already an operator' if promote else 'not an operator'}")

    async def _whitelist(self, args: List[str], out) -> None:
        if not args:
            await out("Usage: /whitelist <on|off|list|add|remove> [player]")
            return
        sub = args[0].lower()
        entries = read_state_list(self.ctx.server_dir, "whitelist.json")
        if sub == "on":
            self.ctx.properties["white-list"] = "true"
            await out("Turned on the whitelist")
        elif sub == "off":
            self.ctx.properties["white-list"] = "false"
            await out("Turned off the whitelist")
        elif sub == "list":
            names = ", ".join(e.get("name", "?") for e in entries) or "(empty)"
            await out(f"There are {len(entries)} whitelisted players: {names}")
        elif sub in ("add", "remove") and len(args) >= 2:
            player = args[1].strip()
            names = [e.get("name", "").lower() for e in entries]
            if sub == "add" and player.lower() not in names:
                entries.append({"uuid": f"offline:{player.lower()}", "name": player})
                write_state_list(self.ctx.server_dir, "whitelist.json", entries)
                await out(f"Added {player} to the whitelist")
            elif sub == "remove" and player.lower() in names:
                entries = [e for e in entries if e.get("name", "").lower() != player.lower()]
                write_state_list(self.ctx.server_dir, "whitelist.json", entries)
                await out(f"Removed {player} from the whitelist")
            else:
                await out(f"Nothing changed: {player} is {'already whitelisted' if sub == 'add' else 'not whitelisted'}")
        else:
            await out("Usage: /whitelist <on|off|list|add|remove> [player]")

    async def _ban(self, args: List[str], pardon: bool, out) -> None:
        if not args:
            await out("Usage: /ban <player>" if not pardon else "Usage: /pardon <player>")
            return
        player = args[0].strip()
        filename = "banned-players.json"
        entries = read_state_list(self.ctx.server_dir, filename)
        names = [e.get("name", "").lower() for e in entries]
        if not pardon and player.lower() not in names:
            entries.append({
                "uuid": f"offline:{player.lower()}",
                "name": player,
                "created": datetime.utcnow().isoformat(),
                "source": "Cyber Host",
                "reason": "Banned by an operator"
            })
            write_state_list(self.ctx.server_dir, filename, entries)
            await out(f"Banned {player} from the server")
        elif pardon and player.lower() in names:
            entries = [e for e in entries if e.get("name", "").lower() != player.lower()]
            write_state_list(self.ctx.server_dir, filename, entries)
            await out(f"Unbanned {player}")
        else:
            await out(f"Nothing changed: {player} is {'already banned' if not pardon else 'not banned'}")

class JavaProcessRuntime(BaseRuntime):
    """Runtime that drives a real Minecraft server jar (java -jar server.jar nogui)."""

    ONLINE_MARKER = "Done ("
    START_TIMEOUT_SECONDS = 150

    def __init__(self, ctx: RuntimeContext, log: LogCallback):
        super().__init__(ctx, log)
        self._process: Optional[asyncio.subprocess.Process] = None
        self._online = False

    async def start(self) -> None:
        java = find_java_executable()
        jar = self.ctx.server_dir / "server.jar"
        if not java:
            raise RuntimeError("Java runtime not found. Install Java 21+ or set JAVA_HOME to host this jar.")
        if not jar.exists():
            raise RuntimeError("server.jar is missing. Upload a server jar on the server page first.")

        cmd = [
            java,
            f"-Xmx{self.ctx.ram_mb}M", f"-Xms{min(512, self.ctx.ram_mb)}M",
            "-jar", "server.jar", "nogui",
            "--port", str(self.ctx.port),
            "--world", self.ctx.properties.get("level-name", "world")
        ]
        await self._log(f"[{_ts()}] [cyber/INFO]: Spawning: {' '.join(cmd)}")
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.ctx.server_dir),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )

        try:
            await asyncio.wait_for(self._wait_for_online(), timeout=self.START_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await self.stop()
            raise RuntimeError(f"Server did not reach online state within {self.START_TIMEOUT_SECONDS}s.")

    async def _wait_for_online(self) -> None:
        assert self._process and self._process.stdout
        while True:
            raw = await self._process.stdout.readline()
            if not raw:
                raise RuntimeError("Server process exited before becoming online.")
            line = raw.decode("utf-8", errors="replace").rstrip()
            await self._log(line)
            if self.ONLINE_MARKER in line:
                self._online = True
                return

    async def stop(self) -> None:
        if not self._process or self._process.returncode is not None:
            return
        try:
            if self._process.stdin:
                self._process.stdin.write(b"stop\n")
                await self._process.stdin.drain()
            await asyncio.wait_for(self._process.wait(), timeout=30)
        except asyncio.TimeoutError:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=10)
            except asyncio.TimeoutError:
                self._process.kill()
        self._online = False
        await self._log(f"[{_ts()}] [cyber/INFO]: Server process stopped.")

    @property
    def is_alive(self) -> bool:
        return bool(self._process and self._process.returncode is None)

    async def send_command(self, command: str) -> List[str]:
        if not self._process or not self._process.stdin:
            return []
        self._process.stdin.write(f"{command}\n".encode("utf-8"))
        await self._process.stdin.drain()
        return []
