import os
import time
import json
import logging
from typing import List, Tuple, Any

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import google.generativeai as genai
import requests

try:
    import tiktoken
except ImportError:
    tiktoken = None


# =========================
# 1. Load environment
# =========================
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "models/text-embedding-004")

QWEN_EMBED_MODEL = os.getenv("QWEN_EMBED_MODEL", "qwen3-embedding:latest")
QWEN_API_BASE = os.getenv("QWEN_API_BASE", "http://localhost:11434")  # ví dụ Ollama

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "postgres")
PG_DATABASE = os.getenv("PG_DATABASE", "postgres")


# =========================
# 2. Logging setup
# =========================

def setup_logging(log_dir: str = "logs") -> str:
    """
    Tạo thư mục logs/ nếu chưa có, tạo file log với timestamp.
    Trả về đường dẫn file log.
    """
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
    """
    Chuẩn hóa obj để json.dumps không bị lỗi:
    - dict/list/tuple -> xử lý đệ quy
    - các kiểu có isoformat (datetime, date, ...) -> dùng isoformat()
    - kiểu khác không serializable -> str(obj)
    """
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    # datetime, date, vv... thường có isoformat
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
    """
    Ước lượng tổng số token của 1 list text.
    Dùng tiktoken (gần đúng GPT). Nếu không có tiktoken, fallback sang đếm từ.
    """
    if not texts:
        return 0

    if tiktoken is None:
        # đơn giản: token ≈ số từ
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
# 5. Postgres: fetch rows
# =========================
def fetch_rows_from_table(
    table_name: str,
    limit: int = 1000,
) -> Tuple[List[str], List[Any]]:
    """
    Lấy tối đa `limit` dòng từ `table_name`, trả về:
    - texts: list[str] là chuỗi đã được concat tất cả các cột
    - raw_rows: list[dict] (RealDictCursor)
    """
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=PG_DATABASE,
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            query = f'SELECT * FROM public."{table_name}" LIMIT %s;'
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
# 6. Gemini embedding + logging
# =========================
def embed_with_gemini(
    texts: List[str],
    raw_rows: List[Any],
    output_dir: str,
    table_name: str,
) -> Tuple[List[List[float]], float, int, str]:
    """
    Gọi Gemini embedding.
    Ghi lại từng dòng + vector vào file JSONL.
    Trả về:
      - embeddings: list of vectors
      - elapsed: thời gian (giây)
      - token_est: ước lượng số token input
      - output_path: đường dẫn file JSONL
    """
    if not texts:
        return [], 0.0, 0, ""

    os.makedirs(output_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    outfile = os.path.join(
        output_dir,
        f"{table_name}_gemini_embeddings_{timestamp}.jsonl"
    )

    genai.configure(api_key=GEMINI_API_KEY)

    embeddings = []
    start = time.time()
    with open(outfile, "w", encoding="utf-8") as f:
        for idx, (t, row) in enumerate(zip(texts, raw_rows)):
            resp = genai.embed_content(
                model=GEMINI_EMBED_MODEL,
                content=t,
            )
            emb = resp["embedding"] if isinstance(resp, dict) else resp.embedding
            embeddings.append(emb)

            record = {
                "row_index": idx,
                "text": t,
                "raw_row": to_jsonable(row),     # xử lý datetime, vv...
                "embedding": to_jsonable(emb),   # đảm bảo JSON-safe
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    elapsed = time.time() - start
    token_est = estimate_tokens(texts)
    logging.info(
        f"Gemini embeddings done: {len(embeddings)} rows, "
        f"time={elapsed:.2f}s, tokens≈{token_est}, output={outfile}"
    )
    return embeddings, elapsed, token_est, outfile


# =========================
# 7. Qwen embedding + logging
# =========================
def embed_with_qwen(
    texts: List[str],
    raw_rows: List[Any],
    output_dir: str,
    table_name: str,
) -> Tuple[List[List[float]], float, int, str]:
    """
    Gọi Qwen embedding qua API kiểu Ollama:
      POST /api/embeddings
      {
        "model": "qwen3-embedding:latest",
        "prompt": "text"
      }

    Ghi từng dòng + vector vào JSONL.
    """
    if not texts:
        return [], 0.0, 0, ""

    os.makedirs(output_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    outfile = os.path.join(
        output_dir,
        f"{table_name}_qwen_embeddings_{timestamp}.jsonl"
    )

    url = f"{QWEN_API_BASE}/api/embeddings"
    embeddings = []
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
    return embeddings, elapsed, token_est, outfile


# =========================
# 8. Main test
# =========================
def run_test(table_name: str, limit: int = 1000):
    logging.info(f"Starting test for table='{table_name}', limit={limit}")
    texts, raw_rows = fetch_rows_from_table(table_name, limit=limit)
    logging.info(f"Got {len(texts)} rows to embed.")

    output_dir = "embeddings_output"
    os.makedirs(output_dir, exist_ok=True)

    # Test Gemini
    logging.info("=== Start Gemini embedding ===")
    gem_embs, gem_time, gem_tokens, gem_file = embed_with_gemini(
        texts, raw_rows, output_dir, table_name
    )
    logging.info(f"Gemini - vectors: {len(gem_embs)}, time={gem_time:.2f}s, tokens≈{gem_tokens}")

    # Test Qwen
    logging.info("=== Start Qwen embedding ===")
    qwen_embs, qwen_time, qwen_tokens, qwen_file = embed_with_qwen(
        texts, raw_rows, output_dir, table_name
    )
    logging.info(f"Qwen  - vectors: {len(qwen_embs)}, time={qwen_time:.2f}s, tokens≈{qwen_tokens}")

    # So sánh sơ bộ
    logging.info("=== Summary ===")
    logging.info(f"Rows: {len(texts)}")
    logging.info(f"Gemini: time={gem_time:.2f}s, tokens≈{gem_tokens}, file={gem_file}")
    logging.info(f"Qwen : time={qwen_time:.2f}s, tokens≈{qwen_tokens}, file={qwen_file}")

    print("\n=== Summary ===")
    print(f"Rows: {len(texts)}")
    print(f"Gemini: time={gem_time:.2f}s, tokens≈{gem_tokens}, file={gem_file}")
    print(f"Qwen : time={qwen_time:.2f}s, tokens≈{qwen_tokens}, file={qwen_file}")


if __name__ == "__main__":
    import argparse

    log_file = setup_logging()

    parser = argparse.ArgumentParser(
        description="Test embedding từ Postgres table bằng Gemini & Qwen, có ghi log + lưu vector"
    )
    parser.add_argument("--table", required=True, help="Tên bảng trong Postgres")
    parser.add_argument("--limit", type=int, default=1000, help="Số dòng tối đa")
    args = parser.parse_args()

    run_test(args.table, args.limit)