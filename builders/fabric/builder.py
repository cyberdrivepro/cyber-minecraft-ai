"""Java Fabric mod builder for Minecraft."""
import json
import shutil
from pathlib import Path
from typing import Dict, Any, List
from builders.base import BaseBuilder, BuildResult
from builders.fabric.validator import fabric_validator
from builders.fabric.gradle_manager import gradle_manager
from ai.schemas import ProjectSpec, Item, Recipe, Block
from logger import get_logger

logger = get_logger("builders.fabric.builder")

class FabricBuilder(BaseBuilder):
    """Generates complete Java Fabric mod source projects and compiles into .jar."""
    
    def validate_spec(self, spec: ProjectSpec) -> List[str]:
        return fabric_validator.validate_spec(spec)

    async def build(
        self,
        spec: ProjectSpec,
        output_dir: Path,
        textures: Dict[str, Path]
    ) -> BuildResult:
        logs = []
        logs.append(f"Starting Java Fabric build for project '{spec.project_name}'...")
        
        spec_errors = self.validate_spec(spec)
        if spec_errors:
            for err in spec_errors:
                logs.append(f"SPEC ERROR: {err}")
            return BuildResult(
                success=False,
                edition="fabric",
                logs="\n".join(logs),
                errors=spec_errors
            )

        staging_dir = output_dir / "staging_fabric"
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        staging_dir.mkdir(parents=True, exist_ok=True)

        package_name = spec.java_config.maven_group.lower()
        package_path = staging_dir / "src" / "main" / "java" / Path(*package_name.split("."))
        package_path.mkdir(parents=True, exist_ok=True)

        resources_dir = staging_dir / "src" / "main" / "resources"
        assets_dir = resources_dir / "assets" / spec.namespace
        data_dir = resources_dir / "data" / spec.namespace
        resources_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)

        # 1. Generate gradle.properties
        with open(staging_dir / "gradle.properties", "w", encoding="utf-8") as f:
            f.write(f"""minecraft_version={spec.java_config.minecraft_version}
yarn_mappings={spec.java_config.minecraft_version}+build.1
loader_version={spec.java_config.fabric_loader_version}
fabric_version={spec.java_config.fabric_api_version}
mod_version=1.0.0
maven_group={spec.java_config.maven_group}
archives_base_name={spec.namespace}
""")

        # 2. Generate settings.gradle
        with open(staging_dir / "settings.gradle", "w", encoding="utf-8") as f:
            f.write(f"rootProject.name = '{spec.namespace}'\n")

        # 3. Generate build.gradle
        with open(staging_dir / "build.gradle", "w", encoding="utf-8") as f:
            f.write(f"""plugins {{
    id 'fabric-loom' version '1.8-SNAPSHOT'
    id 'maven-publish'
}}

version = project.mod_version
group = project.maven_group

base {{
    archivesName = project.archives_base_name
}}

dependencies {{
    minecraft "com.mojang:minecraft:${{project.minecraft_version}}"
    mappings "net.fabricmc:yarn:${{project.yarn_mappings}}:v2"
    modImplementation "net.fabricmc:fabric-loader:${{project.loader_version}}"
    modImplementation "net.fabricmc.fabric-api:fabric-api:${{project.fabric_version}}"
}}

processResources {{
    inputs.property "version", project.version
    filesMatching("fabric.mod.json") {{
        expand "version": project.version
    }}
}}

tasks.withType(JavaCompile).configureEach {{
    it.options.release = 21
}}

java {{
    withSourcesJar()
    sourceCompatibility = JavaVersion.VERSION_21
    targetCompatibility = JavaVersion.VERSION_21
}}
""")

        # 4. Generate fabric.mod.json
        fabric_mod_json = {
            "schemaVersion": 1,
            "id": spec.namespace,
            "version": "1.0.0",
            "name": spec.project_name,
            "description": spec.description or "Generated with Cyber Minecraft AI",
            "authors": ["Cyber Minecraft AI"],
            "contact": {},
            "license": "MIT",
            "environment": "*",
            "entrypoints": {
                "main": [
                    f"{package_name}.CyberMod"
                ]
            },
            "depends": {
                "fabricloader": ">=0.16.0",
                "minecraft": f">={spec.java_config.minecraft_version}",
                "java": ">=21"
            }
        }
        with open(resources_dir / "fabric.mod.json", "w", encoding="utf-8") as f:
            json.dump(fabric_mod_json, f, indent=2)

        # 5. Generate Java Source files
        main_class_content = f"""package {package_name};

import net.fabricmc.api.ModInitializer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class CyberMod implements ModInitializer {{
    public static final String MOD_ID = "{spec.namespace}";
    public static final Logger LOGGER = LoggerFactory.getLogger(MOD_ID);

    @Override
    public void onInitialize() {{
        LOGGER.info("Initializing " + MOD_ID);
        ModItems.registerModItems();
        ModBlocks.registerModBlocks();
    }}
}}
"""
        with open(package_path / "CyberMod.java", "w", encoding="utf-8") as f:
            f.write(main_class_content)

        # Generate ModItems.java
        item_registrations = []
        for item in spec.items:
            upper_id = item.id.upper()
            item_registrations.append(
                f'    public static final Item {upper_id} = registerItem("{item.id}", new Item(new Item.Settings().maxCount({item.stack_size})));'
            )

        items_class_content = f"""package {package_name};

import net.minecraft.item.Item;
import net.minecraft.registry.Registries;
import net.minecraft.registry.Registry;
import net.minecraft.util.Identifier;

public class ModItems {{
{chr(10).join(item_registrations)}

    private static Item registerItem(String name, Item item) {{
        return Registry.register(Registries.ITEM, Identifier.of(CyberMod.MOD_ID, name), item);
    }}

    public static void registerModItems() {{
        CyberMod.LOGGER.info("Registering Mod Items for " + CyberMod.MOD_ID);
    }}
}}
"""
        with open(package_path / "ModItems.java", "w", encoding="utf-8") as f:
            f.write(items_class_content)

        # Generate ModBlocks.java
        block_registrations = []
        for blk in spec.blocks:
            upper_id = blk.id.upper()
            block_registrations.append(
                f'    public static final Block {upper_id} = registerBlock("{blk.id}", new Block(AbstractBlock.Settings.create().strength({blk.destroy_time}f, {blk.explosion_resistance}f)));'
            )

        blocks_class_content = f"""package {package_name};

import net.minecraft.block.AbstractBlock;
import net.minecraft.block.Block;
import net.minecraft.item.BlockItem;
import net.minecraft.item.Item;
import net.minecraft.registry.Registries;
import net.minecraft.registry.Registry;
import net.minecraft.util.Identifier;

public class ModBlocks {{
{chr(10).join(block_registrations)}

    private static Block registerBlock(String name, Block block) {{
        registerBlockItem(name, block);
        return Registry.register(Registries.BLOCK, Identifier.of(CyberMod.MOD_ID, name), block);
    }}

    private static Item registerBlockItem(String name, Block block) {{
        return Registry.register(Registries.ITEM, Identifier.of(CyberMod.MOD_ID, name), new BlockItem(block, new Item.Settings()));
    }}

    public static void registerModBlocks() {{
        CyberMod.LOGGER.info("Registering Mod Blocks for " + CyberMod.MOD_ID);
    }}
}}
"""
        with open(package_path / "ModBlocks.java", "w", encoding="utf-8") as f:
            f.write(blocks_class_content)

        # 6. Generate Assets & Textures
        item_tex_dir = assets_dir / "textures" / "item"
        block_tex_dir = assets_dir / "textures" / "block"
        item_models_dir = assets_dir / "models" / "item"
        lang_dir = assets_dir / "lang"
        item_tex_dir.mkdir(parents=True, exist_ok=True)
        block_tex_dir.mkdir(parents=True, exist_ok=True)
        item_models_dir.mkdir(parents=True, exist_ok=True)
        lang_dir.mkdir(parents=True, exist_ok=True)

        lang_dict: Dict[str, str] = {}
        for item in spec.items:
            # Copy texture
            if item.id in textures and textures[item.id].exists():
                shutil.copy2(textures[item.id], item_tex_dir / f"{item.id}.png")
            else:
                (item_tex_dir / f"{item.id}.png").touch()

            # Item Model JSON
            model_json = {
                "parent": "minecraft:item/generated",
                "textures": {
                    "layer0": f"{spec.namespace}:item/{item.id}"
                }
            }
            with open(item_models_dir / f"{item.id}.json", "w", encoding="utf-8") as f:
                json.dump(model_json, f, indent=2)

            lang_dict[f"item.{spec.namespace}.{item.id}"] = item.display_name

        for blk in spec.blocks:
            if blk.id in textures and textures[blk.id].exists():
                shutil.copy2(textures[blk.id], block_tex_dir / f"{blk.id}.png")
            lang_dict[f"block.{spec.namespace}.{blk.id}"] = blk.display_name

        with open(lang_dir / "en_us.json", "w", encoding="utf-8") as f:
            json.dump(lang_dict, f, indent=2)

        # 7. Generate Recipes in data/
        recipes_dir = data_dir / "recipes"
        recipes_dir.mkdir(parents=True, exist_ok=True)
        for r in spec.recipes:
            res_item = r.result_item
            if not res_item.startswith("minecraft:") and not res_item.startswith(f"{spec.namespace}:"):
                res_item = f"{spec.namespace}:{res_item}"

            key_dict = {}
            for char, item_ref in r.ingredients.items():
                if not item_ref.startswith("minecraft:") and not item_ref.startswith(f"{spec.namespace}:"):
                    item_ref = f"{spec.namespace}:{item_ref}"
                key_dict[char] = {"item": item_ref}

            rec_json = {
                "type": "minecraft:crafting_shaped",
                "pattern": r.pattern,
                "key": key_dict,
                "result": {
                    "id": res_item,
                    "count": r.result_count
                }
            }
            with open(recipes_dir / f"{r.id}.json", "w", encoding="utf-8") as f:
                json.dump(rec_json, f, indent=2)

        # 8. Validate structure
        logs.append("Validating Fabric project structure...")
        struct_errors = fabric_validator.validate_project_structure(staging_dir)
        if struct_errors:
            for se in struct_errors:
                logs.append(f"FABRIC STRUCT ERROR: {se}")
            return BuildResult(
                success=False,
                edition="fabric",
                logs="\n".join(logs),
                errors=struct_errors
            )

        # 9. Execute build / package via GradleManager
        logs.append("Executing Fabric build packaging...")
        build_ok, gradle_logs, jar_path = gradle_manager.execute_build(staging_dir)
        logs.append(gradle_logs)

        if not build_ok or not jar_path:
            return BuildResult(
                success=False,
                edition="fabric",
                logs="\n".join(logs),
                errors=["Fabric compilation failed."]
            )

        # Copy artifact to output
        final_jar = output_dir / f"{spec.namespace}.jar"
        shutil.copy2(jar_path, final_jar)

        logs.append(f"Fabric mod JAR created successfully: {final_jar.name}")
        return BuildResult(
            success=True,
            edition="fabric",
            artifact_path=final_jar,
            output_filename=final_jar.name,
            file_size_bytes=final_jar.stat().st_size,
            logs="\n".join(logs)
        )

fabric_builder = FabricBuilder()
