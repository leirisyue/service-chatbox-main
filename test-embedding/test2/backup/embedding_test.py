import os
import psycopg2
import psycopg2.extras
import numpy as np
import tiktoken
import requests
from typing import List, Dict, Any

# Nếu dùng Google Generative AI (python client)
import google.generativeai as genai


# -----------------------------
# 1. Helper: đọc biến môi trường
# -----------------------------
def get_pg_connection():
    conn = psycopg2.connect(
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
        dbname=os.getenv("PGDATABASE"),
        user=os.getenv("PGUSER"),
        password=os.getenv("PGPASSWORD"),
    )
    return conn


# -----------------------------
# 2. Helper: token counter (ước lượng)
#    - Dùng encoding "cl100k_base" (tương đối phổ biến)
# -----------------------------
_enc = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_enc.encode(text))


# -----------------------------
# 3. Chuẩn hóa 1 record (row) -> text
#    - Lấy tất cả các cột trong bảng
#    - row là dict {column: value}
# -----------------------------
def row_to_text(row: Dict[str, Any]) -> str:
    parts = []
    for col, val in row.items():
        parts.append(f"{col}={val}")
    return " | ".join(parts)


# -----------------------------
# 4. Gọi Google GenAI: text-embedding-004
# -----------------------------
def embed_with_google(texts: List[str]) -> List[List[float]]:
    api_key = os.environ["GOOGLE_API_KEY"]
    genai.configure(api_key=api_key)

    model_name = "models/text-embedding-004"

    # Google GenAI cho phép batch, nhưng tuỳ mức limit,
    # ở đây demo batch 1-nho nhỏ cho rõ.
    embeddings = []
    for t in texts:
        res = genai.embed_content(
            model=model_name,
            content=t,
        )
        vec = res["embedding"]
        embeddings.append(vec)

    return embeddings


# -----------------------------
# 5. Gọi Qwen3-embedding:latest (OpenAI-compatible giả định)
#    - Nếu bạn có SDK riêng của Qwen thì chỉnh lại phần này.
# -----------------------------
def embed_with_qwen(texts: List[str]) -> List[List[float]]:
    api_base = os.environ["QWEN_API_BASE"]
    api_key = os.environ["QWEN_API_KEY"]
    model = "qwen3-embedding:latest"

    url = f"{api_base}/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Batch 1 lần cho nhanh
    payload = {
        "model": model,
        "input": texts,
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    # Chuẩn theo format OpenAI /v1/embeddings
    embeddings = [item["embedding"] for item in data["data"]]
    return embeddings


# -----------------------------
# 6. Hàm chính: đọc dữ liệu từ table, tạo embedding, đo thống kê
# -----------------------------
def test_embeddings(table_name: str, limit: int = 1000):
    # 1. Lấy dữ liệu từ Postgres
    conn = get_pg_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    query = f'SELECT * FROM "{table_name}" LIMIT %s'
    cur.execute(query, (limit,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        print("Không có dữ liệu trong bảng hoặc limit=0.")
        return

    print(f"Đã lấy {len(rows)} dòng từ bảng {table_name}")

    # 2. Convert mỗi row thành text
    texts = [row_to_text(r) for r in rows]

    # 3. Đo token input
    token_counts = [count_tokens(t) for t in texts]
    print("--- Thống kê token input (cl100k_base) ---")
    print(f"Số record: {len(texts)}")
    print(f"Token min : {min(token_counts)}")
    print(f"Token max : {max(token_counts)}")
    print(f"Token avg : {np.mean(token_counts):.2f}")
    print(f"Tổng token: {sum(token_counts)}")

    # 4. Gọi embedding Google
    print("\nĐang gọi Google text-embedding-004 ...")
    google_embeds = embed_with_google(texts)
    google_dims = len(google_embeds[0]) if google_embeds else 0
    print(f"Google embedding dimension: {google_dims}")
    print(f"Số vector Google: {len(google_embeds)}")

    # 5. Gọi embedding Qwen
    print("\nĐang gọi Qwen3-embedding:latest ...")
    qwen_embeds = embed_with_qwen(texts)
    qwen_dims = len(qwen_embeds[0]) if qwen_embeds else 0
    print(f"Qwen embedding dimension: {qwen_dims}")
    print(f"Số vector Qwen: {len(qwen_embeds)}")

    # 6. So sánh sơ bộ độ "gần giống" giữa 2 vector (cosine similarity)
    #    ví dụ lấy 5 dòng đầu
    def cosine(a, b):
        a = np.array(a)
        b = np.array(b)
        return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))

    n_compare = min(5, len(google_embeds), len(qwen_embeds))
    print("\n--- So sánh cosine similarity giữa Google & Qwen (mẫu vài dòng) ---")
    for i in range(n_compare):
        # Để so được cosine, 2 vector phải cùng dimension.
        # Nếu khác dimension thì bỏ qua so sánh.
        if len(google_embeds[i]) != len(qwen_embeds[i]):
            print(f"Dòng {i}: KHÔNG so sánh được (dimension khác nhau).")
            continue
        sim = cosine(google_embeds[i], qwen_embeds[i])
        print(f"Dòng {i}: cosine similarity = {sim:.4f}")

    print("\nHoàn thành test embeddings.")


if __name__ == "__main__":
    # Truyền tên bảng ở đây (hoặc đọc từ argv)
    # Ví dụ: python embedding_test.py
    table = os.getenv("TEST_TABLE_NAME", "your_table_name")
    test_embeddings(table_name=table, limit=1000)