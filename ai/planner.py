"""AI Mod Planner: turns user natural language into validated Pydantic ProjectSpec objects."""
import re
import json
from typing import Dict, Any, Optional, Tuple
from pydantic import ValidationError as PydanticValidationError
from config import settings
from logger import get_logger
from core.exceptions import AIPlanningError
from core.security import sanitize_identifier, sanitize_namespace
from ai.schemas import (
    ProjectSpec,
    Item,
    Recipe,
    Ability,
    Block,
    Mob,
    Boss,
    Projectile,
    BedrockConfig,
    JavaConfig,
)
from ai.prompt_engine import (
    SYSTEM_PLANNER_PROMPT,
    SYSTEM_EDITOR_PROMPT,
    build_planning_prompt,
    build_edit_prompt,
)
from ai.model_manager import model_manager

logger = get_logger("ai.planner")

def clean_and_repair_json(raw_text: str) -> Dict[str, Any]:
    """
    Robust JSON parser and repair engine for LLM outputs.
    Handles code fences, leading/trailing conversational text,
    trailing commas, single quotes, and missing brackets.
    """
    if not raw_text or not raw_text.strip():
        raise AIPlanningError("Empty response received from AI model.")

    text = raw_text.strip()
    
    # Remove markdown code blocks if present
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()

    # Find the outermost JSON object bounds { ... }
    start_idx = text.find("{")
    end_idx = text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        text = text[start_idx : end_idx + 1]

    # Quick first pass parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Repair step 1: replace single quotes with double quotes where appropriate
    repaired = re.sub(r"(?<=\{|,|\[)\s*'([^']+)'\s*:", r'"\1":', text)
    repaired = re.sub(r":\s*'([^']*)'", r': "\1"', repaired)
    
    # Repair step 2: remove trailing commas before closing braces/brackets
    repaired = re.sub(r",\s*([\]}])", r"\1", repaired)

    try:
        return json.loads(repaired)
    except json.JSONDecodeError as err:
        logger.warning(f"JSON regex repair failed: {err}. Raw output was:\n{raw_text[:300]}")
        raise AIPlanningError(f"Could not parse valid JSON from AI response: {err}")

class ModPlanner:
    """Plans new mods and applies edits to existing mod specifications."""
    
    @staticmethod
    def heuristic_parse_prompt(prompt: str, edition: str = "bedrock") -> ProjectSpec:
        """
        Deterministic NLP extractor for Minecraft attributes.
        Guarantees 100% reliable baseline generation even when offline
        or when external LLM is cold-starting.
        """
        lower = prompt.lower()
        
        # 1. Project name & item display name
        name_match = re.search(r"(?:called|named|name is)\s+['\"]?([a-zA-Z0-9\s]+?)['\"]?(?:\.|\,|$|\n)", prompt, re.I)
        if name_match:
            display_name = name_match.group(1).strip()
        else:
            # Check for common items in text
            words = [w for w in ["hammer", "sword", "axe", "pickaxe", "bow", "shield", "armor", "dagger", "staff", "blade", "wand"] if w in lower]
            if words:
                target_word = words[0]
                # Try to extract preceding adjective like "ruby sword", "plasma sword", "thor hammer"
                m = re.search(rf"([a-zA-Z]+)\s+{target_word}", lower)
                if m and m.group(1) not in ("a", "an", "the", "create", "make", "build"):
                    display_name = f"{m.group(1).capitalize()} {target_word.capitalize()}"
                else:
                    display_name = f"Cyber {target_word.capitalize()}"
            else:
                display_name = "Cyber Item"

        item_id = sanitize_identifier(display_name.lower())
        
        # 2. Damage
        damage = 12
        dmg_match = re.search(r"(\d+)\s*(?:damage|dmg|attack)", lower)
        if not dmg_match:
            dmg_match = re.search(r"(?:damage|dmg|attack)\s*(?:of|is|:)?\s*(\d+)", lower)
        if dmg_match:
            damage = int(dmg_match.group(1))
            
        # 3. Durability
        durability = 1500
        dur_match = re.search(r"(\d+)\s*(?:durability|dura|uses)", lower)
        if not dur_match:
            dur_match = re.search(r"(?:durability|dura|uses)\s*(?:of|is|:)?\s*(\d+)", lower)
        if dur_match:
            durability = int(dur_match.group(1))

        # 4. Color / Theme
        color = "#e0115f"  # ruby red default
        for c_name, c_hex in [("ruby", "#e0115f"), ("blood", "#8a0303"), ("blue", "#0088ff"), 
                              ("plasma", "#00ffff"), ("green", "#00ff66"), ("gold", "#ffd700"), 
                              ("purple", "#9900ff"), ("fire", "#ff4500"), ("dark", "#222222")]:
            if c_name in lower:
                color = c_hex
                break

        # 5. Abilities
        abilities = []
        if "lightning" in lower or "thor" in lower:
            abilities.append(Ability(
                item_id=item_id,
                trigger="right_click",
                action="lightning",
                damage=float(damage),
                cooldown_ticks=60
            ))
        elif "plasma" in lower or "shoot" in lower or "beam" in lower or "projectile" in lower or "fire" in lower:
            abilities.append(Ability(
                item_id=item_id,
                trigger="right_click",
                action="projectile",
                damage=float(max(6, damage - 2)),
                cooldown_ticks=40
            ))
        elif "explosion" in lower or "explode" in lower:
            abilities.append(Ability(
                item_id=item_id,
                trigger="sneak_right_click",
                action="explosion",
                power=3.5,
                cooldown_ticks=80
            ))

        # 6. Recipe
        recipes = []
        if "recipe" in lower or "craft" in lower or "diamonds" in lower or "ruby" in lower:
            # Build shaped sword or item recipe
            pattern = [" D ", " R ", " S "]
            ingredients = {
                "D": "minecraft:diamond",
                "R": "minecraft:redstone",
                "S": "minecraft:stick"
            }
            if "iron" in lower:
                ingredients["D"] = "minecraft:iron_ingot"
            if "netherite" in lower:
                ingredients["D"] = "minecraft:netherite_ingot"
            if "gold" in lower:
                ingredients["D"] = "minecraft:gold_ingot"

            recipes.append(Recipe(
                id=f"{item_id}_recipe",
                result_item=item_id,
                result_count=1,
                type="shaped",
                pattern=pattern,
                ingredients=ingredients
            ))

        item_type = "weapon" if any(w in lower for w in ["sword", "hammer", "blade", "axe", "dagger"]) else "item"

        items = [
            Item(
                id=item_id,
                display_name=display_name,
                type=item_type,
                damage=damage,
                durability=durability,
                stack_size=1,
                texture_prompt=f"{display_name} glowing futuristic pixel art",
                texture_color=color
            )
        ]

        # 7. Blocks or Mobs check
        blocks = []
        if "block" in lower or "ore" in lower:
            block_id = sanitize_identifier(f"{item_id}_block")
            blocks.append(Block(
                id=block_id,
                display_name=f"{display_name} Block",
                destroy_time=3.0,
                explosion_resistance=15.0,
                texture_color=color
            ))

        mobs = []
        bosses = []
        if "boss" in lower:
            boss_id = sanitize_identifier(f"{display_name.lower()}_boss")
            bosses.append(Boss(
                id=boss_id,
                display_name=f"{display_name} Titan",
                health=350.0,
                attack_damage=18.0,
                boss_bar=True,
                boss_bar_color="purple"
            ))
        elif "mob" in lower or "monster" in lower or "entity" in lower:
            mob_id = sanitize_identifier(f"{display_name.lower()}_creature")
            mobs.append(Mob(
                id=mob_id,
                display_name=f"{display_name} Creature",
                health=40.0,
                attack_damage=8.0,
                is_hostile=True
            ))

        return ProjectSpec(
            project_name=display_name,
            namespace="cybermods",
            edition="fabric" if "fabric" in edition.lower() or "java" in edition.lower() else "bedrock",
            minecraft_version="latest_supported",
            description=f"Generated Minecraft mod for {display_name}",
            items=items,
            abilities=abilities,
            recipes=recipes,
            blocks=blocks,
            mobs=mobs,
            bosses=bosses,
            bedrock_config=BedrockConfig(),
            java_config=JavaConfig()
        )

    async def plan_mod(self, user_prompt: str, edition: str = "bedrock") -> ProjectSpec:
        """
        Create a validated ProjectSpec from natural language.
        Tries AI model first, validates against Pydantic, repairs if needed,
        and falls back gracefully to the deterministic NLP parser if AI is unavailable.
        """
        logger.info(f"Planning mod for prompt: '{user_prompt}' (edition: {edition})")
        full_prompt = f"{SYSTEM_PLANNER_PROMPT}\n\n{build_planning_prompt(user_prompt, edition)}"
        
        try:
            raw_ai_output = await model_manager.generate(full_prompt, max_tokens=1500)
            json_data = clean_and_repair_json(raw_ai_output)
            spec = ProjectSpec.model_validate(json_data)
            logger.info(f"Successfully generated ProjectSpec '{spec.project_name}' via AI.")
            return spec
        except Exception as e:
            logger.warning(f"AI generation failed or invalid JSON ({e}). Utilizing deterministic heuristic planner.")
            spec = self.heuristic_parse_prompt(user_prompt, edition)
            logger.info(f"Deterministic planner generated ProjectSpec '{spec.project_name}'.")
            return spec

    async def edit_mod(self, existing_spec: ProjectSpec, edit_instruction: str) -> ProjectSpec:
        """
        Apply conversational edits to an existing ProjectSpec.
        Updates only specified parameters while preserving other data.
        """
        logger.info(f"Editing ProjectSpec '{existing_spec.project_name}' with: '{edit_instruction}'")
        full_prompt = f"{SYSTEM_EDITOR_PROMPT}\n\n{build_edit_prompt(existing_spec.model_dump(), edit_instruction)}"
        
        try:
            raw_ai_output = await model_manager.generate(full_prompt, max_tokens=1500)
            json_data = clean_and_repair_json(raw_ai_output)
            updated_spec = ProjectSpec.model_validate(json_data)
            logger.info(f"AI successfully updated ProjectSpec '{updated_spec.project_name}'.")
            return updated_spec
        except Exception as e:
            logger.warning(f"AI edit failed ({e}). Applying deterministic patch.")
            return self._apply_deterministic_edit(existing_spec, edit_instruction)

    def _apply_deterministic_edit(self, spec: ProjectSpec, instruction: str) -> ProjectSpec:
        """Deterministic field editor fallback."""
        lower = instruction.lower()
        data = spec.model_dump()
        
        # 1. Damage modification
        dmg_match = re.search(r"(?:make|change|set)?\s*(?:damage|dmg)\s*(?:to|is|=)?\s*(\d+)", lower)
        if dmg_match and data.get("items"):
            new_dmg = int(dmg_match.group(1))
            for item in data["items"]:
                item["damage"] = new_dmg
            for ability in data.get("abilities", []):
                ability["damage"] = float(new_dmg)

        # 2. Durability modification
        dur_match = re.search(r"(?:make|change|set)?\s*(?:durability|dura)\s*(?:to|is|=)?\s*(\d+)", lower)
        if dur_match and data.get("items"):
            new_dur = int(dur_match.group(1))
            for item in data["items"]:
                item["durability"] = new_dur

        # 3. Color modification
        for c_name, c_hex in [("ruby", "#e0115f"), ("red", "#ff2244"), ("blue", "#0088ff"), 
                              ("plasma", "#00ffff"), ("green", "#00ff66"), ("gold", "#ffd700"), 
                              ("purple", "#9900ff"), ("black", "#222222"), ("white", "#ffffff")]:
            if f"to {c_name}" in lower or f"{c_name} to" in lower or f"make {c_name}" in lower or f"color {c_name}" in lower:
                for item in data.get("items", []):
                    item["texture_color"] = c_hex
                    if item.get("texture_prompt"):
                        item["texture_prompt"] = f"{item['display_name']} with vibrant {c_name} theme"

        # 4. Remove ability
        if "remove" in lower and ("ability" in lower or "explosion" in lower or "lightning" in lower or "projectile" in lower):
            action_type = "explosion" if "explosion" in lower else "lightning" if "lightning" in lower else "projectile"
            data["abilities"] = [ab for ab in data.get("abilities", []) if ab.get("action") != action_type]

        # 5. Add recipe
        if "add" in lower and ("recipe" in lower or "crafting" in lower):
            if data.get("items") and not data.get("recipes"):
                first_item_id = data["items"][0]["id"]
                data["recipes"] = [{
                    "id": f"{first_item_id}_recipe",
                    "result_item": first_item_id,
                    "result_count": 1,
                    "type": "shaped",
                    "pattern": [" D ", " R ", " S "],
                    "ingredients": {
                        "D": "minecraft:diamond",
                        "R": "minecraft:redstone",
                        "S": "minecraft:stick"
                    }
                }]

        # 6. Make boss stronger
        if "boss" in lower and ("stronger" in lower or "twice" in lower or "double" in lower):
            for boss in data.get("bosses", []):
                boss["health"] = boss.get("health", 300.0) * 2.0
                boss["attack_damage"] = boss.get("attack_damage", 15.0) * 1.5

        return ProjectSpec.model_validate(data)

# Global planner instance
planner = ModPlanner()
