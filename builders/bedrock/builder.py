"""Deterministic Bedrock Add-on builder for Minecraft."""
import uuid
import json
import shutil
from pathlib import Path
from typing import Dict, Any, List
from builders.base import BaseBuilder, BuildResult
from builders.bedrock.validator import bedrock_validator
from builders.bedrock.packager import bedrock_packager
from ai.schemas import ProjectSpec, Item, Recipe, Block, Mob, Boss, Ability
from logger import get_logger

logger = get_logger("builders.bedrock.builder")

class BedrockBuilder(BaseBuilder):
    """Generates complete behavior and resource packs, and compiles into .mcaddon."""
    
    def validate_spec(self, spec: ProjectSpec) -> List[str]:
        return bedrock_validator.validate_spec(spec)

    async def build(
        self,
        spec: ProjectSpec,
        output_dir: Path,
        textures: Dict[str, Path]
    ) -> BuildResult:
        """Execute deterministic generation of Bedrock Add-on files."""
        logs = []
        logs.append(f"Starting Bedrock build for project '{spec.project_name}'...")
        
        # 1. Validate spec
        spec_errors = self.validate_spec(spec)
        if spec_errors:
            for err in spec_errors:
                logs.append(f"SPEC ERROR: {err}")
            return BuildResult(
                success=False,
                edition="bedrock",
                logs="\n".join(logs),
                errors=spec_errors
            )

        staging_dir = output_dir / "staging_bedrock"
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        staging_dir.mkdir(parents=True, exist_ok=True)

        bp_dir = staging_dir / "behavior_pack"
        rp_dir = staging_dir / "resource_pack"
        bp_dir.mkdir(parents=True, exist_ok=True)
        rp_dir.mkdir(parents=True, exist_ok=True)

        # Generate UUIDs
        bp_header_uuid = str(uuid.uuid4())
        bp_module_uuid = str(uuid.uuid4())
        rp_header_uuid = str(uuid.uuid4())
        rp_module_uuid = str(uuid.uuid4())

        logs.append("Generated pack UUIDs:")
        logs.append(f"  BP Header: {bp_header_uuid}")
        logs.append(f"  RP Header: {rp_header_uuid}")

        # 2. Build Behavior Pack manifest.json
        bp_manifest = {
            "format_version": 2,
            "header": {
                "name": f"{spec.project_name} (Behavior)",
                "description": spec.description or f"Cyber Mod - {spec.project_name}",
                "uuid": bp_header_uuid,
                "version": [1, 0, 0],
                "min_engine_version": spec.bedrock_config.min_engine_version
            },
            "modules": [
                {
                    "type": "data",
                    "uuid": bp_module_uuid,
                    "version": [1, 0, 0]
                }
            ],
            "dependencies": [
                {
                    "uuid": rp_header_uuid,
                    "version": [1, 0, 0]
                }
            ]
        }
        with open(bp_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(bp_manifest, f, indent=2)

        # 3. Build Resource Pack manifest.json
        rp_manifest = {
            "format_version": 2,
            "header": {
                "name": f"{spec.project_name} (Resource)",
                "description": spec.description or f"Cyber Mod - {spec.project_name}",
                "uuid": rp_header_uuid,
                "version": [1, 0, 0],
                "min_engine_version": spec.bedrock_config.min_engine_version
            },
            "modules": [
                {
                    "type": "resources",
                    "uuid": rp_module_uuid,
                    "version": [1, 0, 0]
                }
            ]
        }
        with open(rp_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(rp_manifest, f, indent=2)

        # 4. Generate Items in Behavior Pack
        bp_items_dir = bp_dir / "items"
        bp_items_dir.mkdir(parents=True, exist_ok=True)
        
        rp_textures_dir = rp_dir / "textures"
        rp_textures_dir.mkdir(parents=True, exist_ok=True)
        rp_items_tex_dir = rp_textures_dir / "items"
        rp_items_tex_dir.mkdir(parents=True, exist_ok=True)
        rp_blocks_tex_dir = rp_textures_dir / "blocks"
        rp_blocks_tex_dir.mkdir(parents=True, exist_ok=True)

        item_texture_data: Dict[str, Any] = {}
        lang_lines: List[str] = [f"## Localization for {spec.project_name}"]

        # Map abilities by item_id
        item_abilities = {ab.item_id: ab for ab in spec.abilities}

        for item in spec.items:
            full_item_id = f"{spec.namespace}:{item.id}"
            logs.append(f"Building item '{full_item_id}'...")

            components: Dict[str, Any] = {
                "minecraft:icon": {"texture": item.id},
                "minecraft:display_name": {"value": item.display_name},
                "minecraft:max_stack_size": item.stack_size,
                "minecraft:hand_equipped": True if item.type in ("weapon", "tool") else False,
            }

            if item.damage:
                components["minecraft:damage"] = item.damage

            if item.durability:
                components["minecraft:durability"] = {"max_durability": item.durability}

            if item.fire_resistant:
                components["minecraft:fire_resistant"] = True

            # If item has an ability with cooldown
            if item.id in item_abilities:
                ab = item_abilities[item.id]
                duration_sec = round(ab.cooldown_ticks / 20.0, 2)
                components["minecraft:cooldown"] = {
                    "category": item.id,
                    "duration": duration_sec
                }

            item_json = {
                "format_version": "1.20.50",
                "minecraft:item": {
                    "description": {
                        "identifier": full_item_id,
                        "category": "Equipment" if item.type in ("weapon", "tool", "armor") else "Items"
                    },
                    "components": components
                }
            }

            with open(bp_items_dir / f"{item.id}.json", "w", encoding="utf-8") as f:
                json.dump(item_json, f, indent=2)

            # Copy item texture
            if item.id in textures and textures[item.id].exists():
                shutil.copy2(textures[item.id], rp_items_tex_dir / f"{item.id}.png")
            else:
                # Fallback blank/default texture
                (rp_items_tex_dir / f"{item.id}.png").touch()

            item_texture_data[item.id] = {"textures": f"textures/items/{item.id}"}
            lang_lines.append(f"item.{full_item_id}.name={item.display_name}")

        # 5. Generate Blocks
        if spec.blocks:
            bp_blocks_dir = bp_dir / "blocks"
            bp_blocks_dir.mkdir(parents=True, exist_ok=True)
            terrain_texture_data: Dict[str, Any] = {}

            for blk in spec.blocks:
                full_block_id = f"{spec.namespace}:{blk.id}"
                logs.append(f"Building block '{full_block_id}'...")

                block_json = {
                    "format_version": "1.20.0",
                    "minecraft:block": {
                        "description": {
                            "identifier": full_block_id
                        },
                        "components": {
                            "minecraft:destructible_by_mining": {
                                "seconds_to_destroy": blk.destroy_time
                            },
                            "minecraft:explosion_resistance": blk.explosion_resistance,
                            "minecraft:light_emission": blk.light_emission,
                            "minecraft:unit_cube": {},
                            "minecraft:material_instances": {
                                "*": {
                                    "texture": blk.id,
                                    "render_method": "opaque"
                                }
                            }
                        }
                    }
                }

                with open(bp_blocks_dir / f"{blk.id}.json", "w", encoding="utf-8") as f:
                    json.dump(block_json, f, indent=2)

                if blk.id in textures and textures[blk.id].exists():
                    shutil.copy2(textures[blk.id], rp_blocks_tex_dir / f"{blk.id}.png")

                terrain_texture_data[blk.id] = {"textures": f"textures/blocks/{blk.id}"}
                lang_lines.append(f"tile.{full_block_id}.name={blk.display_name}")

            terrain_tex_json = {
                "resource_pack_name": spec.namespace,
                "texture_name": "atlas.terrain",
                "texture_data": terrain_texture_data
            }
            with open(rp_textures_dir / "terrain_texture.json", "w", encoding="utf-8") as f:
                json.dump(terrain_tex_json, f, indent=2)

        # 6. Generate item_texture.json
        item_tex_json = {
            "resource_pack_name": spec.namespace,
            "texture_name": "atlas.items",
            "texture_data": item_texture_data
        }
        with open(rp_textures_dir / "item_texture.json", "w", encoding="utf-8") as f:
            json.dump(item_tex_json, f, indent=2)

        # 7. Generate Recipes
        if spec.recipes:
            bp_recipes_dir = bp_dir / "recipes"
            bp_recipes_dir.mkdir(parents=True, exist_ok=True)

            for r in spec.recipes:
                full_recipe_id = f"{spec.namespace}:{r.id}"
                logs.append(f"Building recipe '{full_recipe_id}'...")

                res_item = r.result_item
                if not res_item.startswith("minecraft:") and not res_item.startswith(f"{spec.namespace}:"):
                    res_item = f"{spec.namespace}:{res_item}"

                # Format ingredient keys
                key_dict = {}
                for char, item_ref in r.ingredients.items():
                    if not item_ref.startswith("minecraft:") and not item_ref.startswith(f"{spec.namespace}:"):
                        item_ref = f"{spec.namespace}:{item_ref}"
                    key_dict[char] = {"item": item_ref}

                recipe_json = {
                    "format_version": "1.20.0",
                    "minecraft:recipe_shaped": {
                        "description": {
                            "identifier": full_recipe_id
                        },
                        "tags": ["crafting_table"],
                        "pattern": r.pattern,
                        "key": key_dict,
                        "result": {
                            "item": res_item,
                            "count": r.result_count
                        }
                    }
                }

                with open(bp_recipes_dir / f"{r.id}.json", "w", encoding="utf-8") as f:
                    json.dump(recipe_json, f, indent=2)

        # 8. Generate Entities (Mobs and Bosses)
        all_mobs: List[Mob] = list(spec.mobs) + list(spec.bosses)
        if all_mobs:
            bp_entities_dir = bp_dir / "entities"
            bp_entities_dir.mkdir(parents=True, exist_ok=True)

            for mob in all_mobs:
                full_mob_id = f"{spec.namespace}:{mob.id}"
                logs.append(f"Building entity '{full_mob_id}'...")

                entity_components: Dict[str, Any] = {
                    "minecraft:health": {"value": mob.health, "max": mob.health},
                    "minecraft:movement": {"value": mob.speed},
                    "minecraft:attack": {"damage": mob.attack_damage},
                    "minecraft:type_family": {"family": [mob.id, "monster" if mob.is_hostile else "mob"]},
                    "minecraft:collision_box": {"width": 0.8, "height": 1.8},
                    "minecraft:physics": {}
                }

                if isinstance(mob, Boss) and mob.boss_bar:
                    entity_components["minecraft:boss"] = {
                        "should_darken_sky": True,
                        "name": mob.display_name,
                        "hud_range": 60
                    }

                entity_json = {
                    "format_version": "1.20.0",
                    "minecraft:entity": {
                        "description": {
                            "identifier": full_mob_id,
                            "is_spawnable": True,
                            "is_summonable": True,
                            "is_experimental": False
                        },
                        "components": entity_components
                    }
                }

                with open(bp_entities_dir / f"{mob.id}.json", "w", encoding="utf-8") as f:
                    json.dump(entity_json, f, indent=2)

                lang_lines.append(f"entity.{full_mob_id}.name={mob.display_name}")

        # 9. Write localization texts
        texts_dir = rp_dir / "texts"
        texts_dir.mkdir(parents=True, exist_ok=True)
        with open(texts_dir / "en_US.lang", "w", encoding="utf-8") as f:
            f.write("\n".join(lang_lines) + "\n")

        # 10. Validate generated files
        logs.append("Validating generated Bedrock JSON pack files...")
        file_errors = bedrock_validator.validate_pack_files(staging_dir)
        if file_errors:
            for fe in file_errors:
                logs.append(f"PACK FILE ERROR: {fe}")
            return BuildResult(
                success=False,
                edition="bedrock",
                logs="\n".join(logs),
                errors=file_errors
            )

        # 11. Package into .mcaddon
        out_filename = f"{spec.namespace}_{spec.items[0].id if spec.items else 'mod'}.mcaddon"
        mcaddon_path = output_dir / out_filename
        bedrock_packager.create_mcaddon(staging_dir, mcaddon_path)

        logs.append("Bedrock Add-on compilation successful!")
        logs.append(f"Output artifact: {mcaddon_path.name}")
        logs.append(f"Artifact size: {mcaddon_path.stat().st_size} bytes")

        return BuildResult(
            success=True,
            edition="bedrock",
            artifact_path=mcaddon_path,
            output_filename=mcaddon_path.name,
            file_size_bytes=mcaddon_path.stat().st_size,
            logs="\n".join(logs)
        )

bedrock_builder = BedrockBuilder()
