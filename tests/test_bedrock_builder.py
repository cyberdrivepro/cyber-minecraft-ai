"""Tests for Bedrock Add-on builder, manifest generation, and .mcaddon packaging."""
import zipfile
import pytest
from pathlib import Path
from ai.schemas import ProjectSpec, Item, Recipe
from builders.bedrock import bedrock_builder
from assets.pixel_processor import generate_procedural_sword

@pytest.mark.asyncio
async def test_bedrock_builder_generates_mcaddon(tmp_path):
    spec = ProjectSpec(
        project_name="Blood Ruby Sword",
        namespace="cybermods",
        edition="bedrock",
        items=[
            Item(
                id="blood_ruby_sword",
                display_name="Blood Ruby Sword",
                type="weapon",
                damage=14,
                durability=1800
            )
        ],
        recipes=[
            Recipe(
                id="blood_ruby_sword_recipe",
                result_item="blood_ruby_sword",
                pattern=[" D ", " R ", " S "],
                ingredients={
                    "D": "minecraft:diamond",
                    "R": "minecraft:redstone",
                    "S": "minecraft:stick"
                }
            )
        ]
    )

    # Generate test texture
    tex_path = tmp_path / "blood_ruby_sword.png"
    with open(tex_path, "wb") as f:
        f.write(generate_procedural_sword())

    textures = {"blood_ruby_sword": tex_path}
    output_dir = tmp_path / "build_output"
    output_dir.mkdir()

    result = await bedrock_builder.build(spec, output_dir, textures)
    assert result.success is True
    assert result.artifact_path is not None
    assert result.artifact_path.exists()
    assert result.artifact_path.suffix == ".mcaddon"

    # Verify .mcaddon contains valid manifests and files
    with zipfile.ZipFile(result.artifact_path, "r") as zf:
        file_list = zf.namelist()
        assert any("behavior_pack/manifest.json" in f for f in file_list)
        assert any("resource_pack/manifest.json" in f for f in file_list)
        assert any("items/blood_ruby_sword.json" in f for f in file_list)
        assert any("recipes/blood_ruby_sword_recipe.json" in f for f in file_list)
        assert any("textures/items/blood_ruby_sword.png" in f for f in file_list)
        assert any("texts/en_US.lang" in f for f in file_list)
