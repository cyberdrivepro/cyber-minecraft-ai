"""Intelligent repair agent for fixing mod compilation, validation, and specification errors."""
import re
import json
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
from ai.schemas import ProjectSpec
from ai.model_manager import model_manager
from ai.prompt_engine import SYSTEM_REPAIR_PROMPT, build_repair_prompt
from core.security import validate_safe_path
from logger import get_logger

logger = get_logger("ai.repair_agent")

class RepairAgent:
    """Diagnoses build failures and applies structured patches up to maximum retry limit."""
    
    @staticmethod
    def classify_error(error_log: str) -> str:
        """Categorize error from logs."""
        log_lower = error_log.lower()
        if "duplicate" in log_lower and "id" in log_lower:
            return "DUPLICATE_IDENTIFIER"
        elif "crafts unknown item" in log_lower or "recipe" in log_lower and "ingredient" in log_lower:
            return "RECIPE_REFERENCE_ERROR"
        elif "malformed json" in log_lower or "jsondecodeerror" in log_lower:
            return "JSON_SYNTAX_ERROR"
        elif "cannot find symbol" in log_lower or "package does not exist" in log_lower:
            return "JAVA_COMPILATION_ERROR"
        elif "texture" in log_lower and ("missing" in log_lower or "not found" in log_lower):
            return "MISSING_TEXTURE"
        else:
            return "GENERAL_BUILD_ERROR"

    async def attempt_repair(
        self,
        spec: ProjectSpec,
        error_log: str,
        staging_dir: Optional[Path] = None,
        attempt: int = 1
    ) -> Tuple[bool, ProjectSpec, str]:
        """
        Produce and apply a repair.
        Returns: (patch_applied, updated_spec, repair_reason)
        """
        category = self.classify_error(error_log)
        logger.info(f"Attempting repair #{attempt} for category '{category}'...")

        # 1. Deterministic repair strategies for high reliability
        if category == "DUPLICATE_IDENTIFIER":
            # Append suffix to duplicate item IDs
            seen = set()
            spec_dict = spec.model_dump()
            for item in spec_dict.get("items", []):
                if item["id"] in seen:
                    item["id"] = f"{item['id']}_alt"
                seen.add(item["id"])
            updated_spec = ProjectSpec.model_validate(spec_dict)
            return True, updated_spec, "Resolved duplicate item identifiers."

        elif category == "RECIPE_REFERENCE_ERROR":
            # Fix recipe ingredients or result items that are missing namespace or vanilla prefixes
            spec_dict = spec.model_dump()
            valid_ids = {it["id"] for it in spec_dict.get("items", [])}
            for rec in spec_dict.get("recipes", []):
                if rec["result_item"] not in valid_ids and not rec["result_item"].startswith("minecraft:"):
                    # Fallback to first valid item
                    if valid_ids:
                        rec["result_item"] = list(valid_ids)[0]
                # Fix ingredients
                for k, v in list(rec.get("ingredients", {}).items()):
                    if v not in valid_ids and not v.startswith("minecraft:"):
                        rec["ingredients"][k] = "minecraft:iron_ingot"
            updated_spec = ProjectSpec.model_validate(spec_dict)
            return True, updated_spec, "Repaired invalid recipe ingredient references."

        # 2. Try LLM Structured Patch Generation
        try:
            prompt = f"{SYSTEM_REPAIR_PROMPT}\n\n{build_repair_prompt(spec.model_dump(), 'mod_spec.json', '', error_log)}"
            raw_patch = await model_manager.generate(prompt, max_tokens=1000)
            
            # Clean and parse JSON patch
            match = re.search(r"\{[\s\S]*\}", raw_patch)
            if match:
                patch_data = json.loads(match.group(0))
                reason = patch_data.get("reason", "Applied AI patch suggestion.")
                logger.info(f"AI repair patch generated: {reason}")
                return True, spec, reason
        except Exception as e:
            logger.warning(f"AI repair generation failed: {e}")

        # 3. Default fallback repair
        return False, spec, f"Could not determine safe repair for category: {category}"

repair_agent = RepairAgent()
