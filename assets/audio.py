"""Audio processor supporting .ogg and .wav sounds for weapons, mobs, and blocks."""
from pathlib import Path
from typing import Optional
from core.exceptions import ValidationError
from logger import get_logger

logger = get_logger("assets.audio")

class AudioManager:
    """Validates and stages audio files for Minecraft resource packs."""
    
    SUPPORTED_FORMATS = {".ogg", ".wav"}
    MAX_AUDIO_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB
    
    @classmethod
    def validate_audio_file(cls, file_path: Path) -> bool:
        """Validate audio file extension and size."""
        if not file_path.exists():
            raise ValidationError(f"Audio file '{file_path}' does not exist.")
        if file_path.suffix.lower() not in cls.SUPPORTED_FORMATS:
            raise ValidationError(f"Audio format '{file_path.suffix}' not supported. Use .ogg or .wav.")
        if file_path.stat().st_size > cls.MAX_AUDIO_SIZE_BYTES:
            raise ValidationError("Audio file exceeds maximum 5MB size limit.")
        return True

audio_manager = AudioManager()
