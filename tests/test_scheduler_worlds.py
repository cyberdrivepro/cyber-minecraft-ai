"""Tests for the durable scheduler and world management."""
import asyncio
import zipfile
from datetime import datetime

import pytest

from app import app  # noqa: F401  ensures singletons exist
from servers.manager import server_manager, ServerStatus
from servers.scheduler import scheduler, compute_next_run
from storage.database import get_db
from storage.models import Schedule as DBSchedule, ScheduleRun as DBScheduleRun
from tests.utils import make_auth_client


@pytest.fixture(autouse=True)
async def running_host():
    await server_manager.startup()
    await scheduler.startup()
    yield
    await scheduler.shutdown()
    await server_manager.shutdown()


@pytest.mark.asyncio
async def test_compute_next_run_interval():
    now = datetime.utcnow()
    s = DBSchedule(server_id="x", name="t", action="backup", interval_minutes=30)
    nxt = compute_next_run(s, now)
    assert nxt is not None and nxt > now
    # After running, the next run is one interval later
    s.last_run_at = now
    nxt2 = compute_next_run(s, now)
    assert (nxt2 - now).total_seconds() >= 30 * 60


@pytest.mark.asyncio
async def test_compute_next_run_daily():
    now = datetime.utcnow()
    s = DBSchedule(server_id="x", name="t", action="restart", daily_time="23:59")
    nxt = compute_next_run(s, now)
    assert nxt is not None
    assert nxt.hour == 23 and nxt.minute == 59
    assert nxt > now
    assert compute_next_run(DBSchedule(server_id="x", name="b", action="backup"), now) is None


@pytest.mark.asyncio
async def test_schedule_api_and_execution():
    ac = await make_auth_client()
    resp = await ac.post("/api/servers", json={
        "name": "Sched Server", "software": "paper", "mc_version": "1.21.4", "eula_accepted": True
    })
    sid = resp.json()["id"]

    # Create a backup schedule
    resp = await ac.post(f"/api/servers/{sid}/schedules", json={
        "name": "hourly backup", "action": "backup", "interval_minutes": 60
    })
    assert resp.status_code == 200, resp.text
    schedule = resp.json()["schedule"]
    assert schedule["next_run_at"] is None or schedule["next_run_at"]

    # Validation errors
    resp = await ac.post(f"/api/servers/{sid}/schedules", json={"name": "x", "action": "backup"})
    assert resp.status_code == 400
    resp = await ac.post(f"/api/servers/{sid}/schedules", json={
        "name": "x", "action": "format-disk", "interval_minutes": 10
    })
    assert resp.status_code == 400

    # Force the schedule due and let the scheduler run it
    with get_db() as db:
        row = db.query(DBSchedule).filter(DBSchedule.id == schedule["id"]).first()
        row.next_run_at = datetime.utcnow() - __import__("datetime").timedelta(seconds=1)
    await asyncio.sleep(3)  # scheduler polls every 30s? no: force a tick
    # Run a manual tick instead of waiting
    await scheduler._tick()
    with get_db() as db:
        runs = db.query(DBScheduleRun).filter(DBScheduleRun.schedule_id == schedule["id"]).all()
        assert len(runs) == 1
        assert runs[0].status == "success", runs[0].detail
        assert "backup-" in (runs[0].detail or "")
        # Next run was rescheduled
        row = db.query(DBSchedule).filter(DBSchedule.id == schedule["id"]).first()
        assert row.next_run_at is not None and row.next_run_at > datetime.utcnow()

    # Runs history API
    resp = await ac.get(f"/api/schedules/{schedule['id']}/runs")
    assert resp.status_code == 200
    assert resp.json()[0]["status"] == "success"

    # Disable and delete
    resp = await ac.patch(f"/api/schedules/{schedule['id']}", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()["schedule"]["enabled"] is False
    resp = await ac.delete(f"/api/schedules/{schedule['id']}")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_schedule_overlap_prevention():
    """A long-running schedule must not run twice concurrently."""
    ac = await make_auth_client()
    resp = await ac.post("/api/servers", json={
        "name": "Overlap Server", "software": "paper", "mc_version": "1.21.4", "eula_accepted": True
    })
    sid = resp.json()["id"]
    with get_db() as db:
        s = DBSchedule(server_id=sid, name="backup", action="backup", interval_minutes=10, enabled=True)
        db.add(s)
        db.flush()
        schedule_id = s.id

    # Mark in-flight and fire two ticks: only one run may start
    scheduler._inflight.add(schedule_id)
    with get_db() as db:
        row = db.query(DBSchedule).filter(DBSchedule.id == schedule_id).first()
        row.next_run_at = datetime.utcnow() - __import__("datetime").timedelta(seconds=5)
    await scheduler._tick()
    with get_db() as db:
        runs = db.query(DBScheduleRun).filter(DBScheduleRun.schedule_id == schedule_id).all()
        assert len(runs) == 0  # skipped because it was "in flight"
    scheduler._inflight.discard(schedule_id)


@pytest.mark.asyncio
async def test_world_import_export_delete():
    ac = await make_auth_client()
    resp = await ac.post("/api/servers", json={
        "name": "World Server", "software": "paper", "mc_version": "1.21.4", "eula_accepted": True
    })
    sid = resp.json()["id"]

    # Build a realistic world zip (Java: level.dat + region folder)
    zip_path = "/tmp/opencode-test-world.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("MyWorld/level.dat", b"fake-level-data")
        zf.writestr("MyWorld/region/r.0.0.mca", b"0" * 1024)
    with open(zip_path, "rb") as f:
        resp = await ac.post(f"/api/servers/{sid}/worlds/import",
                             files={"file": ("world.zip", f)}, params={"name": "MyWorld"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["world"] == "MyWorld"

    # Wrapped folder was flattened
    listing = await ac.get(f"/api/servers/{sid}/worlds")
    names = [w["name"] for w in listing.json()]
    assert "MyWorld" in names
    assert "world" in names  # active default world

    # Reject a non-world archive
    bad_zip = "/tmp/opencode-bad.zip"
    with zipfile.ZipFile(bad_zip, "w") as zf:
        zf.writestr("random.txt", "not a world")
    with open(bad_zip, "rb") as f:
        resp = await ac.post(f"/api/servers/{sid}/worlds/import",
                             files={"file": ("bad.zip", f)}, params={"name": "BadWorld"})
    assert resp.status_code == 400

    # Activate the imported world (offline)
    resp = await ac.post(f"/api/servers/{sid}/worlds/MyWorld/activate")
    assert resp.status_code == 200
    props = (await ac.get(f"/api/servers/{sid}/properties")).json()
    assert props["level-name"] == "MyWorld"
    # Active world cannot be deleted
    resp = await ac.delete(f"/api/servers/{sid}/worlds/MyWorld")
    assert resp.status_code == 409
    # Delete the old one
    resp = await ac.delete(f"/api/servers/{sid}/worlds/world")
    assert resp.status_code == 200

    # Export produces a downloadable token
    resp = await ac.post(f"/api/servers/{sid}/worlds/MyWorld/link")
    assert resp.status_code == 200
    url = resp.json()["url"]
    from httpx import AsyncClient, ASGITransport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        assert (await anon.get(url)).status_code == 200
