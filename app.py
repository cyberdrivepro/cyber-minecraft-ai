"""FastAPI application factory and lifespan manager."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from config import settings
from logger import get_logger
from storage.database import init_db
from jobs.queue import job_manager
from jobs.runner import execute_build_job
from bot.bot import start_telegram_bot, stop_telegram_bot
from web.routes import router as web_router

logger = get_logger("app")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager handling startup and shutdown."""
    logger.info("Initializing Cyber Minecraft AI Mod Builder services...")
    
    # 1. Initialize Database
    init_db()
    
    # 2. Start Build Queue Workers
    job_manager.start_workers(execute_build_job)
    
    # 3. Start Telegram Bot asynchronously
    await start_telegram_bot()
    
    logger.info(f"Cyber Minecraft AI is online and listening on {settings.HOST}:{settings.PORT}")
    yield
    
    # Clean shutdown
    logger.info("Shutting down Cyber Minecraft AI services...")
    await stop_telegram_bot()
    await job_manager.stop_workers()
    logger.info("All services cleanly terminated.")

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Production-ready AI-powered Minecraft Mod Creation Platform",
    lifespan=lifespan
)

# Include web dashboard & API routes
app.include_router(web_router)
