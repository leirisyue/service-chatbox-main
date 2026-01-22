import os
import json
import math
import logging
from typing import List, Tuple, Any, Dict

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import requests
import google.generativeai as genai
from embed_test_with_logging_and_db import (
    _load_opensearch_sparse_model,
    _compute_sparse_tensor,
    _sparse_tensor_to_token_dicts,
)

load_dotenv()

# =========================
# Env config
# =========================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "models/text-embedding-004")

QWEN_EMBED_MODEL = os.getenv("QWEN_EMBED_MODEL", "qwen3-embedding:latest")
QWEN_API_BASE = os.getenv("QWEN_API_BASE", "http://localhost:11434")

OPENSEARCH_SPARSE_MODEL_ID = os.getenv(
    "OPENSEARCH_SPARSE_MODEL_ID",
    "opensearch-project/opensearch-neural-sparse-encoding-doc-v2-mini",
)

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "postgres")
PG_DATABASE = os.getenv("PG_DATABASE", "postgres")

# vector hoặc jsonb (giống file trước)
EMBEDDING_STORAGE_TYPE = os.getenv("EMBEDDING_STORAGE_TYPE", "vector").lower()


# =========================
# Logging
# =========================
def setup_logging(log_dir: str = "logs") -> str:
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "test_search_accuracy.log")

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
# Postgres helpers
# =========================
def get_pg_connection():
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        dbname=PG_DATABASE,
    )
    return conn


# =========================
# Embedding helpers
# =========================
def embed_query_gemini(query: str) -> List[float]:
    genai.configure(api_key=GEMINI_API_KEY)
    resp = genai.embed_content(
        model=GEMINI_EMBED_MODEL,
        content=query,
    )
    emb = resp["embedding"] if isinstance(resp, dict) else resp.embedding
    return emb


def embed_query_qwen(query: str) -> List[float]:
    url = f"{QWEN_API_BASE}/api/embeddings"
    payload = {
        "model": QWEN_EMBED_MODEL,
        "prompt": query,
    }
    resp = requests.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    emb = data.get("embedding") or data.get("data", [{}])[0].get("embedding")
    if emb is None:
        raise ValueError(f"Qwen API response không có 'embedding': {data}")
    return emb


def embed_query_opensearch_sparse(query: str) -> Dict[str, float]:
    model, tokenizer, special_token_ids, id_to_token = _load_opensearch_sparse_model()

    feature = tokenizer(
        [query],
        padding=True,
        truncation=True,
        return_tensors="pt",
        return_token_type_ids=False,
    )

    # Gọi model để lấy dense output rồi convert sang sparse dict
    output = model(**feature)[0]
    sparse_tensor = _compute_sparse_tensor(feature, output, special_token_ids)
    token_dict = _sparse_tensor_to_token_dicts(sparse_tensor, id_to_token)[0]
    return token_dict


# =========================
# Cosine similarity
# =========================
def cosine_similarity(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


# =========================
# Search with pgvector (embedding VECTOR)
# =========================
def search_with_pgvector(
    model: str,
    query_emb: List[float],
    top_k: int = 10,
) -> List[dict]:
    table = "gemini_embeddings" if model == "gemini" else "qwen_embeddings"
    conn = get_pg_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            emb_str = "[" + ",".join(str(float(x)) for x in query_emb) + "]"
            sql = f"""
                SELECT
                    id,
                    source_table,
                    source_pk,
                    row_index,
                    text,
                    1 - (embedding <=> %s::vector) AS score
                FROM {table}
                ORDER BY embedding <=> %s::vector
                LIMIT %s;
            """
            # Dùng cùng emb_str cho cả 2 chỗ %s (vector query)
            cur.execute(sql, (emb_str, emb_str, top_k))
            rows = cur.fetchall()
            return rows
    finally:
        conn.close()


# =========================
# Search with JSONB (load vào Python, tự tính cosine)
# =========================
def search_with_jsonb(
    model: str,
    query_emb: List[float],
    top_k: int = 10,
    max_rows: int = 10000,
) -> List[dict]:
    table = "gemini_embeddings" if model == "gemini" else "qwen_embeddings"
    conn = get_pg_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            sql = f"""
                SELECT
                    id,
                    source_table,
                    source_pk,
                    row_index,
                    text,
                    embedding
                FROM {table}
                LIMIT %s;
            """
            cur.execute(sql, (max_rows,))
            rows = cur.fetchall()

        # Tính cosine similarity
        results = []
        for r in rows:
            emb = r["embedding"]
            if isinstance(emb, str):
                emb = json.loads(emb)
            score = cosine_similarity(query_emb, emb)
            r["score"] = score
            results.append(r)

        # Sort theo score giảm dần
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
    finally:
        conn.close()


def search_with_opensearch_sparse_jsonb(
    query_emb: Dict[str, float],
    top_k: int = 10,
    max_rows: int = 10000,
) -> List[dict]:
    table = "opensearch_sparse_embeddings"
    conn = get_pg_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            sql = f"""
                SELECT
                    id,
                    source_table,
                    source_pk,
                    row_index,
                    text,
                    embedding
                FROM {table}
                LIMIT %s;
            """
            cur.execute(sql, (max_rows,))
            rows = cur.fetchall()

        def sparse_dot(q: Dict[str, float], d: Dict[str, float]) -> float:
            return sum(v * d.get(tok, 0.0) for tok, v in q.items())

        results = []
        for r in rows:
            emb = r["embedding"]
            if isinstance(emb, str):
                emb = json.loads(emb)
            if not isinstance(emb, dict):
                # nếu format khác (ví dụ list), bỏ qua
                continue
            score = sparse_dot(query_emb, emb)
            r["score"] = score
            results.append(r)

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]
    finally:
        conn.close()


# =========================
# Main search
# =========================
def search_top_k(
    model: str,
    query_text: str,
    top_k: int = 10,
):
    logging.info(f"Search using model={model}, top_k={top_k}")
    logging.info(f"Query: {query_text}")

    if model == "gemini":
        query_emb = embed_query_gemini(query_text)
        logging.info(f"Got query embedding dim={len(query_emb)}")
        if EMBEDDING_STORAGE_TYPE == "vector":
            results = search_with_pgvector(model, query_emb, top_k=top_k)
        else:
            results = search_with_jsonb(model, query_emb, top_k=top_k)
    elif model == "qwen":
        query_emb = embed_query_qwen(query_text)
        logging.info(f"Got query embedding dim={len(query_emb)}")
        if EMBEDDING_STORAGE_TYPE == "vector":
            results = search_with_pgvector(model, query_emb, top_k=top_k)
        else:
            results = search_with_jsonb(model, query_emb, top_k=top_k)
    elif model == "opensearch_sparse":
        query_emb = embed_query_opensearch_sparse(query_text)
        logging.info(f"Got sparse query embedding with {len(query_emb)} non-zero tokens")
        results = search_with_opensearch_sparse_jsonb(query_emb, top_k=top_k)
    else:
        raise ValueError("model must be 'gemini', 'qwen' hoặc 'opensearch_sparse'")

    logging.info(f"Found {len(results)} results")

    print(f"\n=== Top {top_k} results for model={model} ===")
    logging.info(f"\n=== Top {top_k} results for model={model} ===")
    for i, r in enumerate(results, start=1):
        score = r.get("score", 0.0)
        text = r.get("text", "")[:300].replace("\n", " ")
        source_table = r.get("source_table")
        source_pk = r.get("source_pk")
        row_index = r.get("row_index")
        print(f"{i}. score={score:.4f}")
        logging.info(f"{i}. score={score:.4f}")
        print(f"   source_table={source_table}, source_pk={source_pk}, row_index={row_index}")
        logging.info(f"   source_table={source_table}, source_pk={source_pk}, row_index={row_index}")
        print(f"   text={text}")
        logging.info(f"   text={text}")
        print("")
        logging.info("")


    return results


if __name__ == "__main__":
    import argparse

    setup_logging()

    parser = argparse.ArgumentParser(
        description="Test độ chính xác: embed 1 câu query và search top-k trong DB"
    )
    parser.add_argument(
        "--model",
        required=True,
        choices=["gemini", "qwen", "opensearch_sparse"],
        help=(
            "Model dùng để embed và search "
            "(gemini, qwen hoặc opensearch_sparse)"
        ),
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Câu text để test",
    )
    parser.add_argument(
        "--top_k",
        type=int,
        default=10,
        help="Số dòng top-k cần lấy",
    )

    args = parser.parse_args()
    search_top_k(args.model, args.query, top_k=args.top_k)