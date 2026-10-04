"""Central configuration for Cyber Minecraft AI Mod Builder."""
import os
import secrets
from pathlib import Path
from typing import Optional, Literal

try:
    from pydantic_settings import BaseSettings
    _has_pydantic_settings = True
except ImportError:
    from pydantic import BaseModel
    BaseSettings = BaseModel  # type: ignore
    _has_pydantic_settings = False

def _load_env_file(filepath: Path) -> None:
    """Simple parser for .env files without requiring external packages."""
    if not filepath.exists():
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip("'\"")
            if k and k not in os.environ:
                os.environ[k] = v

# Load .env if present
_env_path = Path(".env").resolve()
_load_env_file(_env_path)

class Settings(BaseSettings):
    APP_NAME: str = "CYBER MINECRAFT AI MOD BUILDER"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.environ.get("DEBUG", "false").lower() in ("true", "1")
    
    # Server / Hugging Face configuration
    HOST: str = os.environ.get("HOST", "0.0.0.0")
    PORT: int = int(os.environ.get("PORT", "7860"))
    PUBLIC_BASE_URL: Optional[str] = os.environ.get("PUBLIC_BASE_URL", None)
    
    # Telegram Bot
    TELEGRAM_BOT_TOKEN: Optional[str] = os.environ.get("TELEGRAM_BOT_TOKEN", None)
    
    # Hugging Face & AI Settings
    HF_TOKEN: Optional[str] = os.environ.get("HF_TOKEN", None)
    AI_PROVIDER: str = os.environ.get("AI_PROVIDER", "local")
    LOCAL_MODEL_ID: str = os.environ.get("LOCAL_MODEL_ID", "Qwen/Qwen2.5-Coder-1.5B-Instruct")
    AUTO_MODEL: bool = os.environ.get("AUTO_MODEL", "true").lower() in ("true", "1")
    VISION_MODEL_ID: Optional[str] = os.environ.get("VISION_MODEL_ID", None)
    
    # External AI Fallback Keys
    OPENAI_API_KEY: Optional[str] = os.environ.get("OPENAI_API_KEY", None)
    GROQ_API_KEY: Optional[str] = os.environ.get("GROQ_API_KEY", None)
    OPENROUTER_API_KEY: Optional[str] = os.environ.get("OPENROUTER_API_KEY", None)
    
    # Admin Security
    ADMIN_TOKEN: str = os.environ.get("ADMIN_TOKEN", secrets.token_urlsafe(16))
    
    # Build & Repair limits
    MAX_CONCURRENT_BUILDS: int = int(os.environ.get("MAX_CONCURRENT_BUILDS", "1"))
    MAX_REPAIR_ATTEMPTS: int = int(os.environ.get("MAX_REPAIR_ATTEMPTS", "3"))
    MAX_BUILD_SECONDS: int = int(os.environ.get("MAX_BUILD_SECONDS", "180"))
    
    # Storage & Paths
    DATA_DIR: Path = Path(os.environ.get("DATA_DIR", "./data")).resolve()
    OUTPUT_DIR: Path = Path(os.environ.get("OUTPUT_DIR", "./data/outputs")).resolve()
    STORAGE_MODE: str = os.environ.get("STORAGE_MODE", "local")
    
    # Database
    DATABASE_URL: Optional[str] = os.environ.get("DATABASE_URL", None)
    
    # Logging
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")
    
    # Java environment
    JAVA_HOME: Optional[str] = os.environ.get("JAVA_HOME", None)

    def __init__(self, **data):
        super().__init__(**data)
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (self.DATA_DIR / "users").mkdir(parents=True, exist_ok=True)
        if not self.DATABASE_URL:
            db_path = (self.DATA_DIR / "cyber_mod.db").resolve()
            # Standard sqlite path format
            self.DATABASE_URL = f"sqlite:///{db_path}"

settings = Settings()
