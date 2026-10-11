"""FastAPI application factory and lifespan manager."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from config import settings
from logger import get_logger
from storage.database import init_db
from jobs.queue import job_manager
from jobs.runner import execute_build_job
from servers.manager import server_manager
from servers.scheduler import scheduler
from core.auth import bootstrap_admin
from bot.bot import start_telegram_bot, stop_telegram_bot
from web.routes import router as web_router
from web.routes_servers import router as host_router

logger = get_logger("app")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager handling startup and shutdown."""
    logger.info("Initializing Cyber Minecraft AI services...")
    
    # 1. Initialize Database (with additive migrations)
    init_db()
    
    # 2. Ensure an initial admin account exists
    bootstrap_admin()
    
    # 3. Start Build Queue Workers
    job_manager.start_workers(execute_build_job)
    
    # 4. Bring the Cyber Host manager online (start queue + monitoring)
    await server_manager.startup()

    # 5. Start the durable schedule service
    await scheduler.startup()
    
    # 6. Start Telegram Bot asynchronously
    await start_telegram_bot()
    
    logger.info(f"Cyber Minecraft AI is online and listening on {settings.HOST}:{settings.PORT}")
    yield
    
    # Clean shutdown
    logger.info("Shutting down Cyber Minecraft AI services...")
    await stop_telegram_bot()
    await scheduler.shutdown()
    await server_manager.shutdown()
    await job_manager.stop_workers()
    logger.info("All services cleanly terminated.")

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Production-ready AI-powered Minecraft Mod Creation and Server Hosting Platform",
    lifespan=lifespan
)

# Include web dashboard & API routes
app.include_router(web_router)
app.include_router(host_router)
