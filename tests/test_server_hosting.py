"""Tests for the Cyber Host server hosting module (manager + API)."""
import asyncio

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app import app  # ensures lifespan-managed singletons exist
from servers.manager import server_manager, ServerStatus
from servers.runtime import read_state_list
from storage.database import get_db
from storage.models import Server as DBServer


async def wait_for_status(server_id: str, wanted: set, timeout: float = 15.0) -> str:
    """Poll until the server reaches one of the wanted statuses."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        with get_db() as db:
            row = db.query(DBServer).filter(DBServer.id == server_id).first()
            if row and row.status in wanted:
                return row.status
        await asyncio.sleep(0.1)
    raise TimeoutError(f"Server {server_id} did not reach {wanted} in time")


@pytest_asyncio.fixture(autouse=True)
async def running_host():
    """Run the host manager (start-queue workers + monitor) for each test.

    httpx ASGITransport does not execute the app lifespan, so the manager's
    workers must be started explicitly here. Shutdown also stops any servers
    left running by a test.
    """
    await server_manager.startup()
    yield
    await server_manager.shutdown()


@pytest_asyncio.fixture()
async def hosted_server():
    row = server_manager.create_server(
        owner_id="test_owner",
        name="Test Survival",
        software="paper",
        mc_version="1.21.4",
        eula_accepted=True
    )
    yield row
    await server_manager.delete_server(row.id)


# ------------------------------------------------------------- manager tests
@pytest.mark.asyncio
async def test_create_server_writes_files(hosted_server):
    sdir = server_manager.get_server_dir(hosted_server.id)
    assert (sdir / "server.properties").exists()
    assert (sdir / "eula.txt").exists()
    assert "eula=true" in (sdir / "eula.txt").read_text(encoding="utf-8")
    assert hosted_server.status == ServerStatus.OFFLINE


@pytest.mark.asyncio
async def test_create_server_rejects_bad_input():
    with pytest.raises(ValueError):
        server_manager.create_server(
            owner_id="test_owner", name="X", software="paper", mc_version="1.21.4", eula_accepted=False
        )
    with pytest.raises(ValueError):
        server_manager.create_server(
            owner_id="test_owner", name="X", software="unknown_sw", mc_version="1.21.4", eula_accepted=True
        )


@pytest.mark.asyncio
async def test_full_lifecycle(hosted_server):
    sid = hosted_server.id
    await server_manager.request_start(sid)
    status = await wait_for_status(sid, {ServerStatus.ONLINE})
    assert status == ServerStatus.ONLINE

    with get_db() as db:
        row = db.query(DBServer).filter(DBServer.id == sid).first()
        assert row.address and row.port

    console = server_manager.get_console(sid)
    assert any("Done" in line for line in console)
    assert any("Server address" in line for line in console)

    # Commands
    output = await server_manager.send_command(sid, "say hello world")
    assert any("[Server] hello world" in line for line in output)
    output = await server_manager.send_command(sid, "list")
    assert any("0 of a max of 20" in line for line in output)

    # Player management while online goes through console commands
    message = await server_manager.manage_player(sid, "ops", "add", "Steve")
    assert "Steve" in message
    ops = await server_manager.list_players(sid, "ops")
    assert [p["name"] for p in ops] == ["Steve"]

    # Properties update while online flags a restart
    await server_manager.set_properties(sid, {"motd": "Updated MOTD", "max-players": 50})
    props = await server_manager.get_properties(sid)
    assert props["motd"] == "Updated MOTD"
    assert props["max-players"] == "50"

    # Stop: status resets, address cleared, auto-backup created
    await server_manager.request_stop(sid)
    status = await wait_for_status(sid, {ServerStatus.OFFLINE})
    assert status == ServerStatus.OFFLINE
    with get_db() as db:
        row = db.query(DBServer).filter(DBServer.id == sid).first()
        assert row.address is None
    backup = await server_manager.create_backup(sid)
    assert backup.filename.endswith(".zip")

    # Offline player management applies directly to state files
    message = await server_manager.manage_player(sid, "whitelist", "add", "Alex")
    assert "Alex" in message
    whitelist = read_state_list(server_manager.get_server_dir(sid), "whitelist.json")
    assert [p["name"] for p in whitelist] == ["Alex"]


@pytest.mark.asyncio
async def test_backup_restore(hosted_server):
    sid = hosted_server.id
    await server_manager.request_start(sid)
    await wait_for_status(sid, {ServerStatus.ONLINE})
    await server_manager.send_command(sid, "say snapshot")
    backup = await server_manager.create_backup(sid)
    assert backup.size_bytes > 0

    path = server_manager.get_backup_path(sid, backup.id)
    assert path and path.exists()

    await server_manager.request_stop(sid)
    await wait_for_status(sid, {ServerStatus.OFFLINE})
    await server_manager.restore_backup(sid, backup.id)
    assert (server_manager.get_server_dir(sid) / "world").exists()


@pytest.mark.asyncio
async def test_start_without_eula_rejected():
    row = server_manager.create_server(
        owner_id="test_owner", name="Eula Check", software="vanilla", mc_version="1.21.4", eula_accepted=True
    )
    try:
        with get_db() as db:
            dbrow = db.query(DBServer).filter(DBServer.id == row.id).first()
            dbrow.eula_accepted = False
        with pytest.raises(ValueError):
            await server_manager.request_start(row.id)
    finally:
        await server_manager.delete_server(row.id)


# ----------------------------------------------------------------- API tests
@pytest.mark.asyncio
async def test_api_server_flow():
    from tests.utils import make_auth_client
    ac = await make_auth_client()
    # Catalog is public
    resp = await ac.get("/api/host/catalog")
    assert resp.status_code == 200
    assert "paper" in resp.json()["software"]

    # Unauthenticated requests are rejected before any data is touched
    bare = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    assert (await bare.get("/api/servers")).status_code == 401
    await bare.aclose()

    # Create
    resp = await ac.post("/api/servers", json={
        "name": "API Test Server", "software": "fabric", "mc_version": "1.21.4", "eula_accepted": True
    })
    assert resp.status_code == 200
    server = resp.json()
    sid = server["id"]
    assert server["status"] == "offline"

    # Duplicate EULA rejection
    resp = await ac.post("/api/servers", json={"name": "No EULA", "eula_accepted": False})
    assert resp.status_code == 400

    # Start and wait for online
    resp = await ac.post(f"/api/servers/{sid}/start")
    assert resp.status_code == 200
    assert resp.json()["queue_position"] >= 1
    assert await wait_for_status(sid, {ServerStatus.ONLINE}) == ServerStatus.ONLINE

    # Console and command
    resp = await ac.get(f"/api/servers/{sid}/console")
    assert resp.status_code == 200
    assert any("Done" in line for line in resp.json()["lines"])
    resp = await ac.post(f"/api/servers/{sid}/command", json={"command": "say api works"})
    assert resp.status_code == 200
    assert any("api works" in line for line in resp.json()["output"])

    # Players API
    resp = await ac.post(f"/api/servers/{sid}/players", json={"kind": "bans", "action": "add", "player": "Griefer"})
    assert resp.status_code == 200
    resp = await ac.get(f"/api/servers/{sid}/players", params={"kind": "bans"})
    assert [p["name"] for p in resp.json()["players"]] == ["Griefer"]

    # Properties API
    resp = await ac.put(f"/api/servers/{sid}/properties", json={"properties": {"difficulty": "hard"}})
    assert resp.status_code == 200
    # Form inputs arrive as strings — numeric properties must coerce (UPG regression)
    resp = await ac.put(f"/api/servers/{sid}/properties", json={"properties": {"max-players": "42"}})
    assert resp.status_code == 200
    assert (await ac.get(f"/api/servers/{sid}/properties")).json()["max-players"] == "42"
    resp = await ac.put(f"/api/servers/{sid}/properties", json={"properties": {"max-players": "99999"}})
    assert resp.status_code == 400
    resp = await ac.put(f"/api/servers/{sid}/properties", json={"properties": {"hacked-key": "x"}})
    assert resp.status_code == 400

    # Backups API
    resp = await ac.post(f"/api/servers/{sid}/backups")
    assert resp.status_code == 200
    backup_id = resp.json()["backup"]["id"]
    resp = await ac.get(f"/api/servers/{sid}/backups/{backup_id}/download")
    assert resp.status_code == 200

    # Files API (safe listing)
    resp = await ac.get(f"/api/servers/{sid}/files")
    assert resp.status_code == 200
    assert {"server.properties", "eula.txt"} <= {f["name"] for f in resp.json() if not f["is_dir"]}

    # Stop via API
    resp = await ac.post(f"/api/servers/{sid}/stop")
    assert resp.status_code == 200
    assert await wait_for_status(sid, {ServerStatus.OFFLINE}) == ServerStatus.OFFLINE

    # Restore while offline
    resp = await ac.post(f"/api/servers/{sid}/backups/{backup_id}/restore")
    assert resp.status_code == 200

    # Server page renders
    resp = await ac.get(f"/servers/{sid}")
    assert resp.status_code == 200
    assert "API Test Server" in resp.text

    # Delete via API
    resp = await ac.delete(f"/api/servers/{sid}")
    assert resp.status_code == 200
    resp = await ac.get(f"/api/servers/{sid}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_api_server_404s():
    from tests.utils import make_auth_client
    # Unauthenticated access gets 401 (never leaks existence)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as bare:
        assert (await bare.get("/api/servers/does_not_exist")).status_code == 401
    # Authenticated access to a missing server gets 404
    ac = await make_auth_client()
    assert (await ac.get("/api/servers/does_not_exist")).status_code == 404
    assert (await ac.post("/api/servers/does_not_exist/start")).status_code == 404
    assert (await ac.get("/servers/does_not_exist")).status_code == 404
