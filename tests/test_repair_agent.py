"""Tests for the automatic repair agent."""
import pytest
from ai.repair_agent import repair_agent
from ai.schemas import ProjectSpec, Item, Recipe

@pytest.mark.asyncio
async def test_repair_duplicate_identifiers():
    spec = ProjectSpec(
        project_name="Dupe Test",
        namespace="cybermods",
        items=[
            Item(id="plasma_sword", display_name="Plasma Sword 1"),
            Item(id="plasma_sword", display_name="Plasma Sword 2")
        ]
    )
    error_log = "SPEC ERROR: Duplicate item ID 'plasma_sword' found in items."
    
    repaired, updated_spec, reason = await repair_agent.attempt_repair(spec, error_log=error_log, attempt=1)
    assert repaired is True
    ids = [it.id for it in updated_spec.items]
    assert len(set(ids)) == 2
    assert "plasma_sword_alt" in ids

@pytest.mark.asyncio
async def test_repair_unknown_recipe_reference():
    spec = ProjectSpec(
        project_name="Recipe Test",
        namespace="cybermods",
        items=[
            Item(id="ruby_blade", display_name="Ruby Blade")
        ],
        recipes=[
            Recipe(
                id="ruby_blade_recipe",
                result_item="non_existent_item",
                pattern=[" D "],
                ingredients={"D": "unknown_mineral"}
            )
        ]
    )
    error_log = "SPEC ERROR: Recipe 'ruby_blade_recipe' crafts unknown item 'non_existent_item'."
    
    repaired, updated_spec, reason = await repair_agent.attempt_repair(spec, error_log=error_log, attempt=1)
    assert repaired is True
    assert updated_spec.recipes[0].result_item == "ruby_blade"
