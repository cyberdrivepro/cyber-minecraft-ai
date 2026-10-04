"""Blockbench 3D model and Bedrock geometry handler."""
import json
import zipfile
from pathlib import Path
from typing import Dict, Any, Optional
from core.exceptions import ValidationError
from logger import get_logger

logger = get_logger("assets.models_3d")

class Model3DManager:
    """Validates and processes .bbmodel and Bedrock geometry files."""
    
    @staticmethod
    def validate_bedrock_geometry(file_path: Path) -> bool:
        """Validate Bedrock geometry JSON format."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Bedrock geometry format versions check
            if "format_version" in data and ("minecraft:geometry" in data or any("geometry" in k for k in data.keys())):
                return True
            return "minecraft:geometry" in str(data)
        except Exception as e:
            logger.warning(f"Geometry JSON validation failed: {e}")
            return False

    @staticmethod
    def inspect_bbmodel(file_path: Path) -> Dict[str, Any]:
        """Inspect Blockbench .bbmodel project file."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "name": data.get("name", "custom_model"),
                "format_version": data.get("meta", {}).get("format_version", "unknown"),
                "model_format": data.get("meta", {}).get("model_format", "unknown"),
                "elements_count": len(data.get("elements", []))
            }
        except Exception as e:
            raise ValidationError(f"Invalid .bbmodel file: {e}")

model_3d_manager = Model3DManager()
