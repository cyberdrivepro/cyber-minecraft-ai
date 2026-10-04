"""Tests for FastAPI endpoints and health check."""
import pytest
from httpx import AsyncClient, ASGITransport
from app import app

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
async def test_dashboard_page():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/")
        assert resp.status_code == 200
        assert "CYBER MINECRAFT AI" in resp.text
        assert "CONTROL PANEL" in resp.text

@pytest.mark.asyncio
async def test_api_projects_and_system():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp_proj = await ac.get("/api/projects")
        assert resp_proj.status_code == 200
        assert isinstance(resp_proj.json(), list)

        resp_sys = await ac.get("/api/system")
        assert resp_sys.status_code == 200
        sys_data = resp_sys.json()
        assert "cpu_percent" in sys_data
        assert "ram_total_mb" in sys_data
