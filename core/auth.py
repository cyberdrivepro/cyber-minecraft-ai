"""Authentication, sessions, permissions, and audit logging for the web platform.

Passwords use PBKDF2-HMAC-SHA256 (hashlib standard library). Sessions are
opaque random tokens stored server-side and delivered as HttpOnly cookies.
All permission checks happen here so API routes can share one enforcement path.
"""
import hashlib
import hmac
import secrets
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from core.clock import utcnow

from fastapi import Request, HTTPException

from config import settings
from storage.database import get_db
from storage.models import User, UserSession, ServerShare, Server, AuditEvent
from logger import get_logger

logger = get_logger("auth")


@dataclass
class ServiceAccount:
    """Synthetic platform-admin identity for trusted local tooling (CLI)."""
    id: str = "cli_admin"
    username: str = "cli"
    role: str = "admin"

SESSION_COOKIE = "cyber_session"
SESSION_TTL_HOURS = 24 * 7
PBKDF2_ITERATIONS = 120_000


def get_current_user(request: Request) -> Optional[User]:
    """FastAPI dependency: resolve the logged-in user (or None when signed out)."""
    return session_user_from_request(request)


def require_user(request: Request) -> User:
    """FastAPI dependency: demand an authenticated account (session or CLI token).

    When AUTH_REQUIRED is disabled (private single-user installs), anonymous
    requests act as a platform-admin service account.
    """
    cli_token = request.headers.get("x-admin-token", "")
    if cli_token and hmac.compare_digest(cli_token, settings.ADMIN_TOKEN):
        return ServiceAccount()  # type: ignore[return-value]
    user = session_user_from_request(request)
    if user is None:
        if not settings.AUTH_REQUIRED:
            return ServiceAccount()  # type: ignore[return-value]
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


# Simple in-memory login rate limiting: {key: [timestamps]}
_login_attempts: dict = {}
MAX_LOGIN_ATTEMPTS = 10
LOGIN_WINDOW_MINUTES = 15

ROLE_LEVELS = {"viewer": 0, "moderator": 1, "admin": 2, "owner": 3}


# ------------------------------------------------------------------ passwords
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return f"pbkdf2${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    try:
        _, iterations, salt, hexdigest = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(digest.hex(), hexdigest)
    except (ValueError, TypeError):
        return False


# ------------------------------------------------------------------- sessions
def create_session(user_id: str, user_agent: str = "") -> str:
    token = secrets.token_urlsafe(32)
    with get_db() as db:
        db.add(UserSession(
            token=token,
            user_id=user_id,
            expires_at=utcnow() + timedelta(hours=SESSION_TTL_HOURS),
            user_agent=(user_agent or "")[:256],
        ))
    return token


def destroy_session(token: str) -> None:
    with get_db() as db:
        row = db.query(UserSession).filter(UserSession.token == token).first()
        if row:
            db.delete(row)


def get_session_user(token: Optional[str]) -> Optional[User]:
    """Resolve a session token to its user, enforcing expiry."""
    if not token:
        return None
    with get_db() as db:
        sess = db.query(UserSession).filter(UserSession.token == token).first()
        if not sess or sess.expires_at < utcnow():
            return None
        user = db.query(User).filter(User.id == sess.user_id).first()
        return user


def session_user_from_request(request: Request) -> Optional[User]:
    return get_session_user(request.cookies.get(SESSION_COOKIE))


def login_rate_limited(key: str) -> bool:
    """True when the key exceeded MAX_LOGIN_ATTEMPTS inside the window."""
    now = utcnow()
    recent = [t for t in _login_attempts.get(key, []) if now - t < timedelta(minutes=LOGIN_WINDOW_MINUTES)]
    _login_attempts[key] = recent
    return len(recent) >= MAX_LOGIN_ATTEMPTS


def record_login_attempt(key: str) -> None:
    now = utcnow()
    # Prune stale keys so the map cannot grow without bound.
    stale = [k for k, ts in _login_attempts.items()
             if all(now - t >= timedelta(minutes=LOGIN_WINDOW_MINUTES) for t in ts)]
    for k in stale:
        _login_attempts.pop(k, None)
    _login_attempts.setdefault(key, []).append(now)


# --------------------------------------------------------------------- users
def get_or_create_user(user_id: str, username: str = "", first_name: str = "") -> User:
    with get_db() as db:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            return user
        user = User(id=user_id, username=username or None, first_name=first_name or None, role="user")
        db.add(user)
        return user


def register_user(username: str, password: str, first_name: str = "") -> User:
    """Create a dashboard account with a hashed password."""
    username = (username or "").strip().lower()
    if not (3 <= len(username) <= 32) or not username.replace("_", "").replace("-", "").isalnum():
        raise ValueError("Username must be 3-32 letters, digits, dashes or underscores.")
    if len(password or "") < 8:
        raise ValueError("Password must be at least 8 characters.")
    with get_db() as db:
        if db.query(User).filter(User.username == username).first():
            raise ValueError("That username is already taken.")
        user = User(
            id=f"usr_{secrets.token_hex(8)}",
            username=username,
            first_name=(first_name or username)[:128],
            password_hash=hash_password(password),
            role="user",
        )
        db.add(user)
        db.flush()
        db.refresh(user)
        return user


def authenticate(username: str, password: str) -> Optional[User]:
    """Verify credentials. Returns the user or None."""
    username = (username or "").strip().lower()
    with get_db() as db:
        user = db.query(User).filter(User.username == username).first()
        if not user or not verify_password(password, user.password_hash):
            return None
        db.refresh(user)
        return user


def bootstrap_admin() -> Optional[User]:
    """Ensure an initial admin account exists.

    Uses ADMIN_USERNAME/ADMIN_PASSWORD from the environment when provided;
    otherwise creates user 'admin' with a generated password stored in
    DATA_DIR/admin_credentials.txt (written once, readable only by the owner).
    """
    with get_db() as db:
        if db.query(User).filter(User.role == "admin").first():
            return None
    username = (getattr(settings, "ADMIN_USERNAME", None) or "admin").lower()
    password = getattr(settings, "ADMIN_PASSWORD", None) or secrets.token_urlsafe(12)
    try:
        user = register_user(username, password, first_name="Administrator")
    except ValueError:
        # Username collision on a non-admin row: promote it instead of failing.
        with get_db() as db:
            user = db.query(User).filter(User.username == username).first()
            if user:
                user.password_hash = hash_password(password)
                user.role = "admin"
            return user
    with get_db() as db:
        user = db.query(User).filter(User.id == user.id).first()
        user.role = "admin"
    if not getattr(settings, "ADMIN_PASSWORD", None):
        cred_file = settings.DATA_DIR / "admin_credentials.txt"
        if not cred_file.exists():
            cred_file.write_text(
                f"username: {username}\npassword: {password}\n"
                "Keep this file private. Delete it after saving the password.\n",
                encoding="utf-8",
            )
            try:
                cred_file.chmod(0o600)
            except OSError:
                pass
        logger.warning(f"Bootstrap admin created. Credentials written to {cred_file}")
    else:
        logger.info(f"Bootstrap admin '{username}' created from environment configuration.")
    return user


# ---------------------------------------------------------------- permissions
def server_role(user: Optional[User], server_id: str) -> Optional[str]:
    """Return the user's effective role on a server: owner, admin/share role, or None."""
    if user is None:
        return None
    if user.role == "admin":
        return "owner"  # platform admins may manage any server (audited)
    with get_db() as db:
        row = db.query(Server).filter(Server.id == server_id).first()
        if row and row.owner_id == user.id:
            return "owner"
        share = db.query(ServerShare).filter(
            ServerShare.server_id == server_id, ServerShare.user_id == user.id
        ).first()
        return share.role if share else None


def require_server_access(user: Optional[User], server_id: str, minimum: str = "viewer") -> str:
    """Raise 404 (not 403, to avoid leaking existence) unless the role is sufficient."""
    role = server_role(user, server_id)
    if role is None or ROLE_LEVELS.get(role, -1) < ROLE_LEVELS.get(minimum, 0):
        raise HTTPException(status_code=404, detail="Server not found")
    return role


def require_admin(request: Request) -> User:
    """FastAPI dependency: demand a platform-admin session (or CLI token)."""
    cli_token = request.headers.get("x-admin-token", "")
    if cli_token and hmac.compare_digest(cli_token, settings.ADMIN_TOKEN):
        return ServiceAccount()  # type: ignore[return-value]
    user = session_user_from_request(request)
    if user is None or user.role != "admin":
        raise HTTPException(status_code=404, detail="Not found")
    return user


# ---------------------------------------------------------------------- audit
def audit(user_id: Optional[str], action: str, target: str = "", detail: str = "", ip: str = "") -> None:
    """Persist a security-relevant event; never raises into the caller."""
    try:
        with get_db() as db:
            db.add(AuditEvent(
                user_id=user_id, action=action[:64], target=target[:256],
                detail=detail[:512], ip=(ip or "")[:64],
            ))
    except Exception as e:
        logger.warning(f"Audit write failed for {action}: {e}")
