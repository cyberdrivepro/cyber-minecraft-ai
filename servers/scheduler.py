"""Durable scheduler for recurring server tasks (backups, restarts, commands...).

Schedules live in the database so they survive application restarts; a single
background task polls for due jobs, executes them through the ServerManager,
records run history and prevents overlapping executions of the same schedule.
"""
import asyncio
from datetime import datetime, timedelta
from typing import Optional

from storage.database import get_db
from storage.models import Schedule, ScheduleRun
from servers.manager import server_manager, ServerStatus
from logger import get_logger

logger = get_logger("servers.scheduler")

POLL_SECONDS = 30


def compute_next_run(schedule: Schedule, from_time: datetime) -> Optional[datetime]:
    """Compute the next run time for interval or daily schedules."""
    if schedule.enabled is False:  # None (unflushed row) counts as enabled
        return None
    if schedule.interval_minutes and schedule.interval_minutes > 0:
        base = schedule.last_run_at or from_time
        candidate = base + timedelta(minutes=schedule.interval_minutes)
        while candidate <= from_time:
            candidate += timedelta(minutes=schedule.interval_minutes)
        return candidate
    if schedule.daily_time:
        try:
            hour, minute = (int(x) for x in schedule.daily_time.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                return None
        except ValueError:
            return None
        candidate = from_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= from_time:
            candidate += timedelta(days=1)
        return candidate
    return None


async def execute_schedule(schedule_id: int) -> str:
    """Run one schedule action; returns a human-readable result detail."""
    with get_db() as db:
        schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
        if not schedule:
            return "Schedule deleted before execution"
        server_id = schedule.server_id
        action = schedule.action
        payload = schedule.payload

    if action == "backup":
        row = await server_manager.create_backup(server_id)
        return f"Backup created: {row.filename}"
    if action == "restart":
        await server_manager.restart_server(server_id)
        return "Restart queued"
    if action == "stop":
        await server_manager.request_stop(server_id, reason="schedule")
        return "Stop requested"
    if action == "start":
        await server_manager.request_start(server_id)
        return "Start queued"
    if action == "save":
        out = await server_manager.send_command(server_id, "save-all")
        return out[-1] if out else "save-all sent"
    if action == "command":
        if not payload:
            return "No command configured"
        out = await server_manager.send_command(server_id, payload[:200])
        return out[-1] if out else "Command sent"
    return f"Unknown action '{action}'"


class SchedulerService:
    """Polls the schedules table and executes due jobs safely."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running = False
        # In-flight execution markers prevent overlapping runs of one schedule.
        self._inflight: set = set()

    async def startup(self) -> None:
        self._running = True
        with get_db() as db:
            for schedule in db.query(Schedule).all():
                if schedule.enabled and schedule.next_run_at is None:
                    schedule.next_run_at = compute_next_run(schedule, datetime.utcnow())
        self._task = asyncio.create_task(self._loop())
        logger.info("Schedule service online.")

    async def shutdown(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Schedule service stopped.")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Scheduler tick error: {e}", exc_info=True)
            await asyncio.sleep(POLL_SECONDS)

    async def _tick(self) -> None:
        now = datetime.utcnow()
        with get_db() as db:
            due = (
                db.query(Schedule)
                .filter(Schedule.enabled.is_(True), Schedule.next_run_at.isnot(None), Schedule.next_run_at <= now)
                .all()
            )
            due_ids = [(s.id, s.server_id) for s in due]
            for schedule in due:
                # Reserve the slot immediately so a slow tick cannot double-run.
                schedule.next_run_at = compute_next_run(schedule, now)
                schedule.last_run_at = now
        for schedule_id, server_id in due_ids:
            if schedule_id in self._inflight:
                continue
            self._inflight.add(schedule_id)
            try:
                with get_db() as db:
                    run = ScheduleRun(schedule_id=schedule_id, status="running")
                    db.add(run)
                    db.flush()
                    run_id = run.id
                try:
                    detail = await execute_schedule(schedule_id)
                    status = "success"
                except Exception as e:
                    detail = str(e)[:500]
                    status = "failed"
                    logger.warning(f"Schedule {schedule_id} run failed: {e}")
                with get_db() as db:
                    run = db.query(ScheduleRun).filter(ScheduleRun.id == run_id).first()
                    if run:
                        run.status = status
                        run.detail = detail
                        run.finished_at = datetime.utcnow()
                    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
                    if schedule and status == "failed" and schedule.action == "backup":
                        # Retry failed backups at the next tick by pulling next run closer.
                        schedule.next_run_at = datetime.utcnow() + timedelta(minutes=5)
            finally:
                self._inflight.discard(schedule_id)


scheduler = SchedulerService()
