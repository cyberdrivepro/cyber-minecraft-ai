"""Validation engine for Bedrock Add-on specifications and generated files."""
import re
import json
from pathlib import Path
from typing import List, Dict, Any
from ai.schemas import ProjectSpec
from core.exceptions import ValidationError
from logger import get_logger

logger = get_logger("builders.bedrock.validator")

class BedrockValidator:
    """Validates Bedrock mod specifications and compiled packs."""
    
    @classmethod
    def validate_spec(cls, spec: ProjectSpec) -> List[str]:
        """Verify project specification before building."""
        errors: List[str] = []
        
        # 1. Namespace check
        if not re.match(r"^[a-z0-9_]{2,32}$", spec.namespace):
            errors.append(f"Invalid namespace '{spec.namespace}'. Must be 2-32 lowercase alphanumeric/underscore.")
            
        # 2. Check duplicate item IDs
        item_ids = set()
        for item in spec.items:
            if item.id in item_ids:
                errors.append(f"Duplicate item ID '{item.id}' found in items.")
            item_ids.add(item.id)
            if not re.match(r"^[a-z0-9_]+$", item.id):
                errors.append(f"Invalid item ID '{item.id}'. Must be lowercase alphanumeric with underscores.")

        # 3. Check duplicate block IDs
        block_ids = set()
        for blk in spec.blocks:
            if blk.id in block_ids or blk.id in item_ids:
                errors.append(f"Duplicate identifier '{blk.id}' in blocks/items.")
            block_ids.add(blk.id)

        # 4. Check recipes
        for r in spec.recipes:
            res_id = r.result_item
            if res_id not in item_ids and not res_id.startswith("minecraft:"):
                # Also allow with namespace
                if not (res_id.startswith(f"{spec.namespace}:") or res_id.replace(f"{spec.namespace}:", "") in item_ids):
                    errors.append(f"Recipe '{r.id}' crafts unknown item '{res_id}'.")
                    
            if r.type == "shaped":
                for row in r.pattern:
                    for char in row:
                        if char != " " and char not in r.ingredients:
                            errors.append(f"Recipe '{r.id}' pattern character '{char}' missing from ingredients map.")

        return errors

    @classmethod
    def validate_pack_files(cls, pack_root: Path) -> List[str]:
        """Validate JSON syntax of all generated files in behavior and resource packs."""
        errors: List[str] = []
        for json_file in pack_root.rglob("*.json"):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    json.load(f)
            except Exception as e:
                errors.append(f"Malformed JSON in {json_file.relative_to(pack_root)}: {e}")
        return errors

bedrock_validator = BedrockValidator()
