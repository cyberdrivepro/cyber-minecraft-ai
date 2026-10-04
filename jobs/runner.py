"""Job runner orchestrating AI Planning, Asset Creation, Building, and Automatic Repair."""
import json
from pathlib import Path
from typing import Optional
from config import settings
from logger import get_logger, create_project_file_logger
from storage.storage_manager import storage
from storage.database import get_db
from storage.models import Project, ProjectVersion, BuildJob as DBBuildJob
from ai.schemas import ProjectSpec
from ai.planner import planner
from ai.repair_agent import repair_agent
from assets.textures import texture_manager
from builders.bedrock import bedrock_builder
from builders.fabric import fabric_builder
from builders.base import BuildResult
from jobs.queue import BuildJobItem, JobStatus, job_manager

logger = get_logger("jobs.runner")

async def execute_build_job(job: BuildJobItem) -> None:
    """Complete lifecycle execution of a build job."""
    proj_dir = storage.get_project_dir(job.user_id, job.project_id)
    proj_logger, file_handler = create_project_file_logger(proj_dir)
    
    try:
        proj_logger.info(f"=== Starting Build Job {job.job_id} for Project {job.project_id} (v{job.version}) ===")
        
        # 1. AI Planning stage
        await job_manager.update_job_stage(job, JobStatus.PLANNING, "🧠 Understanding request...")
        
        if job.is_edit:
            existing_data = storage.get_project_spec(job.user_id, job.project_id)
            if not existing_data:
                raise ValueError("Cannot edit project: existing specification not found.")
            existing_spec = ProjectSpec.model_validate(existing_data)
            spec = await planner.edit_mod(existing_spec, job.prompt)
            change_summary = f"Edit: {job.prompt[:80]}"
        else:
            spec = await planner.plan_mod(job.prompt, edition=job.edition)
            change_summary = "Initial mod generation"

        proj_logger.info(f"Mod spec ready: {spec.project_name} ({spec.edition})")

        # 2. Asset Generation stage
        await job_manager.update_job_stage(job, JobStatus.GENERATING, "🎨 Creating assets...")
        textures = await texture_manager.generate_project_textures(job.user_id, job.project_id, spec)
        proj_logger.info(f"Generated {len(textures)} texture assets.")

        # 3. Project Generation & Validation stage
        await job_manager.update_job_stage(job, JobStatus.BUILDING, "📦 Generating project & building...")
        
        builder = fabric_builder if spec.edition == "fabric" else bedrock_builder
        build_output_dir = storage.get_builds_dir(job.user_id, job.project_id) / f"v{job.version}"
        build_output_dir.mkdir(parents=True, exist_ok=True)
        
        build_result: BuildResult = await builder.build(spec, build_output_dir, textures)
        proj_logger.info(build_result.logs)

        # 4. Validation & Automatic Repair Loop
        repair_attempts = 0
        while not build_result.success and repair_attempts < settings.MAX_REPAIR_ATTEMPTS:
            repair_attempts += 1
            stage_msg = f"🔧 Repairing automatically... (Attempt {repair_attempts}/{settings.MAX_REPAIR_ATTEMPTS})"
            await job_manager.update_job_stage(job, JobStatus.REPAIRING, stage_msg)
            proj_logger.warning(stage_msg)

            repaired, repaired_spec, reason = await repair_agent.attempt_repair(
                spec,
                error_log=build_result.logs + "\n" + "\n".join(build_result.errors),
                attempt=repair_attempts
            )
            
            if repaired:
                spec = repaired_spec
                proj_logger.info(f"Repair applied: {reason}. Rebuilding...")
                build_result = await builder.build(spec, build_output_dir, textures)
                proj_logger.info(build_result.logs)
            else:
                proj_logger.warning("No repair patch could be applied. Aborting repair loop.")
                break

        # 5. Check final build status
        if not build_result.success or not build_result.artifact_path:
            error_msg = f"Build failed after {repair_attempts} repair attempts:\n" + "\n".join(build_result.errors)
            proj_logger.error(error_msg)
            await job_manager.update_job_stage(job, JobStatus.FAILED, f"❌ Build failed: {build_result.errors[0] if build_result.errors else 'Unknown error'}")
            job.error_message = error_msg
            _persist_job_db(job, spec, False, None, repair_attempts)
            return

        # 6. Save Artifact and Version
        await job_manager.update_job_stage(job, JobStatus.VALIDATING, "🧪 Checking output...")
        
        final_artifact = storage.save_artifact(
            user_id=job.user_id,
            project_id=job.project_id,
            version=job.version,
            src_path=build_result.artifact_path
        )
        
        storage.save_project_spec(
            user_id=job.user_id,
            project_id=job.project_id,
            version=job.version,
            spec_data=spec.model_dump()
        )

        job.artifact_path = str(final_artifact)
        await job_manager.update_job_stage(job, JobStatus.COMPLETED, "✅ Ready")
        proj_logger.info(f"Build job {job.job_id} completed successfully. Artifact: {final_artifact}")
        
        _persist_job_db(job, spec, True, str(final_artifact), repair_attempts, change_summary)

    except Exception as e:
        logger.error(f"Error executing build job {job.job_id}: {e}", exc_info=True)
        job.error_message = str(e)
        await job_manager.update_job_stage(job, JobStatus.FAILED, f"❌ Build failed: {str(e)[:100]}")
    finally:
        proj_logger.removeHandler(file_handler)
        file_handler.close()

def _persist_job_db(
    job: BuildJobItem,
    spec: Optional[ProjectSpec],
    success: bool,
    artifact_path: Optional[str],
    repair_attempts: int,
    change_summary: str = "Mod update"
) -> None:
    """Update database records for project, version, and job."""
    try:
        with get_db() as db:
            # Update or create project
            proj = db.query(Project).filter(Project.id == job.project_id).first()
            if not proj and spec:
                proj = Project(
                    id=job.project_id,
                    user_id=job.user_id,
                    name=spec.project_name,
                    namespace=spec.namespace,
                    edition=spec.edition,
                    description=spec.description,
                    current_version=job.version,
                    status="ready" if success else "failed"
                )
                db.add(proj)
            elif proj:
                proj.current_version = job.version
                proj.status = "ready" if success else "failed"
                if spec:
                    proj.name = spec.project_name
                    proj.namespace = spec.namespace

            # Record version
            if spec:
                v = ProjectVersion(
                    project_id=job.project_id,
                    version_number=job.version,
                    spec_json=json.dumps(spec.model_dump()),
                    change_summary=change_summary,
                    build_status="success" if success else "failed",
                    artifact_path=artifact_path
                )
                db.add(v)

            # Record or update build job
            db_job = db.query(DBBuildJob).filter(DBBuildJob.id == job.job_id).first()
            if not db_job:
                db_job = DBBuildJob(
                    id=job.job_id,
                    project_id=job.project_id,
                    version_number=job.version,
                    status=job.status,
                    logs=job.logs,
                    error_message=job.error_message,
                    repair_attempts=repair_attempts,
                    artifact_url=artifact_path
                )
                db.add(db_job)
            else:
                db_job.status = job.status
                db_job.logs = job.logs
                db_job.error_message = job.error_message
                db_job.repair_attempts = repair_attempts
                db_job.artifact_url = artifact_path
    except Exception as e:
        logger.error(f"Failed to persist job record to database: {e}")
