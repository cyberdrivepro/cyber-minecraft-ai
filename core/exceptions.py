"""Custom exception hierarchy for Cyber Minecraft AI Mod Builder."""

class CyberModError(Exception):
    """Base exception for all cyber mod errors."""
    pass

class ValidationError(CyberModError):
    """Raised when mod specification or generated structure fails validation."""
    pass

class BuildError(CyberModError):
    """Raised when mod build fails."""
    def __init__(self, message: str, stage: str = "build", logs: str = ""):
        super().__init__(message)
        self.stage = stage
        self.logs = logs

class SecurityError(CyberModError):
    """Raised when an operation violates security constraints."""
    pass

class ModelLoadError(CyberModError):
    """Raised when an AI model fails to load."""
    pass

class AIPlanningError(CyberModError):
    """Raised when AI fails to produce a valid mod plan."""
    pass

class AssetGenerationError(CyberModError):
    """Raised when asset generation or transformation fails."""
    pass
