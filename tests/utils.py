"""Shared test helpers: authenticated API clients."""
import uuid

from httpx import AsyncClient, ASGITransport

from app import app

async def make_auth_client(base_url: str = "http://test", role: str = "user") -> AsyncClient:
    """Create an AsyncClient with a registered, logged-in user session cookie.

    Registration goes through the real auth API so the flow itself is exercised.
    """
    username = f"tester_{role}_{uuid.uuid4().hex[:8]}"
    transport = ASGITransport(app=app)
    ac = AsyncClient(transport=transport, base_url=base_url)
    resp = await ac.post("/api/auth/register", json={
        "username": username, "password": "correct-horse-battery", "first_name": "Test"
    })
    if resp.status_code == 200 and role == "admin":
        # Promote via direct DB (admin bootstrap API requires an admin already).
        from storage.database import get_db
        from storage.models import User as DBUser
        with get_db() as db:
            row = db.query(DBUser).filter(DBUser.username == username).first()
            row.role = "admin"
    assert resp.status_code == 200, f"registration failed: {resp.text}"
    assert "cyber_session" in resp.cookies
    return ac
