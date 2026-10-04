"""Background job queue and concurrency management using asyncio."""
import asyncio
from datetime import datetime
from typing import Dict, Optional, Callable, Awaitable, List
from pydantic import BaseModel, Field
from config import settings
from logger import get_logger

logger = get_logger("jobs.queue")

class JobStatus:
    QUEUED = "queued"
    PLANNING = "planning"
    GENERATING = "generating"
    VALIDATING = "validating"
    BUILDING = "building"
    REPAIRING = "repairing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class BuildJobItem(BaseModel):
    job_id: str
    project_id: str
    user_id: str
    version: int
    prompt: str
    edition: str = "bedrock"
    is_edit: bool = False
    status: str = JobStatus.QUEUED
    current_stage: str = "Queued in build pipeline..."
    logs: str = ""
    error_message: Optional[str] = None
    artifact_path: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class JobManager:
    """Async background worker queue manager."""
    
    def __init__(self, max_concurrent: int = 1):
        self.max_concurrent = max_concurrent
        self.queue: asyncio.Queue[BuildJobItem] = asyncio.Queue()
        self.active_jobs: Dict[str, BuildJobItem] = {}
        self.completed_jobs: Dict[str, BuildJobItem] = {}
        self.callbacks: Dict[str, Callable[[BuildJobItem], Awaitable[None]]] = {}
        self._workers: List[asyncio.Task] = []
        self._running = False

    def start_workers(self, runner_func: Callable[[BuildJobItem], Awaitable[None]]) -> None:
        """Start background worker tasks."""
        if self._running:
            return
        self._running = True
        for i in range(self.max_concurrent):
            task = asyncio.create_task(self._worker_loop(i, runner_func))
            self._workers.append(task)
        logger.info(f"Started {self.max_concurrent} build worker(s).")

    async def stop_workers(self) -> None:
        """Gracefully stop worker tasks."""
        self._running = False
        for task in self._workers:
            task.cancel()
        self._workers.clear()
        logger.info("Stopped build workers.")

    async def enqueue(
        self,
        job: BuildJobItem,
        progress_callback: Optional[Callable[[BuildJobItem], Awaitable[None]]] = None
    ) -> None:
        """Add job to queue."""
        self.active_jobs[job.job_id] = job
        if progress_callback:
            self.callbacks[job.job_id] = progress_callback
        await self.queue.put(job)
        logger.info(f"Enqueued job {job.job_id} for project {job.project_id} (Queue size: {self.queue.qsize()})")

    def get_job(self, job_id: str) -> Optional[BuildJobItem]:
        """Look up job by ID."""
        return self.active_jobs.get(job_id) or self.completed_jobs.get(job_id)

    async def update_job_stage(self, job: BuildJobItem, status: str, stage_text: str) -> None:
        """Update job stage and notify callback."""
        job.status = status
        job.current_stage = stage_text
        job.logs += f"\n[{datetime.utcnow().strftime('%H:%M:%S')}] {stage_text}"
        
        callback = self.callbacks.get(job.job_id)
        if callback:
            try:
                await callback(job)
            except Exception as e:
                logger.warning(f"Error in progress callback for job {job.job_id}: {e}")

    async def _worker_loop(self, worker_id: int, runner_func: Callable[[BuildJobItem], Awaitable[None]]) -> None:
        """Worker execution loop."""
        logger.info(f"Worker #{worker_id} started.")
        while self._running:
            try:
                job = await self.queue.get()
                job.started_at = datetime.utcnow()
                try:
                    await runner_func(job)
                except Exception as e:
                    logger.error(f"Worker #{worker_id} encountered unhandled error on job {job.job_id}: {e}")
                    job.status = JobStatus.FAILED
                    job.error_message = str(e)
                finally:
                    job.completed_at = datetime.utcnow()
                    self.completed_jobs[job.job_id] = job
                    if job.job_id in self.active_jobs:
                        del self.active_jobs[job.job_id]
                    self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Worker #{worker_id} queue loop error: {e}")

# Global job manager
job_manager = JobManager(max_concurrent=settings.MAX_CONCURRENT_BUILDS)
