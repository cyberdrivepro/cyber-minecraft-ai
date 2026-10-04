"""Assets subsystem initialization."""
from assets.pixel_processor import process_to_pixel_art, generate_procedural_sword, generate_procedural_block, generate_procedural_item
from assets.image_provider import ImageProvider, image_provider
from assets.textures import TextureManager, texture_manager
from assets.reference import ReferenceImageManager, reference_manager
from assets.models_3d import Model3DManager, model_3d_manager
from assets.audio import AudioManager, audio_manager

__all__ = [
    "process_to_pixel_art",
    "generate_procedural_sword",
    "generate_procedural_block",
    "generate_procedural_item",
    "ImageProvider",
    "image_provider",
    "TextureManager",
    "texture_manager",
    "ReferenceImageManager",
    "reference_manager",
    "Model3DManager",
    "model_3d_manager",
    "AudioManager",
    "audio_manager",
]
