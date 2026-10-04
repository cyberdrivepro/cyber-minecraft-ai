"""Pixel art processor and procedural Minecraft texture generator."""
from io import BytesIO
from typing import Tuple, Optional
from PIL import Image, ImageDraw, ImageColor
from logger import get_logger

logger = get_logger("assets.pixel_processor")

def parse_hex_color(color_str: Optional[str], default: Tuple[int, int, int] = (220, 20, 60)) -> Tuple[int, int, int]:
    """Parse color string (hex or name) into RGB tuple."""
    if not color_str:
        return default
    try:
        if color_str.startswith("#"):
            return ImageColor.getrgb(color_str)
        return ImageColor.getrgb(color_str)
    except Exception:
        return default

def adjust_brightness(rgb: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
    """Lighten or darken an RGB tuple."""
    return (
        max(0, min(255, int(rgb[0] * factor))),
        max(0, min(255, int(rgb[1] * factor))),
        max(0, min(255, int(rgb[2] * factor)))
    )

def process_to_pixel_art(image_bytes: bytes, target_size: int = 16) -> bytes:
    """
    Process an arbitrary uploaded image into clean Minecraft-ready pixel art:
    crops square, scales down using Nearest-Neighbor, and returns PNG bytes.
    """
    img = Image.open(BytesIO(image_bytes)).convert("RGBA")
    
    # Crop to square
    w, h = img.size
    min_dim = min(w, h)
    left = (w - min_dim) // 2
    top = (h - min_dim) // 2
    img = img.crop((left, top, left + min_dim, top + min_dim))
    
    # Resample with NEAREST for crisp Minecraft pixels
    pixel_img = img.resize((target_size, target_size), Image.Resampling.NEAREST)
    
    buf = BytesIO()
    pixel_img.save(buf, format="PNG")
    return buf.getvalue()

def generate_procedural_sword(
    blade_color_str: Optional[str] = "#e0115f",
    guard_color_str: Optional[str] = "#d4af37",
    size: int = 16
) -> bytes:
    """
    Generate a 16x16 authentic Minecraft-style diagonal sword texture with blade highlights,
    shadow edge, crossguard, and hilt.
    """
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    blade_base = parse_hex_color(blade_color_str, (224, 17, 95))
    blade_bright = adjust_brightness(blade_base, 1.35)
    blade_dark = adjust_brightness(blade_base, 0.65)
    
    guard_color = parse_hex_color(guard_color_str, (212, 175, 55))
    guard_dark = adjust_brightness(guard_color, 0.7)
    
    hilt_color = (101, 67, 33)   # wood brown
    pommel_color = guard_color

    # Draw diagonal sword from bottom-left (1, 14) to top-right (14, 1)
    # Blade spine and tip
    tip_coords = [(14, 1), (13, 2), (12, 3), (11, 4), (10, 5), (9, 6), (8, 7), (7, 8)]
    for x, y in tip_coords:
        img.putpixel((x, y), (*blade_bright, 255))
        img.putpixel((x - 1, y), (*blade_base, 255))
        img.putpixel((x, y + 1), (*blade_dark, 255))
        
    # Extra tip point
    img.putpixel((15, 0), (*blade_bright, 255))
    img.putpixel((14, 0), (*blade_base, 255))
    img.putpixel((15, 1), (*blade_dark, 255))

    # Crossguard at (6, 9) area
    guard_pixels = [(7, 9), (6, 8), (5, 9), (6, 10), (8, 8), (5, 8)]
    for x, y in guard_pixels:
        if 0 <= x < 16 and 0 <= y < 16:
            img.putpixel((x, y), (*guard_color, 255))
    img.putpixel((6, 9), (*guard_dark, 255))

    # Hilt / Handle (diagonal down-left)
    hilt_pixels = [(4, 11), (3, 12), (2, 13)]
    for x, y in hilt_pixels:
        img.putpixel((x, y), (*hilt_color, 255))

    # Pommel
    img.putpixel((1, 14), (*pommel_color, 255))
    img.putpixel((0, 15), (*guard_dark, 255))

    if size != 16:
        img = img.resize((size, size), Image.Resampling.NEAREST)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def generate_procedural_block(color_str: Optional[str] = "#00ffff", size: int = 16) -> bytes:
    """Generate a clean Minecraft ore/futuristic block texture."""
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    base_stone = (80, 80, 85)
    dark_stone = (50, 50, 55)
    light_stone = (110, 110, 115)
    accent = parse_hex_color(color_str, (0, 255, 255))
    bright_accent = adjust_brightness(accent, 1.4)
    
    # Fill stone texture background
    for y in range(16):
        for x in range(16):
            # Checker/noise pattern
            noise = ((x * 7 + y * 13) % 5)
            if noise == 0:
                img.putpixel((x, y), (*dark_stone, 255))
            elif noise == 1:
                img.putpixel((x, y), (*light_stone, 255))
            else:
                img.putpixel((x, y), (*base_stone, 255))
                
    # Place ore/crystal veins
    vein_coords = [
        (4, 3), (5, 3), (4, 4), (5, 5), (6, 5),
        (10, 8), (11, 8), (11, 9), (12, 9), (10, 9),
        (3, 11), (4, 11), (4, 12), (8, 12), (9, 13)
    ]
    for x, y in vein_coords:
        img.putpixel((x, y), (*accent, 255))
    # Highlights
    img.putpixel((4, 3), (*bright_accent, 255))
    img.putpixel((11, 8), (*bright_accent, 255))
    img.putpixel((4, 11), (*bright_accent, 255))

    if size != 16:
        img = img.resize((size, size), Image.Resampling.NEAREST)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def generate_procedural_item(color_str: Optional[str] = "#ff2244", size: int = 16) -> bytes:
    """Generate an item/gem/orb texture."""
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    gem_color = parse_hex_color(color_str, (255, 34, 68))
    gem_bright = adjust_brightness(gem_color, 1.4)
    gem_dark = adjust_brightness(gem_color, 0.6)
    
    # Draw faceted crystal orb (centered 16x16)
    for y in range(4, 12):
        for x in range(4, 12):
            if (x in (4, 11) and y in (4, 11)):
                continue  # rounded corners
            img.putpixel((x, y), (*gem_color, 255))
            
    # Highlight facets
    img.putpixel((5, 5), (*gem_bright, 255))
    img.putpixel((6, 5), (*gem_bright, 255))
    img.putpixel((5, 6), (*gem_bright, 255))
    
    # Shadow facets
    img.putpixel((10, 10), (*gem_dark, 255))
    img.putpixel((9, 10), (*gem_dark, 255))
    img.putpixel((10, 9), (*gem_dark, 255))

    if size != 16:
        img = img.resize((size, size), Image.Resampling.NEAREST)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
