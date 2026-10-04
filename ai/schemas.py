"""Pydantic schemas for structured Minecraft mod specifications (Bedrock and Fabric)."""
from typing import List, Dict, Optional, Any, Literal
from pydantic import BaseModel, Field, field_validator
from core.security import sanitize_identifier, sanitize_namespace

class Ability(BaseModel):
    id: Optional[str] = None
    item_id: str
    trigger: Literal["right_click", "sneak_right_click", "attack", "hit", "held", "equip"] = "right_click"
    action: Literal["projectile", "lightning", "explosion", "teleport", "heal", "potion_effect", "dash"] = "projectile"
    damage: Optional[float] = 10.0
    power: Optional[float] = 3.0
    cooldown_ticks: int = 40
    particle: Optional[str] = "minecraft:critical_hit_emitter"
    sound: Optional[str] = "random.explode"

    @field_validator("item_id", mode="before")
    def clean_item_id(cls, v):
        return sanitize_identifier(str(v))

class Projectile(BaseModel):
    id: str
    display_name: str
    speed: float = 1.5
    gravity: float = 0.03
    damage: float = 8.0
    on_hit: Optional[str] = "damage"
    texture_color: Optional[str] = "blue"

    @field_validator("id", mode="before")
    def clean_id(cls, v):
        return sanitize_identifier(str(v))

class Item(BaseModel):
    id: str
    display_name: str
    type: Literal["item", "weapon", "armor", "tool", "food"] = "weapon"
    damage: Optional[int] = 10
    durability: Optional[int] = 1000
    stack_size: int = 1
    texture_prompt: Optional[str] = None
    texture_color: Optional[str] = "#ff2244"
    nutrition: Optional[int] = 4
    saturation: Optional[float] = 0.6
    mining_speed: Optional[float] = 8.0
    armor_points: Optional[int] = 6
    armor_slot: Optional[Literal["helmet", "chestplate", "leggings", "boots"]] = "chestplate"
    fire_resistant: bool = False

    @field_validator("id", mode="before")
    def clean_id(cls, v):
        return sanitize_identifier(str(v))

class Recipe(BaseModel):
    id: str
    result_item: str
    result_count: int = 1
    type: Literal["shaped", "shapeless"] = "shaped"
    pattern: List[str] = Field(default_factory=lambda: [" D ", " R ", " S "])
    ingredients: Dict[str, str] = Field(default_factory=lambda: {
        "D": "minecraft:diamond",
        "R": "minecraft:redstone",
        "S": "minecraft:stick"
    })

    @field_validator("id", "result_item", mode="before")
    def clean_ids(cls, v):
        return sanitize_identifier(str(v))

class Block(BaseModel):
    id: str
    display_name: str
    destroy_time: float = 2.0
    explosion_resistance: float = 10.0
    light_emission: int = 0
    drop_item: Optional[str] = None
    texture_prompt: Optional[str] = None
    texture_color: Optional[str] = "#00ffff"

    @field_validator("id", mode="before")
    def clean_id(cls, v):
        return sanitize_identifier(str(v))

class Mob(BaseModel):
    id: str
    display_name: str
    health: float = 20.0
    speed: float = 0.25
    is_hostile: bool = True
    attack_damage: float = 5.0
    texture_prompt: Optional[str] = None
    drops: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator("id", mode="before")
    def clean_id(cls, v):
        return sanitize_identifier(str(v))

class Boss(Mob):
    boss_bar: bool = True
    boss_bar_color: str = "purple"
    health: float = 300.0
    phases: int = 1
    special_attacks: List[str] = Field(default_factory=list)

class LootTable(BaseModel):
    id: str
    pools: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator("id", mode="before")
    def clean_id(cls, v):
        return sanitize_identifier(str(v))

class Structure(BaseModel):
    id: str
    display_name: str
    size_x: int = 5
    size_y: int = 5
    size_z: int = 5
    blocks: List[Dict[str, Any]] = Field(default_factory=list)

class Biome(BaseModel):
    id: str
    display_name: str
    temperature: float = 0.5
    downfall: float = 0.5

class Sound(BaseModel):
    id: str
    category: str = "neutral"
    file_path: Optional[str] = None

class Texture(BaseModel):
    id: str
    item_id: Optional[str] = None
    resolution: int = 16
    file_path: Optional[str] = None

class Model(BaseModel):
    id: str
    type: str = "geometry"
    file_path: Optional[str] = None

class BedrockConfig(BaseModel):
    min_engine_version: List[int] = Field(default_factory=lambda: [1, 20, 0])
    client_scripts: bool = False

class JavaConfig(BaseModel):
    minecraft_version: str = "1.21.1"
    fabric_loader_version: str = "0.16.5"
    fabric_api_version: str = "0.104.0+1.21.1"
    maven_group: str = "com.cybermods"

class ProjectSpec(BaseModel):
    project_name: str
    namespace: str = "cybermods"
    edition: Literal["bedrock", "fabric"] = "bedrock"
    minecraft_version: str = "latest_supported"
    description: str = ""
    items: List[Item] = Field(default_factory=list)
    abilities: List[Ability] = Field(default_factory=list)
    projectiles: List[Projectile] = Field(default_factory=list)
    recipes: List[Recipe] = Field(default_factory=list)
    blocks: List[Block] = Field(default_factory=list)
    mobs: List[Mob] = Field(default_factory=list)
    bosses: List[Boss] = Field(default_factory=list)
    structures: List[Structure] = Field(default_factory=list)
    biomes: List[Biome] = Field(default_factory=list)
    sounds: List[Sound] = Field(default_factory=list)
    textures: List[Texture] = Field(default_factory=list)
    models: List[Model] = Field(default_factory=list)
    bedrock_config: BedrockConfig = Field(default_factory=BedrockConfig)
    java_config: JavaConfig = Field(default_factory=JavaConfig)

    @field_validator("namespace", mode="before")
    def clean_namespace(cls, v):
        return sanitize_namespace(str(v))
