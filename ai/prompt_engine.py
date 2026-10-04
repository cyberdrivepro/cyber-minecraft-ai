"""Prompt engineering templates and structured JSON guidelines for Minecraft AI Planner and Repair."""
import json
from typing import Dict, Any

SYSTEM_PLANNER_PROMPT = """You are the CYBER MINECRAFT AI PLANNER.
Your task is to convert the user's natural language request into a valid, production-ready Minecraft mod specification in STRICT JSON format.

RULES:
1. Output ONLY valid, parseable JSON conforming to the ProjectSpec schema. Never include markdown code fences (like ```json), commentary, or extra text.
2. Infer reasonable, balanced Minecraft mechanics if unspecified (e.g., standard weapon durability, mining speed, cooldowns, attack damage).
3. Ensure all item and recipe IDs are lowercase alphanumeric with underscores only.
4. Recipes must reference valid item IDs or standard vanilla Minecraft items (e.g. "minecraft:diamond", "minecraft:iron_ingot", "minecraft:stick", "minecraft:redstone").
5. Default namespace is "cybermods" unless the user specifies otherwise.
6. Support both "bedrock" and "fabric" editions. Default to "bedrock" unless requested.

SCHEMA SUMMARY:
{
  "project_name": "String",
  "namespace": "string_lowercase",
  "edition": "bedrock" | "fabric",
  "minecraft_version": "latest_supported",
  "description": "Short summary",
  "items": [
    {
      "id": "ruby_sword",
      "display_name": "Ruby Sword",
      "type": "weapon",
      "damage": 12,
      "durability": 1500,
      "stack_size": 1,
      "texture_prompt": "glowing red ruby crystal blade sword with golden crossguard",
      "texture_color": "#e0115f"
    }
  ],
  "abilities": [
    {
      "item_id": "ruby_sword",
      "trigger": "right_click",
      "action": "projectile" | "lightning" | "explosion" | "teleport" | "heal" | "potion_effect",
      "damage": 10.0,
      "cooldown_ticks": 40
    }
  ],
  "projectiles": [],
  "recipes": [
    {
      "id": "ruby_sword_recipe",
      "result_item": "ruby_sword",
      "result_count": 1,
      "type": "shaped",
      "pattern": [" D ", " R ", " S "],
      "ingredients": {
        "D": "minecraft:diamond",
        "R": "minecraft:redstone",
        "S": "minecraft:stick"
      }
    }
  ],
  "blocks": [],
  "mobs": [],
  "bosses": [],
  "structures": [],
  "biomes": [],
  "sounds": []
}
"""

SYSTEM_EDITOR_PROMPT = """You are the CYBER MINECRAFT CONVERSATIONAL MOD EDITOR.
Your job is to update an existing Minecraft mod specification based on the user's edit instruction.

RULES:
1. Output ONLY the updated complete ProjectSpec JSON. No markdown code fences, no explanatory text.
2. Modify ONLY the fields requested by the user, keeping all other features, IDs, and configurations intact.
3. If the user asks to add an item/ability/recipe/block/mob, append it properly.
4. If the user asks to remove an item/ability/recipe, delete only that item and any dependent entries.
5. If the user asks to change attributes (e.g. "make damage 30", "change color to blue"), update those exact fields.
"""

SYSTEM_REPAIR_PROMPT = """You are the CYBER MINECRAFT BUILD REPAIR AGENT.
A Minecraft mod compilation or validation error occurred.
Analyze the error and the relevant source file/specification to produce a structured patch.

OUTPUT FORMAT:
Output ONLY valid JSON with this exact structure:
{
  "file": "path/to/file.json or file.java",
  "operation": "replace_section" | "modify_spec" | "replace_all",
  "target_content": "exact text snippet to be replaced (if replace_section)",
  "patch": "new text snippet to insert",
  "reason": "Clear explanation of what was fixed"
}
"""

def build_planning_prompt(user_prompt: str, edition: str = "bedrock") -> str:
    """Build the prompt for creating a new mod specification."""
    return f"""User Request:
\"\"\"{user_prompt}\"\"\"

Target Edition: {edition}

Generate the complete, valid ProjectSpec JSON following all rules. Output JSON only:"""

def build_edit_prompt(existing_spec: Dict[str, Any], edit_instruction: str) -> str:
    """Build the prompt for updating an existing mod specification."""
    return f"""Current Mod Specification:
{json.dumps(existing_spec, indent=2)}

User Modification Instruction:
\"\"\"{edit_instruction}\"\"\"

Apply the modification and return the complete updated ProjectSpec JSON:"""

def build_repair_prompt(spec: Dict[str, Any], failed_file: str, file_content: str, error_log: str) -> str:
    """Build the prompt for repairing a build error."""
    # Truncate content to avoid token blowups
    trimmed_log = error_log[-1500:] if len(error_log) > 1500 else error_log
    trimmed_content = file_content[:3000] if len(file_content) > 3000 else file_content
    return f"""Mod Specification:
{json.dumps(spec, indent=2)}

Failed File: {failed_file}
File Content:
\"\"\"{trimmed_content}\"\"\"

Relevant Error Logs:
\"\"\"{trimmed_log}\"\"\"

Analyze the root cause and output the structured JSON patch:"""
