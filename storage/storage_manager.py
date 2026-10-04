"""StorageManager abstraction for projects, assets, versions, and build artifacts."""
import json
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, List
from config import settings
from logger import get_logger
from core.security import validate_safe_path, sanitize_identifier

logger = get_logger("storage")

class StorageManager:
    """Manages files, project versions, assets, and artifacts across storage backends."""
    
    def __init__(self, base_dir: Optional[Path] = None, output_dir: Optional[Path] = None):
        self.base_dir = (base_dir or settings.DATA_DIR).resolve()
        self.output_dir = (output_dir or settings.OUTPUT_DIR).resolve()
        self.users_dir = self.base_dir / "users"
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def get_project_dir(self, user_id: str, project_id: str) -> Path:
        """Get the base directory for a user's project."""
        safe_uid = sanitize_identifier(str(user_id), default="default_user")
        safe_pid = sanitize_identifier(str(project_id), default="default_project")
        pdir = self.users_dir / safe_uid / "projects" / safe_pid
        validate_safe_path(self.users_dir, pdir)
        pdir.mkdir(parents=True, exist_ok=True)
        return pdir

    def get_versions_dir(self, user_id: str, project_id: str) -> Path:
        vdir = self.get_project_dir(user_id, project_id) / "versions"
        vdir.mkdir(parents=True, exist_ok=True)
        return vdir

    def get_assets_dir(self, user_id: str, project_id: str) -> Path:
        adir = self.get_project_dir(user_id, project_id) / "assets"
        adir.mkdir(parents=True, exist_ok=True)
        return adir

    def get_builds_dir(self, user_id: str, project_id: str) -> Path:
        bdir = self.get_project_dir(user_id, project_id) / "builds"
        bdir.mkdir(parents=True, exist_ok=True)
        return bdir

    def save_project_spec(self, user_id: str, project_id: str, version: int, spec_data: Dict[str, Any]) -> Path:
        """Save project specification for a specific version and update project.json."""
        pdir = self.get_project_dir(user_id, project_id)
        vdir = self.get_versions_dir(user_id, project_id)
        
        # Save versioned spec
        vfile = vdir / f"v{version}.json"
        with open(vfile, "w", encoding="utf-8") as f:
            json.dump(spec_data, f, indent=2)
            
        # Update latest project.json
        main_file = pdir / "project.json"
        with open(main_file, "w", encoding="utf-8") as f:
            json.dump(spec_data, f, indent=2)
            
        logger.info(f"Saved project {project_id} v{version} to {vfile}")
        return vfile

    def get_project_spec(self, user_id: str, project_id: str, version: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Retrieve project specification for a version or latest."""
        pdir = self.get_project_dir(user_id, project_id)
        if version is not None:
            spec_file = self.get_versions_dir(user_id, project_id) / f"v{version}.json"
        else:
            spec_file = pdir / "project.json"
            
        if not spec_file.exists():
            return None
            
        try:
            with open(spec_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading spec from {spec_file}: {e}")
            return None

    def save_artifact(self, user_id: str, project_id: str, version: int, src_path: Path) -> Path:
        """Store the compiled mod artifact (.mcaddon or .jar) in the outputs directory."""
        safe_uid = sanitize_identifier(str(user_id), default="user")
        safe_pid = sanitize_identifier(str(project_id), default="project")
        dest_dir = self.output_dir / safe_uid / safe_pid
        validate_safe_path(self.output_dir, dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        dest_filename = f"{safe_pid}_v{version}{src_path.suffix}"
        dest_file = dest_dir / dest_filename
        shutil.copy2(src_path, dest_file)
        logger.info(f"Artifact stored at {dest_file}")
        return dest_file

    def get_artifact(self, user_id: str, project_id: str, version: int, extension: str) -> Optional[Path]:
        safe_uid = sanitize_identifier(str(user_id), default="user")
        safe_pid = sanitize_identifier(str(project_id), default="project")
        dest_file = self.output_dir / safe_uid / safe_pid / f"{safe_pid}_v{version}{extension}"
        if dest_file.exists():
            return dest_file
        return None

    def delete_project_data(self, user_id: str, project_id: str) -> bool:
        """Cleanly remove project files and artifacts."""
        pdir = self.get_project_dir(user_id, project_id)
        safe_uid = sanitize_identifier(str(user_id), default="user")
        safe_pid = sanitize_identifier(str(project_id), default="project")
        out_dir = self.output_dir / safe_uid / safe_pid
        
        if pdir.exists():
            shutil.rmtree(pdir, ignore_errors=True)
        if out_dir.exists():
            shutil.rmtree(out_dir, ignore_errors=True)
        return True

# Global storage instance
storage = StorageManager()
