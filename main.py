"""Primary server entrypoint for Hugging Face Spaces and local deployment."""
import uvicorn
from config import settings
from logger import get_logger

logger = get_logger("main")

def main():
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Hugging Face Spaces Port: {settings.PORT}")
    uvicorn.run(
        "app:app",
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
        reload=settings.DEBUG,
        # SSE console streams never end on their own; without this bound a
        # single open dashboard tab makes SIGTERM (systemctl stop/restart)
        # hang forever, blocking the auto-resume-on-boot flow.
        timeout_graceful_shutdown=10
    )

if __name__ == "__main__":
    main()
