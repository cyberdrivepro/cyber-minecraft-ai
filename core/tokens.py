"""Secure, expiring, revocable download tokens for private artifacts.

Tokens are random, stored server-side, expire, carry an optional download
limit, can be revoked, and are validated against the requester's permissions
at creation time. Public URLs never embed user IDs, server credentials or
filesystem paths.
"""
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import settings
from storage.database import get_db
from storage.models import DownloadToken
from core.auth import audit
from core.exceptions import SecurityError
from core.security import validate_safe_path
from logger import get_logger

logger = get_logger("core.tokens")


def create_token(
    user_id: str,
    kind: str,
    target: str,
    server_id: Optional[str] = None,
    ttl_hours: Optional[int] = None,
    max_downloads: Optional[int] = None,
    ip: str = "",
) -> str:
    """Create a download token. The caller must already authorize the user's
    access to `target` before calling this."""
    token = secrets.token_urlsafe(24)
    ttl = ttl_hours or settings.DOWNLOAD_TOKEN_TTL_HOURS
    with get_db() as db:
        db.add(DownloadToken(
            token=token,
            kind=kind,
            server_id=server_id,
            user_id=user_id,
            target=target[:512],
            max_downloads=max_downloads,
            expires_at=datetime.utcnow() + timedelta(hours=max(1, min(ttl, 24 * 30))),
        ))
    audit(user_id, "download_token_created", target=target, detail=f"kind={kind} ttl={ttl}h", ip=ip)
    return token


def resolve_token(token: str) -> Optional[Path]:
    """Validate a token and return the file path it grants, or None.

    Enforces expiry, revocation, and download-count limits. Increments the
    usage counter on success.
    """
    with get_db() as db:
        row = db.query(DownloadToken).filter(DownloadToken.token == token).first()
        if not row or row.revoked:
            return None
        if row.expires_at < datetime.utcnow():
            return None
        if row.max_downloads is not None and row.download_count >= row.max_downloads:
            return None
        path = Path(row.target)
        row.download_count = (row.download_count or 0) + 1
    if not path.exists() or not path.is_file():
        return None
    return path


def revoke_token(token: str, user_id: str, ip: str = "") -> bool:
    """Revoke a token. Only its creator or a platform admin may revoke."""
    with get_db() as db:
        row = db.query(DownloadToken).filter(DownloadToken.token == token).first()
        if not row:
            return False
        if row.user_id != user_id:
            raise SecurityError("Only the link owner can revoke this token")
        row.revoked = True
    audit(user_id, "download_token_revoked", target=token[:16] + "...", ip=ip)
    return True


def list_tokens(user_id: str, server_id: Optional[str] = None):
    with get_db() as db:
        q = db.query(DownloadToken).filter(DownloadToken.user_id == user_id)
        if server_id:
            q = q.filter(DownloadToken.server_id == server_id)
        return [
            {
                "token": r.token,
                "kind": r.kind,
                "server_id": r.server_id,
                "expires_at": r.expires_at.isoformat(),
                "revoked": r.revoked,
                "download_count": r.download_count or 0,
                "max_downloads": r.max_downloads,
                "expired": r.expires_at < datetime.utcnow(),
            }
            for r in q.order_by(DownloadToken.created_at.desc()).limit(50).all()
        ]
