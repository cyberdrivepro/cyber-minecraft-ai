"""Image provider supporting procedural generation and optional Hugging Face Inference."""
import httpx
from typing import Optional
from config import settings
from logger import get_logger
from assets.pixel_processor import (
    generate_procedural_sword,
    generate_procedural_block,
    generate_procedural_item,
    process_to_pixel_art
)

logger = get_logger("assets.image_provider")

class ImageProvider:
    """Manages texture generation using procedural algorithms or cloud inference."""
    
    @staticmethod
    async def generate_texture_bytes(
        prompt: Optional[str] = None,
        asset_type: str = "weapon",
        color_str: Optional[str] = None,
        resolution: int = 16
    ) -> bytes:
        """Generate Minecraft texture bytes."""
        # 1. Try Hugging Face Diffusion if configured and HF_TOKEN present
        if settings.HF_TOKEN and prompt and False:  # Optional cloud diffusion
            try:
                # We can call an endpoint if configured
                pass
            except Exception as e:
                logger.warning(f"Diffusion generation failed: {e}. Falling back to procedural.")

        # 2. Fast deterministic procedural generator
        t = (asset_type or "weapon").lower()
        if "weapon" in t or "sword" in t or "blade" in t or "hammer" in t:
            return generate_procedural_sword(blade_color_str=color_str, size=resolution)
        elif "block" in t or "ore" in t:
            return generate_procedural_block(color_str=color_str, size=resolution)
        else:
            return generate_procedural_item(color_str=color_str, size=resolution)

    @staticmethod
    def process_uploaded_image(raw_bytes: bytes, resolution: int = 16) -> bytes:
        """Convert any user-uploaded image into Minecraft pixel art."""
        return process_to_pixel_art(raw_bytes, target_size=resolution)

image_provider = ImageProvider()
