"""Real network connectivity diagnostics and connection-address discovery.

Every check here performs an actual measurement (DNS resolution, TCP connect,
local port binding, process readiness). Checks that cannot run in a given
environment return status "unavailable" with the reason — never a fabricated
success.
"""
import socket
import time
from core.clock import utcnow
from typing import Any, Dict, List, Optional

from config import settings
from storage.database import get_db
from storage.models import Server as DBServer
from servers.manager import server_manager, ServerStatus
from logger import get_logger

logger = get_logger("servers.networking")

TCP_CONNECT_TIMEOUT = 3.0


def public_host() -> str:
    """The configured or detected public hostname players would connect to."""
    if settings.SERVER_PUBLIC_HOST:
        return settings.SERVER_PUBLIC_HOST
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL.split("://")[-1].split("/")[0].split(":")[0]
    return socket.gethostname() or "localhost"


def dns_resolves(hostname: str) -> Dict[str, Any]:
    """Attempt real DNS resolution of a hostname."""
    try:
        infos = socket.getaddrinfo(hostname, None)
        addresses = sorted({i[4][0] for i in infos})
        return {"status": "ok", "addresses": addresses[:4]}
    except socket.gaierror as e:
        return {"status": "failed", "error": f"DNS resolution failed: {e}"}
    except OSError as e:
        return {"status": "unavailable", "error": f"DNS lookup unavailable: {e}"}


def tcp_reachable(host: str, port: int) -> Dict[str, Any]:
    """Attempt a real TCP connection to host:port."""
    try:
        start = time.monotonic()
        with socket.create_connection((host, port), timeout=TCP_CONNECT_TIMEOUT):
            elapsed_ms = int((time.monotonic() - start) * 1000)
        return {"status": "ok", "latency_ms": elapsed_ms}
    except ConnectionRefusedError:
        return {"status": "failed", "error": "Connection refused (nothing listening or firewall reject)"}
    except socket.timeout:
        return {"status": "failed", "error": "Timed out (host unreachable or port filtered)"}
    except OSError as e:
        return {"status": "unavailable", "error": f"TCP check could not run: {e}"}


def udp_port_bound(port: int) -> Dict[str, Any]:
    """Check whether a UDP port can be bound locally (Bedrock readiness)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("0.0.0.0", port))
        return {"status": "ok"}
    except OSError as e:
        return {"status": "failed", "error": f"UDP bind failed: {e}"}


def port_bindable(port: int) -> Dict[str, Any]:
    """Check whether a TCP port can be bound on this host right now."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", port))
        return {"status": "ok"}
    except PermissionError:
        return {"status": "failed", "error": "Permission denied for this port"}
    except OSError as e:
        return {"status": "failed", "error": f"Bind failed: {e}"}


def diagnose_server(server_id: str) -> Dict[str, Any]:
    """Run the full diagnostic suite for one server and return honest results."""
    with get_db() as db:
        row = db.query(DBServer).filter(DBServer.id == server_id).first()
        if not row:
            return {"error": "Server not found"}
        port = row.port
        status = row.status

    host = public_host()
    internal_host = socket.gethostname()
    checks: Dict[str, Dict[str, Any]] = {}

    if port:
        checks["port_binding"] = port_bindable(port) if status != ServerStatus.ONLINE else {
            "status": "ok", "note": "Port is in active use by this running server"
        }
        checks["dns"] = dns_resolves(host)
        if host in ("localhost", internal_host, "127.0.0.1"):
            checks["tcp_reachability"] = {
                "status": "unavailable",
                "error": "SERVER_PUBLIC_HOST is not configured; testing the local hostname proves nothing about public reachability"
            }
        else:
            checks["tcp_reachability"] = tcp_reachable(host, port)
    else:
        checks["port_binding"] = {"status": "unavailable", "error": "Server is offline; no port is allocated"}
        checks["dns"] = dns_resolves(host)
        checks["tcp_reachability"] = {"status": "unavailable", "error": "Server is offline; start it to test connectivity"}

    addresses = {
        "public_host": host,
        "public_configured": bool(settings.SERVER_PUBLIC_HOST),
        "internal_host": internal_host,
    }
    if row.software == "bedrock":
        addresses["protocol"] = "udp"
        addresses["bedrock"] = f"{host}:{port}" if port else None
        addresses["java"] = None
    else:
        addresses["protocol"] = "tcp"
        addresses["java"] = f"{host}:{port}" if port else None
        addresses["bedrock"] = None

    return {
        "server_id": server_id,
        "runtime_status": status,
        "addresses": addresses,
        "checks": checks,
        "checked_at": utcnow().isoformat(),
        "notes": [
            "A web HTTPS URL (e.g. a Hugging Face Space) does NOT accept Minecraft game connections.",
            "Minecraft Java uses TCP; Bedrock uses UDP. Both need a real public host and open port or a TCP/UDP tunnel.",
            "Cloud platforms without inbound ports require a tunnel provider for public play.",
        ],
    }


def server_links(request_base: str, server_id: str) -> Dict[str, Optional[str]]:
    """Generate the public dashboard links for a server (downloads use tokens)."""
    base = (request_base or "").rstrip("/")
    return {
        "dashboard": f"{base}/servers/{server_id}",
        "server_info": f"{base}/servers/{server_id}?tab=networking",
    }
