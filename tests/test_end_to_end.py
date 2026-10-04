"""End-to-end integration test demonstrating the primary target workflow."""
import pytest
from pathlib import Path
from ai.planner import planner
from assets.textures import texture_manager
from builders.bedrock import bedrock_builder
from storage.storage_manager import StorageManager

@pytest.mark.asyncio
async def test_complete_ruby_sword_lifecycle(tmp_path):
    sm = StorageManager(base_dir=tmp_path / "data", output_dir=tmp_path / "outputs")
    user_id = "tg_user_999"
    project_id = "ruby_sword_mod"

    # Step 1: User prompt
    prompt = "Create a ruby sword called Blood Ruby Sword. Damage 14. Durability 1800. Create a recipe using diamonds and redstone."
    
    # Step 2: AI Planner produces validated ProjectSpec
    spec_v1 = await planner.plan_mod(prompt, edition="bedrock")
    assert spec_v1.project_name == "Blood Ruby Sword"
    assert spec_v1.items[0].damage == 14
    assert spec_v1.items[0].durability == 1800
    assert len(spec_v1.recipes) == 1

    # Step 3: Assets generated
    textures_v1 = await texture_manager.generate_project_textures(user_id, project_id, spec_v1)
    assert spec_v1.items[0].id in textures_v1

    # Step 4: Build Bedrock mod
    build_dir_v1 = tmp_path / "builds" / "v1"
    res_v1 = await bedrock_builder.build(spec_v1, build_dir_v1, textures_v1)
    assert res_v1.success is True
    assert res_v1.artifact_path is not None
    
    # Store v1
    sm.save_project_spec(user_id, project_id, version=1, spec_data=spec_v1.model_dump())
    art_v1 = sm.save_artifact(user_id, project_id, version=1, src_path=res_v1.artifact_path)
    assert art_v1.exists()

    # Step 5: Conversational edit -> Make damage 20
    edit_instruction = "Make damage 20"
    spec_v2 = await planner.edit_mod(spec_v1, edit_instruction)
    assert spec_v2.items[0].damage == 20
    assert spec_v2.items[0].durability == 1800  # Durability preserved!

    # Step 6: Build v2
    build_dir_v2 = tmp_path / "builds" / "v2"
    res_v2 = await bedrock_builder.build(spec_v2, build_dir_v2, textures_v1)
    assert res_v2.success is True
    
    # Store v2
    sm.save_project_spec(user_id, project_id, version=2, spec_data=spec_v2.model_dump())
    art_v2 = sm.save_artifact(user_id, project_id, version=2, src_path=res_v2.artifact_path)
    assert art_v2.exists()

    # Verify both versions exist intact
    assert sm.get_project_spec(user_id, project_id, version=1)["items"][0]["damage"] == 14
    assert sm.get_project_spec(user_id, project_id, version=2)["items"][0]["damage"] == 20
