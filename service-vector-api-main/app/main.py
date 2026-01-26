import uvicorn
from .logger import setup_logger
from .api import app  # Re-export FastAPI app for Uvicorn CLI

logger = setup_logger(__name__)

def start_api():
    logger.info("Starting API server")
    uvicorn.run(
        "app.api:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )

if __name__ == "__main__":
    start_api()
