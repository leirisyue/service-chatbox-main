from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    My_GOOGLE_API_KEY: str

    class Config:
        env_file = ".env"

settings = Settings()
