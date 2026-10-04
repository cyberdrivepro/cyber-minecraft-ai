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
        reload=settings.DEBUG
    )

if __name__ == "__main__":
    main()
