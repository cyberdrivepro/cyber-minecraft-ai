"""Central configuration for Cyber Minecraft AI Mod Builder."""
import os
import secrets
from pathlib import Path
from typing import Optional, Literal, Dict, Any

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
    APP_NAME: str = "CYBER MINECRAFT AI"
    APP_SUBTITLE: str = "Build Mods. Host Worlds. Control Everything."
    APP_VERSION: str = "2.0.0"
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
    ADMIN_USERNAME: str = os.environ.get("ADMIN_USERNAME", "")
    ADMIN_PASSWORD: Optional[str] = os.environ.get("ADMIN_PASSWORD", None)
    
    # Web authentication (set false only for private single-user installs)
    AUTH_REQUIRED: bool = os.environ.get("AUTH_REQUIRED", "true").lower() in ("true", "1")
    ALLOW_REGISTRATION: bool = os.environ.get("ALLOW_REGISTRATION", "true").lower() in ("true", "1")
    DOWNLOAD_TOKEN_TTL_HOURS: int = int(os.environ.get("DOWNLOAD_TOKEN_TTL_HOURS", "24"))
    
    # Build & Repair limits
    MAX_CONCURRENT_BUILDS: int = int(os.environ.get("MAX_CONCURRENT_BUILDS", "1"))
    MAX_REPAIR_ATTEMPTS: int = int(os.environ.get("MAX_REPAIR_ATTEMPTS", "3"))
    MAX_BUILD_SECONDS: int = int(os.environ.get("MAX_BUILD_SECONDS", "180"))
    
    # Cyber Host (Minecraft server hosting)
    MAX_SERVERS_PER_OWNER: int = int(os.environ.get("MAX_SERVERS_PER_OWNER", "10"))
    MAX_CONCURRENT_SERVERS: int = int(os.environ.get("MAX_CONCURRENT_SERVERS", "2"))
    SERVER_PORT_MIN: int = int(os.environ.get("SERVER_PORT_MIN", "25565"))
    SERVER_PORT_MAX: int = int(os.environ.get("SERVER_PORT_MAX", "25600"))
    SERVER_RAM_MB: int = int(os.environ.get("SERVER_RAM_MB", "1024"))
    MAX_BACKUPS_PER_SERVER: int = int(os.environ.get("MAX_BACKUPS_PER_SERVER", "5"))
    SERVER_JAR_MAX_MB: int = int(os.environ.get("SERVER_JAR_MAX_MB", "300"))
    SERVER_IDLE_SHUTDOWN_MINUTES: int = int(os.environ.get("SERVER_IDLE_SHUTDOWN_MINUTES", "0"))
    SERVER_PUBLIC_HOST: Optional[str] = os.environ.get("SERVER_PUBLIC_HOST", None)
    
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
        (self.DATA_DIR / "servers").mkdir(parents=True, exist_ok=True)
        if not self.DATABASE_URL:
            db_path = (self.DATA_DIR / "cyber_mod.db").resolve()
            # Standard sqlite path format
            self.DATABASE_URL = f"sqlite:///{db_path}"

def _sw(label, versions, edition="java", java_version="21", source="", notes="", plugin_support=None, platform_support="linux, windows, docker"):
    """Catalog entry describing a server software family and its real requirements."""
    return {
        "label": label,
        "versions": versions,
        "edition": edition,
        "java_version": None if edition == "bedrock" else java_version,
        "download_source": source,
        "notes": notes,
        "plugins": plugin_support,
        "platforms": platform_support,
    }

# Supported server software catalog. Every entry documents the *real* runtime
# requirements; the platform never claims a type can run when its prerequisites
# (Java version, OS support, an uploaded binary) are missing.
SERVER_SOFTWARE: Dict[str, Any] = {
    "paper": _sw(
        "Paper (plugins)",
        ["1.21.4", "1.21.3", "1.21.1", "1.21", "1.20.6", "1.20.4", "1.20.1",
         "1.19.4", "1.18.2", "1.17.1", "1.16.5", "1.12.2", "1.8.8"],
        java_version="21", source="https://papermc.io/downloads",
        notes="Drop-in Bukkit/Spigot plugin support. Java 21 is required for 1.20.5+; "
              "1.18–1.20.4 need Java 17; 1.17 needs Java 16+; older builds run on Java 8–11. "
              "Upload the Paper jar via the server page.",
        plugin_support="bukkit plugins",
    ),
    "vanilla": _sw(
        "Vanilla",
        ["1.21.4", "1.21.3", "1.21.1", "1.21", "1.20.6", "1.20.4", "1.20.1",
         "1.19.4", "1.19.2", "1.18.2", "1.17.1", "1.16.5", "1.12.2", "1.8.9"],
        source="https://www.minecraft.net/download/server",
        notes="Official Mojang server jar. Java 21 is required for 1.20.5+; "
              "1.18–1.20.4 need Java 17+; 1.17 needs Java 16+; older builds run on Java 8+. "
              "EULA acceptance is required by Mojang.",
        plugin_support=None,
    ),
    "fabric": _sw(
        "Fabric (mods)",
        ["1.21.4", "1.21.3", "1.21.1", "1.21", "1.20.6", "1.20.4", "1.20.1",
         "1.19.4", "1.19.2", "1.18.2", "1.17.1", "1.16.5", "1.14.4"],
        source="https://fabricmc.net/use/server",
        notes="Lightweight mod loader. Java 21 is required for 1.20.5+; older versions need "
              "Java 17 or lower (match the loader installer's recommendation). Requires the "
              "Fabric server launcher jar. Drop mod .jar files into the mods/ folder.",
        plugin_support=None,
    ),
    "forge": _sw(
        "Forge (mods)",
        ["1.21.4", "1.21.1", "1.20.6", "1.20.4", "1.20.1", "1.19.4", "1.19.2",
         "1.18.2", "1.17.1", "1.16.5", "1.12.2", "1.8.9"],
        java_version="17", source="https://files.minecraftforge.net",
        notes="1.21+ requires Java 21; 1.17–1.20 require Java 16/17; 1.16 and below require "
              "Java 8. Upload the Forge installer-produced jar (or run the installer) and drop "
              "mod .jar files into the mods/ folder.",
        plugin_support=None,
    ),
    "purpur": _sw(
        "Purpur (plugins)",
        ["1.21.4", "1.21.3", "1.21.1", "1.20.6", "1.20.4", "1.20.1",
         "1.19.4", "1.18.2", "1.16.5"],
        source="https://purpurmc.org/downloads",
        notes="Paper fork with extra configuration. Java 21 for 1.20.5+, Java 17 for older. "
              "Plugin-compatible with Paper.",
        plugin_support="bukkit plugins",
    ),
    "spigot": _sw(
        "Spigot (plugins)",
        ["1.21.4", "1.21.1", "1.20.6", "1.20.4", "1.20.1", "1.19.4",
         "1.18.2", "1.17.1", "1.16.5", "1.12.2", "1.8.8"],
        source="https://www.spigotmc.org",
        notes="BuildTools-produced jar. Java 21 for 1.20.5+, Java 17 for 1.18+, Java 8 for "
              "older. Paper is recommended as a faster alternative.",
        plugin_support="bukkit plugins",
    ),
    "quilt": _sw(
        "Quilt (mods)",
        ["1.21.4", "1.21.1", "1.20.4", "1.20.1", "1.19.4", "1.19.2",
         "1.18.2", "1.17.1", "1.16.5"],
        source="https://quiltmc.org/install/server",
        notes="Fabric-compatible mod loader. Most Fabric mods work on Quilt. Drop mod .jar "
              "files into the mods/ folder.",
        plugin_support=None,
    ),
    "bedrock": _sw(
        "Bedrock Dedicated",
        ["1.21.60", "1.21.50", "1.21.40", "1.21.20", "1.21.2", "1.21.0", "1.20.80", "1.20.60"],
        edition="bedrock", source="https://www.minecraft.net/download/server/bedrock",
        notes="Official BDS binary; no Java required. Linux builds are provided by Mojang; "
              "Windows builds run natively. Worlds are NOT interchangeable with Java Edition. "
              "Behavior packs/add-ons go into the behavior_packs and resource_packs folders.",
        platform_support="linux, windows, docker",
    ),
}

settings = Settings()
