import uvicorn
import os
import logging
from logging.handlers import TimedRotatingFileHandler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.logger import setup_logger

logger = setup_logger(__name__)

LOG_DIR = os.getenv("LOG_DIR", "/app/logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Initialize logging early
def setup_logging():
    os.makedirs("logs", exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    log_file = os.path.join(LOG_DIR, "app.log")
    fh = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    fh.setLevel(logging.INFO)
    fh.setFormatter(fmt)

    logger.handlers.clear()
    logger.addHandler(ch)
    logger.addHandler(fh)

setup_logging()
log = logging.getLogger("startup")

# Log environment basics to help diagnose
def log_env_summary():
    try:
        from app.config import settings
        logger.info("Environment summary: PG=%s:%s DB=%s OLLAMA_HOST=%s EMB_MODEL=%s GEMINI_MODEL=%s RELOAD=%s",
                 settings.APP_PG_HOST, settings.APP_PG_PORT, settings.APP_PG_DATABASE,
                 settings.OLLAMA_HOST, settings.APP_EMBEDDING_MODEL,
                 settings.APP_GEMINI_MODEL, settings.APP_RELOAD)
    except Exception as e:
        logger.exception("Failed to read settings: %s", e)

log_env_summary()

app = FastAPI(
    title="RAG Chatbot Service",
    version="0.1.3",
    description="Service Chatbot cho mô hình RAG: OCR ảnh, embedding với Ollama, truy vấn Postgres và trả lời bằng Gemini.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import router after logging and settings
try:
    from app.routers.rag import rag_router
    app.include_router(rag_router, tags=["RAG"])
    logger.info("Router mounted successfully.")
except Exception as e:
    logger.exception("Failed to mount router: %s", e)
    # Fail fast so the stack trace is printed clearly
    raise

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # disable reload in container; logging handles rotation
        log_config=None,
    )