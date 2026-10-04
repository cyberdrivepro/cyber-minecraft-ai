"""Tests for Java Fabric builder."""
import zipfile
import pytest
from pathlib import Path
from ai.schemas import ProjectSpec, Item, Recipe, Block
from builders.fabric import fabric_builder
from assets.pixel_processor import generate_procedural_sword

@pytest.mark.asyncio
async def test_fabric_builder_generates_jar_structure(tmp_path):
    spec = ProjectSpec(
        project_name="Cyber Fabric Mod",
        namespace="cyberfabric",
        edition="fabric",
        items=[
            Item(id="plasma_sword", display_name="Plasma Sword", type="weapon", damage=18)
        ],
        blocks=[
            Block(id="cyber_core", display_name="Cyber Core")
        ]
    )

    tex_item = tmp_path / "plasma_sword.png"
    with open(tex_item, "wb") as f:
        f.write(generate_procedural_sword())

    tex_block = tmp_path / "cyber_core.png"
    with open(tex_block, "wb") as f:
        f.write(generate_procedural_sword())

    textures = {"plasma_sword": tex_item, "cyber_core": tex_block}
    output_dir = tmp_path / "output_fabric"
    output_dir.mkdir()

    res = await fabric_builder.build(spec, output_dir, textures)
    assert res.success is True
    assert res.artifact_path is not None
    assert res.artifact_path.suffix == ".jar"

    # Verify contents of generated jar
    with zipfile.ZipFile(res.artifact_path, "r") as zf:
        names = zf.namelist()
        assert any("fabric.mod.json" in n for n in names)
        assert any("CyberMod.java" in n for n in names)
        assert any("ModItems.java" in n for n in names)
        assert any("ModBlocks.java" in n for n in names)
