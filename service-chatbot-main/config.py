from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from typing import ClassVar, Dict

load_dotenv()

class Settings(BaseSettings):
    My_GOOGLE_API_KEY: str = ""  # Make optional with default value
    
    # API settings
    API_URL: str = "http://127.0.0.1:8000"
    API_URL_CHATBOT: str = "http://127.0.0.1:8080"
    
    # Database settings
    DB_NAME: str = "db_vector"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres"
    DB_HOST: str = "localhost"
    DB_PORT: str = "5432"
    
    # Table names
    MATERIALS_TABLE: str = "materials_qwen"
    
    # Qwen Embedding settings
    QWEN_HOST: str = "192.168.4.102"
    QWEN_PORT: int = 11434
    QWEN_TIMEOUT: int = 30
    QWEN_MODEL: str = "qwen3-embedding:latest"
    QWEN_EMBED_MODEL: str = "qwen3-embedding:latest"
    OLLAMA_HOST: str = "http://192.168.4.102:11434"
    
    # Similarity threshold settings
    SIMILARITY_THRESHOLD_LOW: float = 0.3  # For broad matching (product search, textfunc)
    SIMILARITY_THRESHOLD_MEDIUM: float = 0.35  # For ranking
    SIMILARITY_THRESHOLD_HIGH: float = 0.7  # For feedback matching
    SIMILARITY_THRESHOLD_VERY_HIGH: float = 0.85  # For strict matching

    class Config:
        env_file = ".env"

    @property
    def DB_CONFIG(self) -> Dict[str, str]:
        """Get database configuration as dict"""
        return {
            "dbname": self.DB_NAME,
            "user": self.DB_USER,
            "password": self.DB_PASSWORD,
            "host": self.DB_HOST,
            "port": self.DB_PORT
        }

settings = Settings()