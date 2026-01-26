import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    APP_PG_HOST = os.getenv("APP_PG_HOST", "localhost")
    APP_PG_USER = os.getenv("APP_PG_USER", "postgres")
    APP_PG_PASSWORD = os.getenv("APP_PG_PASSWORD", "postgres")
    APP_PG_DATABASE = os.getenv("APP_PG_DATABASE", "ultimate_advisor")
    APP_PG_PORT = int(os.getenv("APP_PG_PORT", "5432"))

    
    ORIGIN_DB_HOST = os.getenv("ORIGIN_DB_HOST", "localhost")
    ORIGIN_DB_PORT = int(os.getenv("ORIGIN_DB_PORT", "5432"))
    ORIGIN_DB_NAME = os.getenv("ORIGIN_DB_NAME", "PTHSP")
    ORIGIN_DB_USER = os.getenv("ORIGIN_DB_USER", "postgres")
    ORIGIN_DB_PASSWORD = os.getenv("ORIGIN_DB_PASSWORD", "postgres")
    ORIGIN_DB_SCHEMA = os.getenv("ORIGIN_DB_SCHEMA", "")

    APP_EMBEDDING_MODEL = os.getenv("APP_EMBEDDING_MODEL", "qwen3-embedding:latest")

    # embedding chunking (to avoid model context overflow)
    # Max characters per chunk sent to Ollama embeddings
    EMBEDDING_CHUNK_SIZE = int(os.getenv("EMBEDDING_CHUNK_SIZE", "3000"))
    # Overlap in characters between consecutive chunks
    EMBEDDING_CHUNK_OVERLAP = int(os.getenv("EMBEDDING_CHUNK_OVERLAP", "200"))

    # ollama
    OLLAMA_HOST = os.getenv("OLLAMA_HOST")
    QWEN_MODEL: str = "qwen3-embedding:latest"
    QWEN_EMBED_MODEL: str = "qwen3-embedding:latest"
    
    
    VECTOR_DB_HOST: str = os.getenv("VECTOR_DB_HOST", "localhost")
    VECTOR_DB_PORT: str = os.getenv("VECTOR_DB_PORT", "5432")
    VECTOR_DB_USER: str = os.getenv("VECTOR_DB_USER", "root")
    VECTOR_DB_PASSWORD: str = os.getenv("VECTOR_DB_PASSWORD", "123")
    VECTOR_DB_DATABASE: str = os.getenv("VECTOR_DB_DATABASE", "postgres")

    VECTOR_DB_SSH_TUNNEL_ENABLED: bool = os.getenv("VECTOR_DB_SSH_TUNNEL_ENABLED", "true").strip().lower() == "true"
    VECTOR_DB_SSH_TUNNEL_HOST: str = os.getenv("VECTOR_DB_SSH_TUNNEL_HOST", "192.168.4.102")
    VECTOR_DB_SSH_TUNNEL_PORT: int = int(os.getenv("VECTOR_DB_SSH_TUNNEL_PORT", "22"))
    VECTOR_DB_SSH_TUNNEL_USER: str = os.getenv("VECTOR_DB_SSH_TUNNEL_USER", "sysadmin")
    VECTOR_DB_SSH_TUNNEL_PASSWORD: str = os.getenv("VECTOR_DB_SSH_TUNNEL_PASSWORD", "123")
    VECTOR_DB_SSH_TUNNEL_LOCAL_PORT: int = int(os.getenv("VECTOR_DB_SSH_TUNNEL_LOCAL_PORT", "15432"))


settings = Settings()