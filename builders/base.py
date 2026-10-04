"""Base classes and schemas for mod builders."""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

class BuildResult(BaseModel):
    success: bool
    edition: str
    artifact_path: Optional[Path] = None
    output_filename: Optional[str] = None
    file_size_bytes: int = 0
    logs: str = ""
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

class BaseBuilder(ABC):
    """Abstract base class for Bedrock and Fabric mod builders."""
    
    @abstractmethod
    async def build(self, spec: Any, output_dir: Path, textures: Dict[str, Path]) -> BuildResult:
        """Build mod from specification."""
        pass

    @abstractmethod
    def validate_spec(self, spec: Any) -> List[str]:
        """Validate specification before build."""
        pass
