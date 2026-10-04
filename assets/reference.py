"""Reference image handling and vision prompt analysis."""
from pathlib import Path
from typing import Optional
from PIL import Image
from storage.storage_manager import storage
from logger import get_logger

logger = get_logger("assets.reference")

class ReferenceImageManager:
    """Manages user reference images and color palette extraction."""
    
    @staticmethod
    def save_reference_image(user_id: str, project_id: str, raw_bytes: bytes, filename: str = "ref.png") -> Path:
        """Store reference image in project assets."""
        ref_dir = storage.get_assets_dir(user_id, project_id) / "references"
        ref_dir.mkdir(parents=True, exist_ok=True)
        dest = ref_dir / filename
        with open(dest, "wb") as f:
            f.write(raw_bytes)
        return dest

    @staticmethod
    def extract_dominant_color(image_path: Path) -> str:
        """Extract dominant hex color from reference image."""
        try:
            img = Image.open(image_path).convert("RGB")
            img = img.resize((50, 50))
            colors = img.getcolors(maxcolors=2500)
            if colors:
                # Find most frequent non-white non-black color
                sorted_colors = sorted(colors, key=lambda c: c[0], reverse=True)
                for count, (r, g, b) in sorted_colors:
                    if (r + g + b > 50) and (r + g + b < 700):
                        return f"#{r:02x}{g:02x}{b:02x}"
                return f"#{sorted_colors[0][1][0]:02x}{sorted_colors[0][1][1]:02x}{sorted_colors[0][1][2]:02x}"
        except Exception as e:
            logger.warning(f"Could not extract dominant color: {e}")
        return "#e0115f"

reference_manager = ReferenceImageManager()
