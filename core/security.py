"""Security and sanitization utilities for safe mod generation and execution."""
import os
import re
import zipfile
from pathlib import Path
from typing import Union
from core.exceptions import SecurityError

# Allowed patterns
IDENTIFIER_REGEX = re.compile(r"^[a-z0-9_]+$")
NAMESPACE_REGEX = re.compile(r"^[a-z0-9_]{2,32}$")
JAVA_PACKAGE_REGEX = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")

# Safety limits
MAX_UPLOAD_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_PROJECT_FILE_COUNT = 2000
MAX_EXTRACTED_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB
MAX_BUILD_SECONDS = 180  # 3 minutes max build time

def sanitize_identifier(raw: str, default: str = "item") -> str:
    """
    Sanitize a string to be a safe Minecraft identifier (item/block ID).
    Converts spaces and dashes to underscores, strips non-alphanumeric/underscore,
    and forces lowercase.
    """
    if not raw:
        return default
    cleaned = raw.strip().lower()
    cleaned = re.sub(r"[\s\-]+", "_", cleaned)
    cleaned = re.sub(r"[^a-z0-9_]", "", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned or not cleaned[0].isalnum():
        cleaned = f"{default}_{cleaned}" if cleaned else default
    return cleaned[:32]

def sanitize_namespace(raw: str, default: str = "cybermods") -> str:
    """Sanitize namespace for Bedrock and Fabric mods."""
    sanitized = sanitize_identifier(raw, default=default)
    if len(sanitized) < 2:
        return default
    return sanitized[:32]

def validate_safe_path(base_dir: Union[str, Path], target_path: Union[str, Path]) -> Path:
    """
    Ensure target_path resolves strictly within base_dir to prevent path traversal.
    Raises SecurityError if path escapes base directory.
    """
    base = Path(base_dir).resolve()
    target = Path(target_path).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise SecurityError(f"Access denied: path traversal attempt detected outside '{base}'.")
    return target

def safe_extract_zip(zip_file_path: Union[str, Path], extract_to: Union[str, Path]) -> None:
    """
    Safely extract a zip file preventing Zip Slip vulnerability and zip bombs.
    """
    dest = Path(extract_to).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    total_size = 0
    file_count = 0

    with zipfile.ZipFile(zip_file_path, "r") as zf:
        for member in zf.infolist():
            file_count += 1
            if file_count > MAX_PROJECT_FILE_COUNT:
                raise SecurityError("Zip archive contains too many files (possible zip bomb).")
            
            total_size += member.file_size
            if total_size > MAX_EXTRACTED_SIZE_BYTES:
                raise SecurityError("Zip archive contents exceed maximum allowed size.")

            # Validate target path
            target_path = (dest / member.filename).resolve()
            try:
                target_path.relative_to(dest)
            except ValueError:
                raise SecurityError(f"Zip member '{member.filename}' attempts path traversal.")

            zf.extract(member, dest)
