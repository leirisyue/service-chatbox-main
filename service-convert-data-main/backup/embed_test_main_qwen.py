import os
import time
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
# 2. Helper: token counting
# =========================
def estimate_tokens(texts: List[str], model_name: str = "gpt-4o-mini") -> int:
    """
    Ước lượng tổng số token của 1 list text.
    Ở đây dùng tiktoken (gần đúng cho GPT style). Nếu không có tiktoken, fallback sang đếm từ.
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
# 3. Postgres: fetch rows
# =========================
def fetch_rows_from_table(
    table_name: str,
    limit: int = 1000,
) -> Tuple[List[str], List[Any]]:
    """
    Lấy tối đa `limit` dòng từ `table_name`, trả về:
    - texts: list[str] là chuỗi đã được concat tất cả các cột
    - raw_rows: list[dict] hoặc tuple (tuỳ cursor) để nếu muốn debug
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
            # Lấy tất cả cột: SELECT * FROM table
            query = f'SELECT * FROM public."{table_name}" LIMIT %s;'
            cur.execute(query, (limit,))
            rows = cur.fetchall()

            texts = []
            for row in rows:
                # row là dict: {col: value}
                # Chuyển mỗi cột thành "col=value" rồi nối lại
                parts = []
                for col, val in row.items():
                    if val is None:
                        v_str = ""
                    else:
                        v_str = str(val)
                    parts.append(f"{col}={v_str}")
                row_text = " | ".join(parts)
                texts.append(row_text)

        return texts, rows
    finally:
        conn.close()


# =========================
# 4. Gemini embedding
# =========================
def embed_with_gemini(texts: List[str]) -> Tuple[List[List[float]], float, int]:
    """
    Gọi Gemini embedding (genai.embed_content).
    Trả về:
      - embeddings: list of vectors
      - elapsed: thời gian (giây)
      - token_est: ước lượng số token input
    """
    if not texts:
        return [], 0.0, 0

    genai.configure(api_key=GEMINI_API_KEY)

    # Gemini embed_content có thể embed batch, nhưng thường embed từng cái cho đơn giản test.
    embeddings = []
    start = time.time()
    for t in texts:
        resp = genai.embed_content(
            model=GEMINI_EMBED_MODEL,
            content=t,
        )
        # resp.embedding là list[float]
        embeddings.append(resp["embedding"] if isinstance(resp, dict) else resp.embedding)
    elapsed = time.time() - start

    token_est = estimate_tokens(texts)
    return embeddings, elapsed, token_est


# =========================
# 5. Qwen embedding (Ollama HTTP demo)
# =========================
def embed_with_qwen(texts: List[str]) -> Tuple[List[List[float]], float, int]:
    """
    Ví dụ gọi Qwen embedding qua API dạng Ollama:
      POST /api/embeddings
      {
        "model": "qwen3-embedding:latest",
        "prompt": "text"
      }

    Nếu bạn dùng API khác (OpenAI-like, vLLM,...), hãy sửa phần này cho phù hợp.
    """
    if not texts:
        return [], 0.0, 0

    url = f"{QWEN_API_BASE}/api/embeddings"
    embeddings = []
    start = time.time()
    for t in texts:
        payload = {
            "model": QWEN_EMBED_MODEL,
            "prompt": t,
        }
        resp = requests.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        # Ollama thường trả { "embedding": [float, ...] }
        emb = data.get("embedding") or data.get("data", [{}])[0].get("embedding")
        if emb is None:
            raise ValueError(f"Qwen API response không có 'embedding': {data}")
        embeddings.append(emb)
    elapsed = time.time() - start

    token_est = estimate_tokens(texts)
    return embeddings, elapsed, token_est


# =========================
# 6. Main test
# =========================
def run_test(table_name: str, limit: int = 1000):
    print(f"Đang lấy tối đa {limit} dòng từ bảng '{table_name}' ...")
    texts, raw_rows = fetch_rows_from_table(table_name, limit=limit)
    print(f"Lấy được {len(texts)} dòng.")

    # Test Gemini
    print("\n=== Test Gemini embedding ===")
    gem_embs, gem_time, gem_tokens = embed_with_gemini(texts)
    print(f"Gemini - số vector: {len(gem_embs)}")
    if gem_embs:
        print(f"Gemini - kích thước vector: {len(gem_embs[0])}")
    print(f"Gemini - thời gian: {gem_time:.2f} s")
    print(f"Gemini - ước lượng tokens input: {gem_tokens}")

    # Test Qwen
    print("\n=== Test Qwen embedding ===")
    qwen_embs, qwen_time, qwen_tokens = embed_with_qwen(texts)
    print(f"Qwen  - số vector: {len(qwen_embs)}")
    if qwen_embs:
        print(f"Qwen  - kích thước vector: {len(qwen_embs[0])}")
    print(f"Qwen  - thời gian: {qwen_time:.2f} s")
    print(f"Qwen  - ước lượng tokens input: {qwen_tokens}")

    # So sánh sơ bộ
    print("\n=== So sánh tổng quan ===")
    print(f"Số dòng: {len(texts)}")
    print(f"Gemini: time={gem_time:.2f}s, tokens≈{gem_tokens}")
    print(f"Qwen : time={qwen_time:.2f}s, tokens≈{qwen_tokens}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test embedding từ Postgres table bằng Gemini & Qwen")
    parser.add_argument("--table", required=True, help="Tên bảng trong Postgres")
    parser.add_argument("--limit", type=int, default=1000, help="Số dòng tối đa")
    args = parser.parse_args()

    run_test(args.table, args.limit)