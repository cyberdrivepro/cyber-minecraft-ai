"""Tests for FastAPI endpoints and health check."""
import pytest
from httpx import AsyncClient, ASGITransport
from app import app
from tests.utils import make_auth_client

@pytest.mark.asyncio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded")
        assert "ai" in data
        assert "queue" in data
        assert data["database"] is True

@pytest.mark.asyncio
async def test_dashboard_requires_auth_and_renders():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Unauthenticated access is redirected to the login page
        resp = await ac.get("/", follow_redirects=False)
        assert resp.status_code == 303
        assert "/login" in resp.headers["location"]

        # After login the dashboard renders
        ac = await make_auth_client()
        resp = await ac.get("/")
        assert resp.status_code == 200
        assert "CYBER MINECRAFT AI" in resp.text

@pytest.mark.asyncio
async def test_api_projects_and_system():
    ac = await make_auth_client()
    resp_proj = await ac.get("/api/projects")
    assert resp_proj.status_code == 200
    assert isinstance(resp_proj.json(), list)

    resp_sys = await ac.get("/api/system")
    assert resp_sys.status_code == 200
    sys_data = resp_sys.json()
    assert "cpu_percent" in sys_data
    assert "ram_total_mb" in sys_data

@pytest.mark.asyncio
async def test_auth_flow_rejects_bad_credentials():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/auth/login", json={"username": "ghost", "password": "wrong-pass"})
        assert resp.status_code == 401
        # Weak passwords rejected at registration
        resp = await ac.post("/api/auth/register", json={"username": "weakpw", "password": "short"})
        assert resp.status_code == 400
