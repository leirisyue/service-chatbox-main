from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from typing import ClassVar, Dict
import os
try:
    from sshtunnel import SSHTunnelForwarder
except ImportError:
    SSHTunnelForwarder = None

# Global tunnel holders for main DB and vector DB
_MAIN_DB_TUNNEL = None
_VECTOR_DB_TUNNEL = None

load_dotenv()

# Set Google Cloud credentials if provided
if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

class Settings(BaseSettings):
    # My_GOOGLE_API_KEY: str = os.getenv("My_GOOGLE_API_KEY", "localhost")
    GOOGLE_PROJECT_ID: str = os.getenv("GOOGLE_PROJECT_ID", "aa-aibuild")
    GOOGLE_LOCATION: str = os.getenv("GOOGLE_LOCATION", "us-central1")
    GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    
    # API settings
    API_URL: str = "http://127.0.0.1:8000"
    API_URL_CHATBOT: str = "http://127.0.0.1:8080"
    
    # Database vector settings
    # DB_NAME: str = "db_vector"
    # DB_USER: str = "postgres"
    # DB_PASSWORD: str = "postgres"
    # DB_HOST: str = "localhost"
    # DB_PORT: str = "5432"
    
    # Database description settings
    # DB_NAME_ORIGIN: str = "PTHSP"
    # DB_USER_ORIGIN: str = "postgres"
    # DB_PASSWORD_ORIGIN: str = "postgres"
    # DB_HOST_ORIGIN: str = "localhost"
    # DB_PORT_ORIGIN: str = "5432"
    
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    API_ENDPOINT: str = os.getenv("API_ENDPOINT", "https://aiplatform.googleapis.com")
    MODEL_ID: str = os.getenv("MODEL_ID", "gemini-2.5-flash")
    GENERATE_CONTENT_API: str = os.getenv("GENERATE_CONTENT_API", "generateContent")
    
    # Table names
    # MATERIALS_TABLE: str = "materials_qwen"
    MATERIALS_TABLE: str = "material_merge"
    MATERIALS_VIEW: str = "VIEW_MATERIAL_MERGE"
    
    PRODUCTS_TABLE: str = "products_qwen"
    
    PRODUCT_MATERIALS_TABLE: str = "product_materials"
    
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
    
    MAIN_DB_HOST: str = os.getenv("MAIN_DB_HOST", "localhost")
    MAIN_DB_PORT: str = os.getenv("MAIN_DB_PORT", "5432")
    MAIN_DB_USER: str = os.getenv("MAIN_DB_USER", "postgres")
    MAIN_DB_PASSWORD: str = os.getenv("MAIN_DB_PASSWORD", "postgres")
    MAIN_DB_DATABASE: str = os.getenv("MAIN_DB_DATABASE", "postgres")

    MAIN_DB_SSH_TUNNEL_ENABLED: bool = os.getenv("MAIN_DB_SSH_TUNNEL_ENABLED", "false").strip().lower() == "true"
    MAIN_DB_SSH_TUNNEL_HOST: str = os.getenv("MAIN_DB_SSH_TUNNEL_HOST", "")
    MAIN_DB_SSH_TUNNEL_PORT: int = int(os.getenv("MAIN_DB_SSH_TUNNEL_PORT", "22"))
    MAIN_DB_SSH_TUNNEL_USER: str = os.getenv("MAIN_DB_SSH_TUNNEL_USER", "")
    MAIN_DB_SSH_TUNNEL_PASSWORD: str = os.getenv("MAIN_DB_SSH_TUNNEL_PASSWORD", "")
    MAIN_DB_SSH_TUNNEL_LOCAL_PORT: int = int(os.getenv("MAIN_DB_SSH_TUNNEL_LOCAL_PORT", "15432"))

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

    _main_db_tunnel: ClassVar = None
    _vector_db_tunnel: ClassVar = None

    class Config:
        env_file = ".env"

    @property
    def DB_CONFIG(self) -> Dict[str, str]:
        """Get VECTOR DB configuration as dict (with optional SSH tunnel)."""
        tunnel = self._ensure_vector_db_tunnel

        if tunnel is not None:
            host = "127.0.0.1"
            port = tunnel.local_bind_port
        else:
            host = self.VECTOR_DB_HOST
            port = int(self.VECTOR_DB_PORT)

        return {
            "host": host,
            "port": port,
            "user": self.VECTOR_DB_USER,
            "password": self.VECTOR_DB_PASSWORD,
            "dbname": self.VECTOR_DB_DATABASE,
            "sslmode": "disable",
        }

    # @property
    # def DB_CONFIG_ORIGIN(self) -> Dict[str, str]:
    #     """Get origin database configuration as dict"""
    #     return {
    #         "dbname": self.DB_NAME_ORIGIN,
    #         "user": self.DB_USER_ORIGIN,
    #         "password": self.DB_PASSWORD_ORIGIN,
    #         "host": self.DB_HOST_ORIGIN,
    #         "port": self.DB_PORT_ORIGIN
    #     }
    @property
    def _ensure_main_db_tunnel(self):
        global _MAIN_DB_TUNNEL
        if not self.MAIN_DB_SSH_TUNNEL_ENABLED:
            return None
        if SSHTunnelForwarder is None:
            raise RuntimeError("sshtunnel package is required for SSH tunnel. Please install it with 'pip install sshtunnel'.")
        if _MAIN_DB_TUNNEL is not None:
            return _MAIN_DB_TUNNEL

        if not self.MAIN_DB_SSH_TUNNEL_HOST or not self.MAIN_DB_SSH_TUNNEL_USER:
            raise RuntimeError("self.MAIN_DB_SSH_TUNNEL_HOST và MAIN_DB_SSH_TUNNEL_USER phải được cấu hình trong .env khi bật MAIN_DB_SSH_TUNNEL_ENABLED.")

        try:
            tunnel = SSHTunnelForwarder(
                (self.MAIN_DB_SSH_TUNNEL_HOST, self.MAIN_DB_SSH_TUNNEL_PORT),
                ssh_username=self.MAIN_DB_SSH_TUNNEL_USER,
                ssh_password=self.MAIN_DB_SSH_TUNNEL_PASSWORD or None,
                remote_bind_address=(self.MAIN_DB_HOST, int(self.MAIN_DB_PORT)),
                local_bind_address=("127.0.0.1", 0),  # Let system choose available port
            )
            tunnel.start()
            _MAIN_DB_TUNNEL = tunnel
            print(f"✓ Main DB SSH tunnel started: 127.0.0.1:{tunnel.local_bind_port} -> {self.MAIN_DB_HOST}:{self.MAIN_DB_PORT}")
        except Exception as e:
            print(f"✗ Failed to start Main DB SSH tunnel: {e}")
            raise

        return _MAIN_DB_TUNNEL

    @property
    def _ensure_vector_db_tunnel(self):
        global _VECTOR_DB_TUNNEL
        if not self.VECTOR_DB_SSH_TUNNEL_ENABLED:
            return None
        if SSHTunnelForwarder is None:
            raise RuntimeError("sshtunnel package is required for SSH tunnel. Please install it with 'pip install sshtunnel'.")
        if _VECTOR_DB_TUNNEL is not None:
            return _VECTOR_DB_TUNNEL

        if not self.VECTOR_DB_SSH_TUNNEL_HOST or not self.VECTOR_DB_SSH_TUNNEL_USER:
            raise RuntimeError("VECTOR_DB_SSH_TUNNEL_HOST và VECTOR_DB_SSH_TUNNEL_USER phải được cấu hình trong .env khi bật VECTOR_DB_SSH_TUNNEL_ENABLED.")

        try:
            tunnel = SSHTunnelForwarder(
                (self.VECTOR_DB_SSH_TUNNEL_HOST, self.VECTOR_DB_SSH_TUNNEL_PORT),
                ssh_username=self.VECTOR_DB_SSH_TUNNEL_USER,
                ssh_password=self.VECTOR_DB_SSH_TUNNEL_PASSWORD or None,
                remote_bind_address=(self.VECTOR_DB_HOST, int(self.VECTOR_DB_PORT)),
                local_bind_address=("127.0.0.1", 0),  # Let system choose available port
            )
            tunnel.start()
            _VECTOR_DB_TUNNEL = tunnel
            print(f"✓ Vector DB SSH tunnel started: 127.0.0.1:{tunnel.local_bind_port} -> {self.VECTOR_DB_HOST}:{self.VECTOR_DB_PORT}")
        except Exception as e:
            print(f"✗ Failed to start Vector DB SSH tunnel: {e}")
            raise

        return _VECTOR_DB_TUNNEL

    @property
    def DB_CONFIG_ORIGIN(self) -> Dict[str, str]:
        tunnel = self._ensure_main_db_tunnel

        if tunnel is not None:
            host = "127.0.0.1"
            port = tunnel.local_bind_port
        else:
            host = self.MAIN_DB_HOST
            port = int(self.MAIN_DB_PORT)

        return {
            "host": host,
            "port": port,
            "user": self.MAIN_DB_USER,
            "password": self.MAIN_DB_PASSWORD,
            "dbname": self.MAIN_DB_DATABASE,
            "sslmode": "disable",
        }

settings = Settings()