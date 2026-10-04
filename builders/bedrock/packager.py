"""Packager for Minecraft Bedrock .mcaddon archives."""
import zipfile
from pathlib import Path
from typing import Optional
from logger import get_logger

logger = get_logger("builders.bedrock.packager")

class BedrockPackager:
    """Compresses generated packs into a standard Minecraft .mcaddon file."""
    
    @staticmethod
    def create_mcaddon(staging_dir: Path, output_file: Path) -> Path:
        """
        Bundle behavior_pack and resource_pack folders into an .mcaddon archive.
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)
        if output_file.exists():
            output_file.unlink()

        with zipfile.ZipFile(output_file, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in staging_dir.rglob("*"):
                if item.is_file():
                    # Archive relative to staging directory
                    arcname = item.relative_to(staging_dir)
                    zf.write(item, arcname)

        logger.info(f"Successfully created .mcaddon: {output_file} ({output_file.stat().st_size} bytes)")
        return output_file

bedrock_packager = BedrockPackager()
