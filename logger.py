"""Structured logging with secret masking and project build log handlers."""
import logging
import sys
import re
from pathlib import Path
from typing import Optional
from config import settings

# Sensitive patterns to redact
_SENSITIVE_PATTERNS = [
    re.compile(r"bot[0-9]{8,12}:[a-zA-Z0-9_-]{35}"),  # Telegram bot tokens
    re.compile(r"hf_[a-zA-Z0-9]{34,40}"),             # Hugging Face tokens
    re.compile(r"sk-[a-zA-Z0-9]{32,60}"),             # OpenAI/Groq keys
    re.compile(r"gsk_[a-zA-Z0-9]{32,60}"),            # Groq keys
]

class SecretRedactingFormatter(logging.Formatter):
    """Custom logging formatter that strips sensitive tokens and secrets."""
    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        for pattern in _SENSITIVE_PATTERNS:
            msg = pattern.sub("[REDACTED_SECRET]", msg)
        # Also redact from settings if populated
        for secret_val in [settings.TELEGRAM_BOT_TOKEN, settings.HF_TOKEN, settings.ADMIN_TOKEN, 
                           settings.OPENAI_API_KEY, settings.GROQ_API_KEY, settings.OPENROUTER_API_KEY]:
            if secret_val and len(secret_val) > 4:
                msg = msg.replace(secret_val, "[REDACTED_SECRET]")
        return msg

def get_logger(name: str = "cybermod") -> logging.Logger:
    """Return a configured logger instance."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
        logger.setLevel(level)
        
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = SecretRedactingFormatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
    return logger

def create_project_file_logger(project_dir: Path) -> tuple[logging.Logger, logging.FileHandler]:
    """Create a project-specific build logger that writes to build.log inside project directory."""
    project_dir.mkdir(parents=True, exist_ok=True)
    log_file = project_dir / "build.log"
    
    logger_name = f"build_{project_dir.name}"
    proj_logger = logging.getLogger(logger_name)
    proj_logger.setLevel(logging.DEBUG)
    
    handler = logging.FileHandler(str(log_file), mode="a", encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    formatter = SecretRedactingFormatter(
        fmt="%(asctime)s [%(levelname)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    handler.setFormatter(formatter)
    proj_logger.addHandler(handler)
    return proj_logger, handler
