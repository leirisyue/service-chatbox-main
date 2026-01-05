from fastapi import FastAPI
from app.api import router
from app.core.config import settings
import uvicorn
from .core.logging import setup_logging

setup_logging()

app = FastAPI(
    title="Embedding API",
    description="Qwen / Gemini Embedding Service",
    version="1.0.0",
)

app.include_router(router)
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
    
if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True,
    )
