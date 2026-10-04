"""SQLAlchemy database models for Cyber Minecraft AI Mod Builder."""
from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(String(64), primary_key=True)  # Telegram user ID or internal ID
    username = Column(String(64), nullable=True)
    first_name = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    settings_json = Column(Text, default="{}")
    
    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")

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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
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
    created_at = Column(DateTime, default=datetime.utcnow)
    
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
    created_at = Column(DateTime, default=datetime.utcnow)
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
    created_at = Column(DateTime, default=datetime.utcnow)
    
    project = relationship("Project", back_populates="assets")

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(String(64), nullable=True)
    user_id = Column(String(64), nullable=False)
    role = Column(String(32), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class AppSetting(Base):
    __tablename__ = "settings"
    
    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
