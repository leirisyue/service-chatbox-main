import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    QWEN_EMBED_MODEL = os.getenv("QWEN_EMBED_MODEL")
    QWEN_API_BASE = os.getenv("QWEN_API_BASE")

    PG_HOST = os.getenv("PG_HOST")
    PG_PORT = os.getenv("PG_PORT")
    PG_USER = os.getenv("PG_USER")
    PG_PASSWORD = os.getenv("PG_PASSWORD")
    PG_DATABASE = os.getenv("PG_DATABASE")

    EMBEDDING_STORAGE_TYPE = os.getenv("EMBEDDING_STORAGE_TYPE", "vector").lower()

    APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT = int(os.getenv("APP_PORT", "8000"))

settings = Settings()
