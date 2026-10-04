"""Texture management for projects, items, and blocks."""
from pathlib import Path
from typing import Optional, Dict
from ai.schemas import ProjectSpec, Item, Block
from assets.image_provider import image_provider
from storage.storage_manager import storage
from logger import get_logger

logger = get_logger("assets.textures")

class TextureManager:
    """Orchestrates asset creation and caching for mod projects."""
    
    @staticmethod
    async def generate_project_textures(user_id: str, project_id: str, spec: ProjectSpec) -> Dict[str, Path]:
        """
        Generate or retrieve textures for all items and blocks in the specification.
        Returns a mapping of identifier -> generated PNG Path.
        """
        assets_dir = storage.get_assets_dir(user_id, project_id)
        textures_dir = assets_dir / "textures"
        textures_dir.mkdir(parents=True, exist_ok=True)
        
        texture_map: Dict[str, Path] = {}
        
        # 1. Items & weapons
        for item in spec.items:
            tex_file = textures_dir / f"{item.id}.png"
            if not tex_file.exists():
                logger.info(f"Generating texture for item '{item.id}' (color: {item.texture_color})...")
                png_bytes = await image_provider.generate_texture_bytes(
                    prompt=item.texture_prompt,
                    asset_type=item.type,
                    color_str=item.texture_color,
                    resolution=16
                )
                with open(tex_file, "wb") as f:
                    f.write(png_bytes)
            texture_map[item.id] = tex_file

        # 2. Blocks
        for blk in spec.blocks:
            tex_file = textures_dir / f"{blk.id}.png"
            if not tex_file.exists():
                logger.info(f"Generating texture for block '{blk.id}' (color: {blk.texture_color})...")
                png_bytes = await image_provider.generate_texture_bytes(
                    prompt=blk.texture_prompt,
                    asset_type="block",
                    color_str=blk.texture_color,
                    resolution=16
                )
                with open(tex_file, "wb") as f:
                    f.write(png_bytes)
            texture_map[blk.id] = tex_file

        return texture_map

texture_manager = TextureManager()
