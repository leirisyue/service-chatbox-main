import os
import logging
import psycopg2
from dotenv import load_dotenv


from embed_test_with_logging_and_db_batch import setup_logging

try:
    from sshtunnel import SSHTunnelForwarder
except ImportError:
    SSHTunnelForwarder = None

try:
    import tiktoken
except ImportError:
    tiktoken = None


# =========================
# 1. Load environment
# =========================
load_dotenv()

QWEN_EMBED_MODEL = os.getenv("QWEN_EMBED_MODEL", "qwen3-embedding:latest")
QWEN_API_BASE = os.getenv("QWEN_API_BASE", "http://localhost:11434")  # ví dụ Ollama

MAIN_DB_HOST = os.getenv("MAIN_DB_HOST", "localhost")
MAIN_DB_PORT = os.getenv("MAIN_DB_PORT", "5432")
MAIN_DB_USER = os.getenv("MAIN_DB_USER", "postgres")
MAIN_DB_PASSWORD = os.getenv("MAIN_DB_PASSWORD", "postgres")
MAIN_DB_DATABASE = os.getenv("MAIN_DB_DATABASE", "postgres")

MAIN_DB_SSH_TUNNEL_ENABLED = os.getenv("MAIN_DB_SSH_TUNNEL_ENABLED", "false").strip().lower() == "true"
MAIN_DB_SSH_TUNNEL_HOST = os.getenv("MAIN_DB_SSH_TUNNEL_HOST", "")
MAIN_DB_SSH_TUNNEL_PORT = int(os.getenv("MAIN_DB_SSH_TUNNEL_PORT", "22"))
MAIN_DB_SSH_TUNNEL_USER = os.getenv("MAIN_DB_SSH_TUNNEL_USER", "")
MAIN_DB_SSH_TUNNEL_PASSWORD = os.getenv("MAIN_DB_SSH_TUNNEL_PASSWORD", "")
MAIN_DB_SSH_TUNNEL_LOCAL_PORT = int(os.getenv("MAIN_DB_SSH_TUNNEL_LOCAL_PORT", "15432"))

VECTOR_DB_HOST = os.getenv("VECTOR_DB_HOST", "localhost")
VECTOR_DB_PORT = os.getenv("VECTOR_DB_PORT", "5432")
VECTOR_DB_USER = os.getenv("VECTOR_DB_USER", "postgres")
VECTOR_DB_PASSWORD = os.getenv("VECTOR_DB_PASSWORD", "postgres")
VECTOR_DB_DATABASE = os.getenv("VECTOR_DB_DATABASE", "postgres")
FETCH_DB_DATABASE = os.getenv("FETCH_DB_DATABASE", "postgres")

# Kiểu lưu embedding trong DB: "vector" (pgvector) hoặc "jsonb"
EMBEDDING_STORAGE_TYPE = os.getenv("EMBEDDING_STORAGE_TYPE", "vector").lower()


# =========================
# 5. Postgres helpers
# =========================

_MAIN_DB_TUNNEL = None

def get_vector_db_connection():
    conn = psycopg2.connect(
        host=VECTOR_DB_HOST,
        port=VECTOR_DB_PORT,
        user=VECTOR_DB_USER,
        password=VECTOR_DB_PASSWORD,
        dbname=VECTOR_DB_DATABASE,
    )
    return conn

def get_fetch_db_connection():
    conn = psycopg2.connect(
        host=VECTOR_DB_HOST,
        port=VECTOR_DB_PORT,
        user=VECTOR_DB_USER,
        password=VECTOR_DB_PASSWORD,
        dbname=FETCH_DB_DATABASE,
    )
    return conn

def _ensure_main_db_tunnel():
    global _MAIN_DB_TUNNEL
    if not MAIN_DB_SSH_TUNNEL_ENABLED:
        return None
    if SSHTunnelForwarder is None:
        raise RuntimeError("sshtunnel package is required for SSH tunnel. Please install it with 'pip install sshtunnel'.")
    if _MAIN_DB_TUNNEL is not None:
        return _MAIN_DB_TUNNEL

    if not MAIN_DB_SSH_TUNNEL_HOST or not MAIN_DB_SSH_TUNNEL_USER:
        raise RuntimeError("MAIN_DB_SSH_TUNNEL_HOST và MAIN_DB_SSH_TUNNEL_USER phải được cấu hình trong .env khi bật MAIN_DB_SSH_TUNNEL_ENABLED.")

    tunnel = SSHTunnelForwarder(
        (MAIN_DB_SSH_TUNNEL_HOST, MAIN_DB_SSH_TUNNEL_PORT),
        ssh_username=MAIN_DB_SSH_TUNNEL_USER,
        ssh_password=MAIN_DB_SSH_TUNNEL_PASSWORD or None,
        remote_bind_address=(MAIN_DB_HOST, int(MAIN_DB_PORT)),
        local_bind_address=("127.0.0.1", MAIN_DB_SSH_TUNNEL_LOCAL_PORT),
    )
    tunnel.start()
    _MAIN_DB_TUNNEL = tunnel
    logging.info(
        f"SSH tunnel started to {MAIN_DB_HOST}:{MAIN_DB_PORT} via "
        f"{MAIN_DB_SSH_TUNNEL_HOST}:{MAIN_DB_SSH_TUNNEL_PORT}, local port={tunnel.local_bind_port}"
    )
    return _MAIN_DB_TUNNEL

def get_main_db_connection():
    tunnel = _ensure_main_db_tunnel()

    if tunnel is not None:
        host = "127.0.0.1"
        port = tunnel.local_bind_port
    else:
        host = MAIN_DB_HOST
        port = int(MAIN_DB_PORT)

    conn = psycopg2.connect(
        host=host,
        port=port,
        user=MAIN_DB_USER,
        password=MAIN_DB_PASSWORD,
        dbname=MAIN_DB_DATABASE,
        sslmode="disable",
    )
    return conn

def map_postgres_type(data_type, udt_name):
    if data_type == "integer":
        return "INTEGER"
    if data_type == "bigint":
        return "BIGINT"
    if data_type == "text":
        return "TEXT"
    if data_type == "character varying":
        return "VARCHAR"
    if data_type == "timestamp without time zone":
        return "TIMESTAMP"
    if data_type == "timestamp with time zone":
        return "TIMESTAMPTZ"
    if data_type == "boolean":
        return "BOOLEAN"

    # fallback
    return udt_name.upper()
