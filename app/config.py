from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
import os

class Settings(BaseSettings):
    # Database
    APP_PG_HOST:str = os.getenv("APP_PG_HOST", "localhost")
    APP_PG_USER:str = os.getenv("APP_PG_USER", "postgres")
    APP_PG_PASSWORD:str = os.getenv("APP_PG_PASSWORD", "postgres")
    APP_PG_DATABASE:str = os.getenv("APP_PG_DATABASE", "ultimate_advisor")
    APP_PG_PORT: int = int(os.getenv("APP_PG_PORT", "5432"))

    # Ollama
    OLLAMA_HOST: str = os.getenv("OLLAMA_URL")
    APP_EMBEDDING_MODEL:str = os.getenv("APP_EMBEDDING_MODEL", "qwen3-embedding:latest")

    # Gemini
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY")
    APP_GEMINI_MODEL: str = os.getenv("APP_GEMINI_MODEL", "gemini-2.0-flash")

    # App
    # Pydantic will coerce env strings to the annotated types
    APP_RELOAD: bool = os.getenv("APP_RELOAD", "false") in ["1", "true", "True", "TRUE"]
    APP_TOP_K: int = int(os.getenv("APP_TOP_K", "5"))
    APP_MIN_SCORE: float = float(os.getenv("APP_MIN_SCORE", "0.3"))
    APP_LOG_DIR: str = os.getenv("APP_LOG_DIR", "logs")

    APP_TABLE_SCHEMAS_JSON: str = Field(default="")

    # model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)
    model_config = SettingsConfigDict(env_file=".env.locally", case_sensitive=False)

settings = Settings()