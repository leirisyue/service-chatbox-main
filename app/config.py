from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # Database
    APP_PG_HOST: str = Field(default="host.docker.internal")
    APP_PG_USER: str = Field(default="postgres")
    APP_PG_PASSWORD: str = Field(default="postgres")
    APP_PG_DATABASE: str = Field(default="ultimate_advisor")
    APP_PG_PORT: int = Field(default=5432)

    # Ollama
    OLLAMA_HOST: str = Field(default="http://host.docker.internal:11434")
    APP_EMBEDDING_MODEL: str = Field(default="nomic-embed-text:latest")

    # Gemini
    GOOGLE_API_KEY: str = Field(default="", description="API key từ Google AI Studio")
    APP_GEMINI_MODEL: str = Field(default="gemini-1.5-flash")

    # App
    APP_RELOAD: bool = Field(default=False)
    APP_TOP_K: int = Field(default=5)
    APP_MIN_SCORE: float = Field(default=0.3)

    # Optional: JSON mô tả schema các bảng để selector dùng
    # Ví dụ:
    # APP_TABLE_SCHEMAS_JSON=[
    #   {"schema":"public","table":"customers","description":"Thông tin khách hàng..."},
    #   {"schema":"public","table":"products","description":"Thông tin sản phẩm..."}
    # ]
    APP_TABLE_SCHEMAS_JSON: str = Field(default="")

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

settings = Settings()