"""Tests for multi-user authorization, server isolation, and download tokens."""
import time

import pytest
from httpx import AsyncClient, ASGITransport

from app import app
from tests.utils import make_auth_client
from core import tokens as download_tokens


@pytest.mark.asyncio
async def test_users_cannot_access_each_others_servers():
    owner = await make_auth_client()
    intruder = await make_auth_client()
    resp = await owner.post("/api/servers", json={
        "name": "Private Server", "software": "paper", "mc_version": "1.21.4", "eula_accepted": True
    })
    assert resp.status_code == 200, resp.text
    sid = resp.json()["id"]

    # The intruder cannot see, start, read console, or delete the server
    listing = (await intruder.get("/api/servers")).json()
    assert sid not in [s["id"] for s in listing]
    assert (await intruder.get(f"/api/servers/{sid}")).status_code == 404
    assert (await intruder.get(f"/api/servers/{sid}/console")).status_code == 404
    assert (await intruder.post(f"/api/servers/{sid}/start")).status_code == 404
    assert (await intruder.delete(f"/api/servers/{sid}")).status_code == 404
    assert (await intruder.get(f"/api/servers/{sid}/backups")).status_code == 404

    # Owner can see it
    assert (await owner.get(f"/api/servers/{sid}")).status_code == 200


@pytest.mark.asyncio
async def test_sharing_grants_scoped_access():
    owner = await make_auth_client()
    friend = await make_auth_client()
    resp = await owner.post("/api/servers", json={
        "name": "Shared Server", "software": "paper", "mc_version": "1.21.4", "eula_accepted": True
    })
    assert resp.status_code == 200, resp.text
    sid = resp.json()["id"]

    # Share with the friend's account
    users = (await owner.get("/api/admin/users")).status_code  # not an admin; expect 404
    assert users == 404
    # Find friend's username through their own /api/auth/me
    me = (await friend.get("/api/auth/me")).json()
    resp = await owner.post(f"/api/servers/{sid}/shares", json={
        "username": me["username"], "role": "moderator"
    })
    assert resp.status_code == 200, resp.text

    # Friend now has moderator access: can read and command, cannot delete
    assert (await friend.get(f"/api/servers/{sid}")).status_code == 200
    assert sid in [s["id"] for s in (await friend.get("/api/servers")).json()]
    assert (await friend.delete(f"/api/servers/{sid}")).status_code == 404
    # Moderators cannot edit properties (admin-level)
    assert (await friend.put(f"/api/servers/{sid}/properties", json={"properties": {"motd": "x"}})).status_code == 404

    # Only the owner can manage shares
    resp = await friend.post(f"/api/servers/{sid}/shares", json={"username": "x", "role": "viewer"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_tokens_expire_and_revoke(tmp_path):
    from datetime import datetime, timedelta
    owner = await make_auth_client()
    intruder = await make_auth_client()

    secret = tmp_path / "artifact.zip"
    secret.write_bytes(b"PK\x03\x04 secret artifact")

    token = download_tokens.create_token("someone", "backup", str(secret), ttl_hours=1)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as anon:
        resp = await anon.get(f"/api/dl/{token}")
        assert resp.status_code == 200
        assert resp.content == secret.read_bytes()
        # Invalid tokens get 404
        assert (await anon.get("/api/dl/not-a-real-token")).status_code == 404

    # Revocation by a non-owner fails; by the owner succeeds
    with pytest.raises(Exception):
        download_tokens.revoke_token(token, intruder.id)
    assert download_tokens.revoke_token(token, "someone") is True
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        assert (await anon.get(f"/api/dl/{token}")).status_code == 404


@pytest.mark.asyncio
async def test_download_token_download_limit():
    secret_path = "/tmp/opencode-limit-test.txt"
    from pathlib import Path
    Path(secret_path).write_text("limited")
    token = download_tokens.create_token("someone", "world", secret_path, max_downloads=2, ttl_hours=1)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as anon:
        assert (await anon.get(f"/api/dl/{token}")).status_code == 200
        assert (await anon.get(f"/api/dl/{token}")).status_code == 200
        assert (await anon.get(f"/api/dl/{token}")).status_code == 404  # limit reached
    Path(secret_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_artifact_download_isolated_per_user():
    owner = await make_auth_client()
    intruder = await make_auth_client()
    # Artifacts of another user must 404, not leak content
    owner_id = (await owner.get("/api/auth/me")).json()["id"]
    resp = await intruder.get(f"/api/download/{owner_id}/some-project/1")
    assert resp.status_code == 404
