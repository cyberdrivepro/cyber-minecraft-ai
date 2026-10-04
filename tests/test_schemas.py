"""Tests for Pydantic mod schemas and identifier sanitization."""
import pytest
from pydantic import ValidationError as PydanticValidationError
from ai.schemas import ProjectSpec, Item, Recipe, Ability, Block, Mob
from core.security import sanitize_identifier, sanitize_namespace

def test_sanitize_identifier():
    assert sanitize_identifier("Blood Ruby Sword") == "blood_ruby_sword"
    assert sanitize_identifier("Thor's Hammer 2026!") == "thors_hammer_2026"
    assert sanitize_identifier("  --plasma-blade--  ") == "plasma_blade"
    assert sanitize_identifier("") == "item"
    assert sanitize_identifier("!!!") == "item"

def test_sanitize_namespace():
    assert sanitize_namespace("My Cool Mod") == "my_cool_mod"
    assert sanitize_namespace("A") == "cybermods"
    assert sanitize_namespace("cybermods") == "cybermods"

def test_project_spec_valid():
    spec = ProjectSpec(
        project_name="Ruby Arsenal",
        namespace="ruby_mods",
        edition="bedrock",
        items=[
            Item(
                id="ruby_sword",
                display_name="Ruby Sword",
                type="weapon",
                damage=14,
                durability=1800
            )
        ],
        recipes=[
            Recipe(
                id="ruby_sword_recipe",
                result_item="ruby_sword",
                pattern=[" D ", " R ", " S "],
                ingredients={
                    "D": "minecraft:diamond",
                    "R": "minecraft:redstone",
                    "S": "minecraft:stick"
                }
            )
        ]
    )
    assert spec.project_name == "Ruby Arsenal"
    assert spec.items[0].damage == 14
    assert spec.recipes[0].result_item == "ruby_sword"

def test_item_clean_id():
    item = Item(id="Super Ruby Blade!!", display_name="Super Ruby Blade")
    assert item.id == "super_ruby_blade"
