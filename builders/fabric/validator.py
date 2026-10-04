"""Validation engine for Fabric mods, Java source files, and Gradle projects."""
import re
import json
from pathlib import Path
from typing import List
from ai.schemas import ProjectSpec
from core.security import JAVA_PACKAGE_REGEX, IDENTIFIER_REGEX
from logger import get_logger

logger = get_logger("builders.fabric.validator")

class FabricValidator:
    """Validates Java Fabric mod specifications and generated source files."""
    
    @classmethod
    def validate_spec(cls, spec: ProjectSpec) -> List[str]:
        errors = []
        if not IDENTIFIER_REGEX.match(spec.namespace):
            errors.append(f"Invalid Fabric mod id '{spec.namespace}'. Must match [a-z0-9_]+.")

        pkg = spec.java_config.maven_group
        if not JAVA_PACKAGE_REGEX.match(pkg):
            errors.append(f"Invalid Java maven package '{pkg}'.")

        for item in spec.items:
            if not IDENTIFIER_REGEX.match(item.id):
                errors.append(f"Invalid item ID '{item.id}' for Java Fabric.")

        return errors

    @classmethod
    def validate_project_structure(cls, project_dir: Path) -> List[str]:
        errors = []
        fabric_json = project_dir / "src" / "main" / "resources" / "fabric.mod.json"
        if not fabric_json.exists():
            errors.append("Missing required 'fabric.mod.json' file.")
        else:
            try:
                with open(fabric_json, "r", encoding="utf-8") as f:
                    json.load(f)
            except Exception as e:
                errors.append(f"Invalid fabric.mod.json JSON: {e}")

        # Check build.gradle
        build_gradle = project_dir / "build.gradle"
        if not build_gradle.exists():
            errors.append("Missing build.gradle configuration.")

        return errors

fabric_validator = FabricValidator()
