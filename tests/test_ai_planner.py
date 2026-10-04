"""Tests for AI planner, JSON repair, and conversational edits."""
import pytest
from ai.planner import clean_and_repair_json, planner
from ai.schemas import ProjectSpec, Item

def test_clean_and_repair_json_with_code_fences():
    raw = """```json
    {
        "project_name": "Plasma Blade",
        "namespace": "cybermods",
        "edition": "bedrock",
        "items": []
    }
    ```"""
    data = clean_and_repair_json(raw)
    assert data["project_name"] == "Plasma Blade"

def test_clean_and_repair_json_trailing_commas():
    raw = """
    {
        "project_name": "Trailing Mod",
        "namespace": "cybermods",
        "edition": "bedrock",
        "items": [],
    }
    """
    data = clean_and_repair_json(raw)
    assert data["project_name"] == "Trailing Mod"

def test_heuristic_parse_ruby_sword():
    prompt = "Create a ruby sword called Blood Ruby Sword. Damage 14. Durability 1800. Create a recipe using diamonds and redstone."
    spec = planner.heuristic_parse_prompt(prompt, edition="bedrock")
    
    assert spec.project_name == "Blood Ruby Sword"
    assert len(spec.items) == 1
    item = spec.items[0]
    assert item.damage == 14
    assert item.durability == 1800
    assert len(spec.recipes) == 1
    assert spec.recipes[0].result_item == item.id

def test_conversational_edit_deterministic():
    prompt = "Create a ruby sword called Blood Ruby Sword. Damage 14. Durability 1800."
    spec = planner.heuristic_parse_prompt(prompt, edition="bedrock")
    
    # Edit: Make damage 30
    updated = planner._apply_deterministic_edit(spec, "Make damage 30")
    assert updated.items[0].damage == 30
    assert updated.items[0].durability == 1800  # Preserved!

    # Edit: Change color to blue
    updated2 = planner._apply_deterministic_edit(updated, "Change color to blue")
    assert updated2.items[0].damage == 30  # Preserved!
    assert updated2.items[0].texture_color == "#0088ff"
