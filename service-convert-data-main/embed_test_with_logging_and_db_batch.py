import os
import time
import json
import logging
from typing import List, Tuple, Any, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import requests

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

# Cấu hình SSH tunnel cho MAIN DB (tùy chọn)
# Nếu muốn script tự mở SSH tunnel:
#   MAIN_DB_SSH_TUNNEL_ENABLED=true
#   MAIN_DB_SSH_TUNNEL_HOST=192.168.4.41      # bastion SSH
#   MAIN_DB_SSH_TUNNEL_PORT=22                # cổng SSH
#   MAIN_DB_SSH_TUNNEL_USER=root              # user SSH
#   MAIN_DB_SSH_TUNNEL_PASSWORD=...           # mật khẩu SSH (hoặc dùng key riêng)
#   MAIN_DB_SSH_TUNNEL_LOCAL_PORT=15432       # cổng local forward tới MAIN_DB_HOST:MAIN_DB_PORT
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

# Kiểu lưu embedding trong DB: "vector" (pgvector) hoặc "jsonb"
EMBEDDING_STORAGE_TYPE = os.getenv("EMBEDDING_STORAGE_TYPE", "vector").lower()


# =========================
# 2. Logging setup
# =========================

def setup_logging(log_dir: str = "logs") -> str:
    os.makedirs(log_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(log_dir, f"embed_test_{timestamp}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler()
        ],
    )
    logging.info(f"Logging to {log_path}")
    return log_path


# =========================
# 3. Helper: make JSON-safe
# =========================

def to_jsonable(obj):
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    elif hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            return str(obj)
    else:
        try:
            json.dumps(obj)
            return obj
        except TypeError:
            return str(obj)


# =========================
# 4. Helper: token counting
# =========================
def estimate_tokens(texts: List[str], model_name: str = "gpt-4o-mini") -> int:
    if not texts:
        return 0

    if tiktoken is None:
        return sum(len(t.split()) for t in texts)

    try:
        enc = tiktoken.encoding_for_model(model_name)
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")

    total = 0
    for t in texts:
        total += len(enc.encode(t))
    return total


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

_MAIN_DB_TUNNEL = None

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

# =========================
# tạo bảng embedding dùng chung (nếu muốn gom bảng)
# ========================
def ensure_embedding_tables():
    conn = get_vector_db_connection()
    try:
        with conn.cursor() as cur:
            if EMBEDDING_STORAGE_TYPE == "vector":
                # cần extension vector
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS qwen_embeddings (
                        id SERIAL PRIMARY KEY,
                        source_table TEXT NOT NULL,
                        source_pk TEXT,
                        row_index INT NOT NULL,
                        text TEXT NOT NULL,
                        embedding VECTOR,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );
                    """
                )
            else:
                # lưu dạng JSONB
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS qwen_embeddings (
                        id SERIAL PRIMARY KEY,
                        source_table TEXT NOT NULL,
                        source_pk TEXT,
                        row_index INT NOT NULL,
                        text TEXT NOT NULL,
                        embedding JSONB,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    );
                    """
                )
        conn.commit()
    finally:
        conn.close()


def insert_embedding_rows(
    model: str,
    table_name: str,
    texts: List[str],
    raw_rows: List[Any],
    embeddings: List[List[float]],
):
    if not embeddings:
        logging.info(f"No embeddings to insert for model={model}")
        return

    # Xác định bảng đích trong VECTOR_DB_DATABASE
    # Hiện tại script batch này chỉ sử dụng Qwen
    if model == "qwen":
        target_table = "qwen_embeddings"
    else:
        raise ValueError(f"Unsupported model type for batch script: {model}")

    # Đảm bảo bảng embedding đã được tạo (nếu chưa có)
    ensure_embedding_tables()

    conn = get_vector_db_connection()
    try:
        with conn.cursor() as cur:
            for idx, (text, row, emb) in enumerate(zip(texts, raw_rows, embeddings)):
                # cố gắng lấy khóa chính 'id' từ row nếu có
                source_pk: Optional[str] = None
                if isinstance(row, dict):
                    if "id" in row:
                        source_pk = str(row["id"])
                    elif "ID" in row:
                        source_pk = str(row["ID"])

                if EMBEDDING_STORAGE_TYPE == "vector":
                    # chèn dạng ARRAY -> VECTOR (pgvector)
                    # cú pháp: embedding = %s::vector
                    emb_str = "[" + ",".join(str(float(x)) for x in emb) + "]"
                    sql = f"""
                        INSERT INTO {target_table} (source_table, source_pk, row_index, text, embedding)
                        VALUES (%s, %s, %s, %s, %s::vector)
                    """
                    params = (table_name, source_pk, idx, text, emb_str)
                else:
                    # lưu JSONB
                    sql = f"""
                        INSERT INTO {target_table} (source_table, source_pk, row_index, text, embedding)
                        VALUES (%s, %s, %s, %s, %s::jsonb)
                    """
                    params = (table_name, source_pk, idx, text, json.dumps(emb))

                cur.execute(sql, params)

        conn.commit()
        logging.info(
            f"Inserted {len(embeddings)} rows into {target_table} "
            f"(storage_type={EMBEDDING_STORAGE_TYPE})"
        )
    finally:
        conn.close()


def fetch_rows_from_table(
    table_name: str,
    limit: int = 1000,
) -> Tuple[List[str], List[Any]]:
    conn = get_main_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = f"SELECT * FROM public.\"{table_name}\" LIMIT %s;"
            logging.info(f"Executing query: {query} with limit={limit}")
            cur.execute(query, (limit,))
            rows = cur.fetchall()

            texts = []
            for row in rows:
                parts = []
                for col, val in row.items():
                    if val is None:
                        v_str = ""
                    else:
                        v_str = str(val)
                    parts.append(f"{col}={v_str}")
                row_text = " | ".join(parts)
                texts.append(row_text)

        logging.info(f"Fetched {len(texts)} rows from table '{table_name}'.")
        return texts, rows
    finally:
        conn.close()



# =========================
# 7. Qwen embedding + logging + DB save
# =========================
def embed_with_qwen(
    table_name: str,
    texts: List[str],
    raw_rows: List[Any],
    output_dir: str,
) -> Tuple[List[List[float]], float, int, str]:
    if not texts:
        return [], 0.0, 0, ""

    os.makedirs(output_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    outfile = os.path.join(
        output_dir,
        f"{table_name}_qwen_embeddings_{timestamp}.jsonl"
    )

    url = f"{QWEN_API_BASE}/api/embeddings"
    embeddings: List[List[float]] = []
    start = time.time()
    with open(outfile, "w", encoding="utf-8") as f:
        for idx, (t, row) in enumerate(zip(texts, raw_rows)):
            payload = {
                "model": QWEN_EMBED_MODEL,
                "prompt": t,
            }
            resp = requests.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            emb = data.get("embedding") or data.get("data", [{}])[0].get("embedding")
            if emb is None:
                raise ValueError(f"Qwen API response không có 'embedding': {data}")
            embeddings.append(emb)

            record = {
                "row_index": idx,
                "text": t,
                "raw_row": to_jsonable(row),
                "embedding": to_jsonable(emb),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    elapsed = time.time() - start
    token_est = estimate_tokens(texts)

    logging.info(
        f"Qwen embeddings done: {len(embeddings)} rows, "
        f"time={elapsed:.2f}s, tokens≈{token_est}, output={outfile}"
    )

    # Lưu vào DB
    insert_embedding_rows("qwen", table_name, texts, raw_rows, embeddings)

    return embeddings, elapsed, token_est, outfile


# =========================
# 8.1 batch fetch rows
# =========================
def fetch_rows_batch(
    table_name: str,
    limit: int,
    offset: int,
) -> Tuple[List[str], List[Any]]:
    conn = get_main_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = f"""
                SELECT *
                FROM public."{table_name}"
                ORDER BY id
                LIMIT %s OFFSET %s
            """
            cur.execute(query, (limit, offset))
            rows = cur.fetchall()

            texts = []
            for row in rows:
                parts = []
                for col, val in row.items():
                    parts.append(f"{col}={'' if val is None else val}")
                texts.append(" | ".join(parts))

        return texts, rows
    finally:
        conn.close()


# =========================
# 8. Main test
# =========================
def run_test(table_name: str, limit: int = 1000, batch_size: int = 100):
    logging.info(
        f"Starting test for table='{table_name}', limit={limit}, batch={batch_size}"
    )

    # ensure_embedding_tables()

    output_dir = "embeddings_output"
    os.makedirs(output_dir, exist_ok=True)

    offset = 0
    total_processed = 0

    while total_processed < limit:
        current_limit = min(batch_size, limit - total_processed)

        texts, raw_rows = fetch_rows_batch(
            table_name,
            limit=current_limit,
            offset=offset,
        )

        if not texts:
            break

        logging.info(
            f"Processing batch offset={offset}, size={len(texts)}"
        )

        # =====================
        # Qwen
        # =====================
        embed_with_qwen(
            table_name,
            texts,
            raw_rows,
            output_dir,
        )

        offset += len(texts)
        total_processed += len(texts)

        logging.info(
            f"Batch done. Total processed: {total_processed}/{limit}"
        )

    logging.info("=== ALL DONE ===")




if __name__ == "__main__":
    import argparse

    log_file = setup_logging()

    parser = argparse.ArgumentParser(
        description="Test embedding từ Postgres table bằng  Qwen, có log, file JSONL và lưu DB"
    )
    parser.add_argument("--table", required=True, help="Tên bảng trong Postgres")
    parser.add_argument("--limit", type=int, default=1000, help="Số dòng tối đa")
    args = parser.parse_args()

    run_test(args.table, args.limit)