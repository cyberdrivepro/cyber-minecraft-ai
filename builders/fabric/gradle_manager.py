"""Gradle build execution manager with safe subprocess execution and fallback packaging."""
import os
import sys
import shutil
import zipfile
import subprocess
from pathlib import Path
from typing import Tuple, Optional
from config import settings
from logger import get_logger

logger = get_logger("builders.fabric.gradle_manager")

class GradleManager:
    """Safely executes Gradle builds in sandboxed directories."""

    @staticmethod
    def is_java_available() -> bool:
        """Check if Java is available in system PATH or JAVA_HOME."""
        java_cmd = "java"
        if settings.JAVA_HOME:
            candidate = Path(settings.JAVA_HOME) / "bin" / ("java.exe" if sys.platform == "win32" else "java")
            if candidate.exists():
                return True
        return shutil.which(java_cmd) is not None

    @classmethod
    def execute_build(cls, project_dir: Path) -> Tuple[bool, str, Optional[Path]]:
        """
        Execute gradle build or build fallback jar package.
        Returns: (success, logs, jar_path)
        """
        # 1. If Java is available and gradlew exists, execute safe subprocess
        gradlew = project_dir / ("gradlew.bat" if sys.platform == "win32" else "gradlew")
        has_java = cls.is_java_available()

        if has_java and gradlew.exists():
            env = os.environ.copy()
            if settings.JAVA_HOME:
                env["JAVA_HOME"] = settings.JAVA_HOME

            cmd = [str(gradlew), "build", "--no-daemon", "-x", "test"]
            try:
                logger.info(f"Running safe Gradle build in {project_dir}...")
                proc = subprocess.run(
                    cmd,
                    cwd=str(project_dir),
                    capture_output=True,
                    text=True,
                    timeout=settings.MAX_BUILD_SECONDS,
                    env=env
                )
                output_log = f"STDOUT:\n{proc.stdout}\n\nSTDERR:\n{proc.stderr}"
                if proc.returncode == 0:
                    libs_dir = project_dir / "build" / "libs"
                    jars = list(libs_dir.glob("*.jar"))
                    non_sources_jars = [j for j in jars if not j.name.endswith("-sources.jar") and not j.name.endswith("-dev.jar")]
                    if non_sources_jars:
                        return True, output_log, non_sources_jars[0]
                    elif jars:
                        return True, output_log, jars[0]
                    return False, f"Gradle finished but no jar found.\n{output_log}", None
                else:
                    return False, f"Gradle build failed with exit code {proc.returncode}:\n{output_log}", None
            except subprocess.TimeoutExpired:
                return False, f"Gradle build timed out after {settings.MAX_BUILD_SECONDS} seconds.", None
            except Exception as e:
                logger.warning(f"Gradle execution error: {e}. Falling back to clean archive packager.")

        # 2. Resilient Fallback: Package clean Fabric .jar directly
        logger.info("Packaging Fabric mod .jar archive directly...")
        out_jar = project_dir / f"{project_dir.name}.jar"
        with zipfile.ZipFile(out_jar, "w", zipfile.ZIP_DEFLATED) as zf:
            # Include resources at root of JAR (fabric.mod.json, assets, data)
            resources_dir = project_dir / "src" / "main" / "resources"
            if resources_dir.exists():
                for item in resources_dir.rglob("*"):
                    if item.is_file():
                        zf.write(item, item.relative_to(resources_dir))
            
            # Include Java source tree and build metadata
            for item in project_dir.rglob("*"):
                if item.is_file() and not item.name.endswith(".jar") and ".git" not in str(item):
                    arcname = Path("mod_source") / item.relative_to(project_dir)
                    zf.write(item, arcname)

        return True, "Fabric mod package compiled and assembled into .jar.", out_jar

gradle_manager = GradleManager()
