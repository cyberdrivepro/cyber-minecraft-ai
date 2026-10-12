"""SQLAlchemy database models for Cyber Minecraft AI Mod Builder."""
from typing import Optional
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Index
from sqlalchemy.orm import declarative_base, relationship

from core.clock import utcnow

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(String(64), primary_key=True)  # Telegram user ID or internal ID
    username = Column(String(64), nullable=True, unique=True)
    first_name = Column(String(128), nullable=True)
    password_hash = Column(String(256), nullable=True)  # pbkdf2 hash; NULL for bot-only accounts
    role = Column(String(32), default="user")  # admin, user
    telegram_linked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    last_active = Column(DateTime, default=utcnow, onupdate=utcnow)
    settings_json = Column(Text, default="{}")
    
    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    """Persistent login session (cookie token -> user)."""
    __tablename__ = "user_sessions"
    
    token = Column(String(64), primary_key=True)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=False)
    user_agent = Column(String(256), nullable=True)
    
    user = relationship("User", back_populates="sessions")


class ServerShare(Base):
    """Grant another user access to a server with a role (viewer, moderator, admin)."""
    __tablename__ = "server_shares"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(String(64), ForeignKey("servers.id"), nullable=False)
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False)
    role = Column(String(32), default="viewer")  # viewer, moderator, admin
    granted_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utcnow)


class DownloadToken(Base):
    """Secure, expiring, revocable token for private artifact/backup downloads."""
    __tablename__ = "download_tokens"
    
    token = Column(String(64), primary_key=True)
    kind = Column(String(32), nullable=False)  # backup, artifact, world
    server_id = Column(String(64), nullable=True)
    user_id = Column(String(64), nullable=False)  # owner who created the link
    target = Column(String(512), nullable=False)  # opaque target reference
    max_downloads = Column(Integer, nullable=True)
    download_count = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)


class Schedule(Base):
    """Durable scheduled task attached to a server (backup, restart, command, ...)."""
    __tablename__ = "schedules"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(String(64), ForeignKey("servers.id"), nullable=False)
    name = Column(String(128), nullable=False)
    action = Column(String(32), nullable=False)  # backup, restart, stop, start, command, save
    payload = Column(String(256), nullable=True)  # e.g. command text
    interval_minutes = Column(Integer, nullable=True)  # recurring every N minutes
    daily_time = Column(String(5), nullable=True)  # "HH:MM" server-local daily schedule
    enabled = Column(Boolean, default=True)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    
    runs = relationship("ScheduleRun", back_populates="schedule", cascade="all, delete-orphan")


class ScheduleRun(Base):
    """Execution history entry for a schedule."""
    __tablename__ = "schedule_runs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    schedule_id = Column(Integer, ForeignKey("schedules.id"), nullable=False)
    status = Column(String(32), default="running")  # running, success, failed, skipped
    detail = Column(Text, nullable=True)
    started_at = Column(DateTime, default=utcnow)
    finished_at = Column(DateTime, nullable=True)
    
    schedule = relationship("Schedule", back_populates="runs")


class AuditEvent(Base):
    """Security-relevant action audit trail."""
    __tablename__ = "audit_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=True)
    action = Column(String(64), nullable=False)
    target = Column(String(256), nullable=True)
    detail = Column(String(512), nullable=True)
    ip = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utcnow)

class Project(Base):
    __tablename__ = "projects"
    
    id = Column(String(64), primary_key=True)  # UUID or clean slug
    user_id = Column(String(64), ForeignKey("users.id"), nullable=False)
    name = Column(String(128), nullable=False)
    namespace = Column(String(64), nullable=False)
    edition = Column(String(32), default="bedrock")  # "bedrock" or "fabric"
    description = Column(Text, nullable=True)
    current_version = Column(Integer, default=1)
    status = Column(String(32), default="draft")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    
    user = relationship("User", back_populates="projects")
    versions = relationship("ProjectVersion", back_populates="project", cascade="all, delete-orphan")
    jobs = relationship("BuildJob", back_populates="project", cascade="all, delete-orphan")
    assets = relationship("Asset", back_populates="project", cascade="all, delete-orphan")

class ProjectVersion(Base):
    __tablename__ = "project_versions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    spec_json = Column(Text, nullable=False)  # Serialized ProjectSpec JSON
    change_summary = Column(String(256), default="Initial generation")
    build_status = Column(String(32), default="unbuilt")
    artifact_path = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    
    project = relationship("Project", back_populates="versions")

class BuildJob(Base):
    __tablename__ = "build_jobs"
    
    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False)
    version_number = Column(Integer, nullable=False)
    status = Column(String(32), default="queued")  # queued, planning, generating, validating, building, repairing, completed, failed, cancelled
    logs = Column(Text, default="")
    error_message = Column(Text, nullable=True)
    repair_attempts = Column(Integer, default=0)
    artifact_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    project = relationship("Project", back_populates="jobs")

class Asset(Base):
    __tablename__ = "assets"
    
    id = Column(String(64), primary_key=True)
    project_id = Column(String(64), ForeignKey("projects.id"), nullable=False)
    asset_type = Column(String(32), nullable=False)  # texture, model, sound, reference
    filename = Column(String(128), nullable=False)
    file_path = Column(String(512), nullable=False)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=utcnow)
    
    project = relationship("Project", back_populates="assets")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(64), nullable=True)
    user_id = Column(String(64), nullable=False)
    role = Column(String(32), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)

class AppSetting(Base):
    __tablename__ = "settings"
    
    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

class Server(Base):
    __tablename__ = "servers"
    
    id = Column(String(64), primary_key=True)
    owner_id = Column(String(64), nullable=False, default="web_admin")
    name = Column(String(128), nullable=False)
    description = Column(String(256), nullable=True)
    software = Column(String(32), nullable=False, default="paper")  # paper, vanilla, fabric, forge, bedrock
    mc_version = Column(String(32), nullable=False, default="1.21.4")
    status = Column(String(32), default="offline")  # offline, queued, preparing, starting, online, stopping, error
    status_detail = Column(String(256), default="Server is offline")
    address = Column(String(256), nullable=True)
    port = Column(Integer, nullable=True)
    eula_accepted = Column(Boolean, default=False)
    motd = Column(String(128), default="A Cyber Host server")
    gamemode = Column(String(32), default="survival")
    difficulty = Column(String(32), default="normal")
    max_players = Column(Integer, default=20)
    level_seed = Column(String(64), nullable=True)
    pvp = Column(Boolean, default=True)
    whitelist_enabled = Column(Boolean, default=False)
    world_name = Column(String(64), default="world")
    ram_mb = Column(Integer, default=1024)
    auto_backup = Column(Boolean, default=True)
    jar_ready = Column(Boolean, default=False)
    playtime_seconds = Column(Integer, default=0)
    last_started = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    
    backups = relationship("ServerBackup", back_populates="server", cascade="all, delete-orphan")

Index("ix_servers_owner", Server.owner_id)
Index("ix_servers_status", Server.status)
Index("ix_schedule_runs_schedule", ScheduleRun.schedule_id)
Index("ix_audit_created", AuditEvent.created_at)

class ServerBackup(Base):
    __tablename__ = "server_backups"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    server_id = Column(String(64), ForeignKey("servers.id"), nullable=False)
    filename = Column(String(256), nullable=False)
    size_bytes = Column(Integer, default=0)
    kind = Column(String(32), default="manual")  # manual, auto
    created_at = Column(DateTime, default=utcnow)
    
    server = relationship("Server", back_populates="backups")
