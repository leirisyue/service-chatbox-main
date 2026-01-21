import os
import time
import json
import logging
from typing import List, Tuple, Any, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
import google.generativeai as genai
import requests
import torch
from transformers import AutoModelForMaskedLM, AutoTokenizer

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

OPENSEARCH_SPARSE_MODEL_ID = os.getenv(
    "OPENSEARCH_SPARSE_MODEL_ID",
    "opensearch-project/opensearch-neural-sparse-encoding-doc-v2-mini",
)

PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "postgres")
PG_DATABASE = os.getenv("PG_DATABASE", "postgres")

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
# 5. OpenSearch sparse encoder helpers
# =========================

_opensearch_sparse_model = None
_opensearch_sparse_tokenizer = None
_opensearch_sparse_special_token_ids = None
_opensearch_sparse_id_to_token = None


def _load_opensearch_sparse_model():
    """Lazy load Hugging Face model/tokenizer cho opensearch sparse encoder."""
    global _opensearch_sparse_model, _opensearch_sparse_tokenizer, _opensearch_sparse_special_token_ids, _opensearch_sparse_id_to_token

    if _opensearch_sparse_model is not None:
        return (
            _opensearch_sparse_model,
            _opensearch_sparse_tokenizer,
            _opensearch_sparse_special_token_ids,
            _opensearch_sparse_id_to_token,
        )

    model = AutoModelForMaskedLM.from_pretrained(OPENSEARCH_SPARSE_MODEL_ID)
    tokenizer = AutoTokenizer.from_pretrained(OPENSEARCH_SPARSE_MODEL_ID)

    special_token_ids = [
        tokenizer.vocab[token]
        for token in tokenizer.special_tokens_map.values()
        if token in tokenizer.vocab
    ]

    id_to_token = ["" for _ in range(tokenizer.vocab_size)]
    for token, idx in tokenizer.vocab.items():
        if 0 <= idx < tokenizer.vocab_size:
            id_to_token[idx] = token

    _opensearch_sparse_model = model
    _opensearch_sparse_tokenizer = tokenizer
    _opensearch_sparse_special_token_ids = special_token_ids
    _opensearch_sparse_id_to_token = id_to_token

    return model, tokenizer, special_token_ids, id_to_token


def _compute_sparse_tensor(feature, output, special_token_ids):
    """Từ output dense (batch, seq_len, vocab) -> sparse tensor (batch, vocab)."""
    # attention_mask: (batch, seq_len) -> (batch, seq_len, 1)
    attn = feature["attention_mask"].unsqueeze(-1)
    # max pooling theo chiều seq_len, chỉ giữ token thật (mask=1)
    values, _ = torch.max(output * attn, dim=1)  # (batch, vocab_size)
    values = torch.log1p(torch.relu(values))
    if special_token_ids:
        values[:, special_token_ids] = 0
    return values


def _sparse_tensor_to_token_dicts(sparse_tensor, id_to_token):
    """Chuyển tensor sparse (batch, vocab) -> list[dict[token -> weight]]."""
    batch_size, _ = sparse_tensor.shape
    sample_indices, token_indices = torch.nonzero(sparse_tensor, as_tuple=True)
    non_zero_values = sparse_tensor[(sample_indices, token_indices)].tolist()

    # Đếm số token khác 0 cho mỗi sample
    counts = torch.bincount(sample_indices, minlength=batch_size).tolist()
    tokens = [id_to_token[idx] for idx in token_indices.tolist()]

    result: List[dict] = []
    offset = 0
    for c in counts:
        if c == 0:
            result.append({})
            continue
        token_slice = tokens[offset : offset + c]
        value_slice = non_zero_values[offset : offset + c]
        result.append(dict(zip(token_slice, value_slice)))
        offset += c
    return result


# =========================
# 6. Postgres helpers
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


def ensure_embedding_tables():
    """
    Tạo bảng gemini_embeddings & qwen_embeddings nếu chưa có.
    Hỗ trợ 2 kiểu:
      - vector (pgvector, embedding VECTOR)
      - jsonb (embedding JSONB)
    """
    conn = get_pg_connection()
    try:
        with conn.cursor() as cur:
            if EMBEDDING_STORAGE_TYPE == "vector":
                # cần extension vector
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS gemini_embeddings (
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
                    CREATE TABLE IF NOT EXISTS gemini_embeddings (
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

            # Bảng riêng cho sparse embedding của OpenSearch (luôn JSONB)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS opensearch_sparse_embeddings (
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
    embeddings: List[Any],
):
    """Lưu embedding vào bảng.

    Mapping:
      - model = "gemini"          -> gemini_embeddings
      - model = "qwen"            -> qwen_embeddings
      - model = "opensearch_sparse" -> opensearch_sparse_embeddings (luôn JSONB)
    """
    if not embeddings:
        logging.info(f"No embeddings to insert for model={model}")
        return

    if model == "gemini":
        target_table = "gemini_embeddings"
    elif model == "qwen":
        target_table = "qwen_embeddings"
    elif model == "opensearch_sparse":
        target_table = "opensearch_sparse_embeddings"
    else:
        raise ValueError("Unsupported model type")

    conn = get_pg_connection()
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

                if model == "opensearch_sparse":
                    # Sparse embedding lưu dạng JSONB (token -> weight)
                    sql = f"""
                        INSERT INTO {target_table} (source_table, source_pk, row_index, text, embedding)
                        VALUES (%s, %s, %s, %s, %s::jsonb)
                    """
                    params = (table_name, source_pk, idx, text, json.dumps(emb))
                elif EMBEDDING_STORAGE_TYPE == "vector":
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
    conn = get_pg_connection()
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
# 6. Gemini embedding + logging + DB save
# =========================
def embed_with_gemini(
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
        f"{table_name}_gemini_embeddings_{timestamp}.jsonl"
    )

    genai.configure(api_key=GEMINI_API_KEY)

    embeddings: List[List[float]] = []
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
                "raw_row": to_jsonable(row),
                "embedding": to_jsonable(emb),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    elapsed = time.time() - start
    token_est = estimate_tokens(texts)

    logging.info(
        f"Gemini embeddings done: {len(embeddings)} rows, "
        f"time={elapsed:.2f}s, tokens≈{token_est}, output={outfile}"
    )

    # Lưu vào DB
    insert_embedding_rows("gemini", table_name, texts, raw_rows, embeddings)

    return embeddings, elapsed, token_est, outfile


# =========================
# 7. Qwen embedding + logging + DB save
# =========================
def embed_with_qwen(
    table_name: str,
    texts: List[str],
    raw_rows: List[Any],
    output_dir: str,
) -> Tuple[List[List[float]], float, int, str]:
    """Sinh embedding bằng Qwen.

    - Với bảng materials_qwen: cập nhật trực tiếp vào cột
      name_embedding (material_name) và
      description_embedding (material_subgroup, material_group, material_name)
      trong bảng input.
    - Với bảng khác: giữ nguyên behavior cũ, ghi vào bảng qwen_embeddings.
    """

    # Trường hợp đặc biệt: cập nhật trực tiếp bảng materials_qwen
    if table_name == "materials_qwen":
        if not raw_rows:
            return [], 0.0, 0, ""

        os.makedirs(output_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        outfile = os.path.join(
            output_dir,
            f"{table_name}_qwen_embeddings_{timestamp}.jsonl",
        )

        url = f"{QWEN_API_BASE}/api/embeddings"

        def _call_qwen(text: str) -> List[float]:
            payload = {
                "model": QWEN_EMBED_MODEL,
                "prompt": text,
            }
            resp = requests.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            emb = data.get("embedding") or data.get("data", [{}])[0].get("embedding")
            if emb is None:
                raise ValueError(f"Qwen API response không có 'embedding': {data}")
            return emb

        start = time.time()
        description_embeddings: List[List[float]] = []
        all_texts_for_token_est: List[str] = []

        conn = get_pg_connection()
        try:
            with conn.cursor() as cur, open(outfile, "w", encoding="utf-8") as f:
                for idx, row in enumerate(raw_rows):
                    # Lấy các trường cần thiết từ dòng
                    material_name = (row.get("material_name") or "").strip()
                    material_subgroup = (row.get("material_subgroup") or "").strip()
                    material_group = (row.get("material_group") or "").strip()
                    id_sap = row.get("id_sap")

                    if id_sap is None:
                        logging.warning(
                            "materials_qwen row index %s không có id_sap, bỏ qua cập nhật.",
                            idx,
                        )
                        continue

                    name_text = material_name
                    desc_parts = [p for p in [material_subgroup, material_group, material_name] if p]
                    description_text = " ".join(desc_parts)

                    # Gọi Qwen cho 2 đoạn text
                    name_emb = _call_qwen(name_text)
                    desc_emb = _call_qwen(description_text)

                    description_embeddings.append(desc_emb)
                    all_texts_for_token_est.append(name_text + " " + description_text)

                    # Ghi log ra JSONL để tiện debug
                    record = {
                        "row_index": idx,
                        "id_sap": id_sap,
                        "material_name": material_name,
                        "material_subgroup": material_subgroup,
                        "material_group": material_group,
                        "name_embedding": to_jsonable(name_emb),
                        "description_embedding": to_jsonable(desc_emb),
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

                    # Cập nhật trực tiếp vào bảng materials_qwen
                    if EMBEDDING_STORAGE_TYPE == "vector":
                        name_emb_str = "[" + ",".join(str(float(x)) for x in name_emb) + "]"
                        desc_emb_str = "[" + ",".join(str(float(x)) for x in desc_emb) + "]"
                        update_sql = (
                            "UPDATE public.\"materials_qwen\" "
                            "SET name_embedding = %s::vector, "
                            "    description_embedding = %s::vector "
                            "WHERE id_sap = %s"
                        )
                        params = (name_emb_str, desc_emb_str, id_sap)
                    else:
                        update_sql = (
                            "UPDATE public.\"materials_qwen\" "
                            "SET name_embedding = %s::jsonb, "
                            "    description_embedding = %s::jsonb "
                            "WHERE id_sap = %s"
                        )
                        params = (
                            json.dumps(name_emb),
                            json.dumps(desc_emb),
                            id_sap,
                        )

                    cur.execute(update_sql, params)

            conn.commit()
        finally:
            conn.close()

        elapsed = time.time() - start
        token_est = estimate_tokens(all_texts_for_token_est)

        logging.info(
            "Qwen embeddings (materials_qwen) done: %d rows, time=%.2fs, tokens≈%d, output=%s",
            len(description_embeddings),
            elapsed,
            token_est,
            outfile,
        )

        # Trả về list description_embedding để tương thích run_test
        return description_embeddings, elapsed, token_est, outfile

    # Trường hợp đặc biệt: cập nhật trực tiếp bảng products_qwen
    if table_name == "products_qwen":
        if not raw_rows:
            return [], 0.0, 0, ""

        os.makedirs(output_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        outfile = os.path.join(
            output_dir,
            f"{table_name}_qwen_embeddings_{timestamp}.jsonl",
        )

        url = f"{QWEN_API_BASE}/api/embeddings"

        def _call_qwen(text: str) -> List[float]:
            payload = {
                "model": QWEN_EMBED_MODEL,
                "prompt": text,
            }
            resp = requests.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            emb = data.get("embedding") or data.get("data", [{}])[0].get("embedding")
            if emb is None:
                raise ValueError(f"Qwen API response không có 'embedding': {data}")
            return emb

        start = time.time()
        description_embeddings: List[List[float]] = []
        all_texts_for_token_est: List[str] = []

        conn = get_pg_connection()
        try:
            with conn.cursor() as cur, open(outfile, "w", encoding="utf-8") as f:
                for idx, row in enumerate(raw_rows):
                    # Lấy các trường cần thiết từ dòng
                    product_name = (row.get("product_name") or "").strip()
                    category = (row.get("category") or "").strip()
                    sub_category = (row.get("sub_category") or "").strip()
                    material_primary = (row.get("material_primary") or "").strip()
                    id_sap = row.get("id_sap")

                    if id_sap is None:
                        logging.warning(
                            "products_qwen row index %s không có id_sap, bỏ qua cập nhật.",
                            idx,
                        )
                        continue

                    name_text = product_name
                    desc_parts = [p for p in [category, sub_category, material_primary] if p]
                    description_text = " ".join(desc_parts)

                    # Gọi Qwen cho 2 đoạn text
                    name_emb = _call_qwen(name_text)
                    desc_emb = _call_qwen(description_text)

                    description_embeddings.append(desc_emb)
                    all_texts_for_token_est.append(name_text + " " + description_text)

                    # Ghi log ra JSONL để tiện debug
                    record = {
                        "row_index": idx,
                        "id_sap": id_sap,
                        "product_name": product_name,
                        "category": category,
                        "sub_category": sub_category,
                        "material_primary": material_primary,
                        "name_embedding": to_jsonable(name_emb),
                        "description_embedding": to_jsonable(desc_emb),
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

                    # Cập nhật trực tiếp vào bảng products_qwen
                    if EMBEDDING_STORAGE_TYPE == "vector":
                        name_emb_str = "[" + ",".join(str(float(x)) for x in name_emb) + "]"
                        desc_emb_str = "[" + ",".join(str(float(x)) for x in desc_emb) + "]"
                        update_sql = (
                            "UPDATE public.\"products_qwen\" "
                            "SET name_embedding = %s::vector, "
                            "    description_embedding = %s::vector "
                            "WHERE id_sap = %s"
                        )
                        params = (name_emb_str, desc_emb_str, id_sap)
                    else:
                        update_sql = (
                            "UPDATE public.\"products_qwen\" "
                            "SET name_embedding = %s::jsonb, "
                            "    description_embedding = %s::jsonb "
                            "WHERE id_sap = %s"
                        )
                        params = (
                            json.dumps(name_emb),
                            json.dumps(desc_emb),
                            id_sap,
                        )

                    cur.execute(update_sql, params)

            conn.commit()
        finally:
            conn.close()

        elapsed = time.time() - start
        token_est = estimate_tokens(all_texts_for_token_est)

        logging.info(
            "Qwen embeddings (products_qwen) done: %d rows, time=%.2fs, tokens≈%d, output=%s",
            len(description_embeddings),
            elapsed,
            token_est,
            outfile,
        )

        # Trả về list description_embedding để tương thích run_test
        return description_embeddings, elapsed, token_est, outfile

    # Mặc định: behavior cũ, lưu vào bảng qwen_embeddings
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
# 8. OpenSearch sparse embedding + logging + DB save
# =========================
def embed_with_opensearch_sparse(
    table_name: str,
    texts: List[str],
    raw_rows: List[Any],
    output_dir: str,
) -> Tuple[List[Any], float, int, str]:
    """Sinh sparse embedding (token -> weight) bằng model OpenSearch.

        - Với bảng materials_sparse, products_sparse: cập nhật trực tiếp vào cột
            name_embedding và description_embedding của bảng input (lưu dạng VECTOR
            dày có kích thước bằng vocab_size, suy ra từ sparse tensor).
        - Với bảng khác: lưu vào bảng opensearch_sparse_embeddings (JSONB) như cũ.
    """

    # Trường hợp đặc biệt: cập nhật trực tiếp bảng materials_sparse
    if table_name == "materials_sparse":
        if not raw_rows:
            return [], 0.0, 0, ""

        os.makedirs(output_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        outfile = os.path.join(
            output_dir,
            f"{table_name}_opensearch_sparse_embeddings_{timestamp}.jsonl",
        )

        model, tokenizer, special_token_ids, id_to_token = _load_opensearch_sparse_model()

        def _encode_sparse(text: str) -> List[float]:
            feature = tokenizer(
                [text],
                padding=True,
                truncation=True,
                return_tensors="pt",
                return_token_type_ids=False,
            )
            with torch.no_grad():
                output = model(**feature)[0]
            sparse_tensor = _compute_sparse_tensor(
                feature,
                output,
                special_token_ids,
            )  # (1, vocab_size)
            # Trả về vector dày (1, vocab_size) -> list[float]
            dense_vector = sparse_tensor.squeeze(0).tolist()
            # Giới hạn số chiều để phù hợp pgvector (<=16000)
            if len(dense_vector) > 16000:
                dense_vector = dense_vector[:16000]
            return dense_vector

        start = time.time()
        description_embeddings: List[Any] = []
        all_texts_for_token_est: List[str] = []

        conn = get_pg_connection()
        try:
            with conn.cursor() as cur, open(outfile, "w", encoding="utf-8") as f:
                for idx, row in enumerate(raw_rows):
                    material_name_sparse = (row.get("material_name") or "").strip()
                    material_subgroup = (row.get("material_subgroup") or "").strip()
                    material_group = (row.get("material_group") or "").strip()
                    id_sap = row.get("id_sap")

                    if id_sap is None:
                        logging.warning(
                            "materials_qwen row index %s không có id_sap, bỏ qua cập nhật.",
                            idx,
                        )
                        continue

                    name_text = material_name_sparse
                    desc_parts = [p for p in [material_subgroup, material_group, material_name_sparse] if p]
                    description_text = " ".join(desc_parts)

                    name_emb = _encode_sparse(name_text)
                    desc_emb = _encode_sparse(description_text)

                    description_embeddings.append(desc_emb)
                    all_texts_for_token_est.append(name_text + " " + description_text)

                    record = {
                        "row_index": idx,
                        "id_sap": id_sap,
                        "material_name": material_name_sparse,
                        "material_subgroup": material_subgroup,
                        "material_group": material_group,
                        "name_embedding": to_jsonable(name_emb),
                        "description_embedding": to_jsonable(desc_emb),
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

                    # Cập nhật trực tiếp vào bảng materials_sparse (VECTOR)
                    name_emb_str = "[" + ",".join(str(float(x)) for x in name_emb) + "]"
                    desc_emb_str = "[" + ",".join(str(float(x)) for x in desc_emb) + "]"
                    update_sql = (
                        "UPDATE public.\"materials_sparse\" "
                        "SET name_embedding = %s::vector, "
                        "    description_embedding = %s::vector "
                        "WHERE id_sap = %s"
                    )
                    params = (
                        name_emb_str,
                        desc_emb_str,
                        id_sap,
                    )

                    cur.execute(update_sql, params)

            conn.commit()
        finally:
            conn.close()

        elapsed = time.time() - start
        token_est = estimate_tokens(all_texts_for_token_est)

        logging.info(
            "OpenSearch sparse embeddings (materials_sparse) done: %d rows, time=%.2fs, tokens≈%d, output=%s",
            len(description_embeddings),
            elapsed,
            token_est,
            outfile,
        )

        # Trả về list description_embedding để tương thích run_test
        return description_embeddings, elapsed, token_est, outfile


    # Trường hợp đặc biệt: cập nhật trực tiếp bảng products_sparse
    if table_name == "products_sparse":
        if not raw_rows:
            return [], 0.0, 0, ""

        os.makedirs(output_dir, exist_ok=True)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        outfile = os.path.join(
            output_dir,
            f"{table_name}_opensearch_sparse_embeddings_{timestamp}.jsonl",
        )

        model, tokenizer, special_token_ids, id_to_token = _load_opensearch_sparse_model()

        def _encode_sparse(text: str) -> List[float]:
            feature = tokenizer(
                [text],
                padding=True,
                truncation=True,
                return_tensors="pt",
                return_token_type_ids=False,
            )
            with torch.no_grad():
                output = model(**feature)[0]
            sparse_tensor = _compute_sparse_tensor(
                feature,
                output,
                special_token_ids,
            )  # (1, vocab_size)
            # Trả về vector dày (1, vocab_size) -> list[float]
            dense_vector = sparse_tensor.squeeze(0).tolist()
            # Giới hạn số chiều để phù hợp pgvector (<=16000)
            if len(dense_vector) > 16000:
                dense_vector = dense_vector[:16000]
            return dense_vector

        start = time.time()
        description_embeddings: List[Any] = []
        all_texts_for_token_est: List[str] = []

        conn = get_pg_connection()
        try:
            with conn.cursor() as cur, open(outfile, "w", encoding="utf-8") as f:
                for idx, row in enumerate(raw_rows):
                    product_name = (row.get("product_name") or "").strip()
                    category = (row.get("category") or "").strip()
                    sub_category = (row.get("sub_category") or "").strip()
                    material_primary = (row.get("material_primary") or "").strip()
                    id_sap = row.get("id_sap")

                    if id_sap is None:
                        logging.warning(
                            "products_sparse row index %s không có id_sap, bỏ qua cập nhật.",
                            idx,
                        )
                        continue

                    name_text = product_name
                    desc_parts = [p for p in [category, sub_category, material_primary] if p]
                    description_text = " ".join(desc_parts)

                    name_emb = _encode_sparse(name_text)
                    desc_emb = _encode_sparse(description_text)

                    description_embeddings.append(desc_emb)
                    all_texts_for_token_est.append(name_text + " " + description_text)

                    record = {
                        "row_index": idx,
                        "id_sap": id_sap,
                        "product_name": product_name,
                        "category": category,
                        "sub_category": sub_category,
                        "material_primary": material_primary,
                        "name_embedding": to_jsonable(name_emb),
                        "description_embedding": to_jsonable(desc_emb),
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

                    # Cập nhật trực tiếp vào bảng materials_sparse (VECTOR)
                    name_emb_str = "[" + ",".join(str(float(x)) for x in name_emb) + "]"
                    desc_emb_str = "[" + ",".join(str(float(x)) for x in desc_emb) + "]"
                    update_sql = (
                        "UPDATE public.\"products_sparse\" "
                        "SET name_embedding = %s::vector, "
                        "    description_embedding = %s::vector "
                        "WHERE id_sap = %s"
                    )
                    params = (
                        name_emb_str,
                        desc_emb_str,
                        id_sap,
                    )

                    cur.execute(update_sql, params)

            conn.commit()
        finally:
            conn.close()

        elapsed = time.time() - start
        token_est = estimate_tokens(all_texts_for_token_est)

        logging.info(
            "OpenSearch sparse embeddings (products_sparse) done: %d rows, time=%.2fs, tokens≈%d, output=%s",
            len(description_embeddings),
            elapsed,
            token_est,
            outfile,
        )

        # Trả về list description_embedding để tương thích run_test
        return description_embeddings, elapsed, token_est, outfile

    # Mặc định: behavior cũ, lưu vào bảng opensearch_sparse_embeddings (JSONB)
    if not texts:
        return [], 0.0, 0, ""

    os.makedirs(output_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    outfile = os.path.join(
        output_dir,
        f"{table_name}_opensearch_sparse_embeddings_{timestamp}.jsonl",
    )

    model, tokenizer, special_token_ids, id_to_token = _load_opensearch_sparse_model()

    embeddings: List[Any] = []
    start = time.time()
    with open(outfile, "w", encoding="utf-8") as f:
        for idx, (t, row) in enumerate(zip(texts, raw_rows)):
            feature = tokenizer(
                [t],
                padding=True,
                truncation=True,
                return_tensors="pt",
                return_token_type_ids=False,
            )

            with torch.no_grad():
                output = model(**feature)[0]

            sparse_tensor = _compute_sparse_tensor(
                feature,
                output,
                special_token_ids,
            )  # (1, vocab_size)

            token_dict = _sparse_tensor_to_token_dicts(
                sparse_tensor,
                id_to_token,
            )[0]
            embeddings.append(token_dict)

            record = {
                "row_index": idx,
                "text": t,
                "raw_row": to_jsonable(row),
                "embedding": to_jsonable(token_dict),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    elapsed = time.time() - start
    token_est = estimate_tokens(texts)

    logging.info(
        "OpenSearch sparse embeddings done: %d rows, time=%.2fs, tokens≈%d, output=%s",
        len(embeddings),
        elapsed,
        token_est,
        outfile,
    )

    # Lưu vào DB (luôn JSONB)
    insert_embedding_rows("opensearch_sparse", table_name, texts, raw_rows, embeddings)

    return embeddings, elapsed, token_est, outfile


# =========================
# 8. Main test
# =========================
def run_test(table_name: str, limit: int = 1000):
    logging.info(f"Starting test for table='{table_name}', limit={limit}")

    # Đảm bảo 2 bảng embedding tồn tại
    ensure_embedding_tables()

    texts, raw_rows = fetch_rows_from_table(table_name, limit=limit)
    logging.info(f"Got {len(texts)} rows to embed.")

    output_dir = "embeddings_output"
    os.makedirs(output_dir, exist_ok=True)

    # Test Gemini
    # logging.info("=== Start Gemini embedding ===")
    # gem_embs, gem_time, gem_tokens, gem_file = embed_with_gemini(
    #     table_name, texts, raw_rows, output_dir
    # )
    # logging.info(f"Gemini - vectors: {len(gem_embs)}, time={gem_time:.2f}s, tokens≈{gem_tokens}")

    # Test Qwen
    # logging.info("=== Start Qwen embedding ===")
    # qwen_embs, qwen_time, qwen_tokens, qwen_file = embed_with_qwen(
    #     table_name, texts, raw_rows, output_dir
    # )
    # logging.info(f"Qwen  - vectors: {len(qwen_embs)}, time={qwen_time:.2f}s, tokens≈{qwen_tokens}")

    # Test OpenSearch sparse
    logging.info("=== Start OpenSearch sparse embedding ===")
    os_embs, os_time, os_tokens, os_file = embed_with_opensearch_sparse(
        table_name, texts, raw_rows, output_dir
    )
    logging.info(
        "OpenSearch-sparse - vectors: %d, time=%.2fs, tokens≈%d",
        len(os_embs),
        os_time,
        os_tokens,
    )

    # So sánh sơ bộ
    logging.info("=== Summary ===")
    logging.info(f"Rows: {len(texts)}")
    # logging.info(f"Gemini: time={gem_time:.2f}s, tokens≈{gem_tokens}, file={gem_file}")
    # logging.info(f"Qwen : time={qwen_time:.2f}s, tokens≈{qwen_tokens}, file={qwen_file}")
    logging.info(
        f"OpenSearch-sparse: time={os_time:.2f}s, tokens≈{os_tokens}, file={os_file}"
    )

    print("\n=== Summary ===")
    print(f"Rows: {len(texts)}")
    # print(f"Gemini: time={gem_time:.2f}s, tokens≈{gem_tokens}, file={gem_file}")
    # print(f"Qwen : time={qwen_time:.2f}s, tokens≈{qwen_tokens}, file={qwen_file}")
    print(
        f"OpenSearch-sparse: time={os_time:.2f}s, tokens≈{os_tokens}, file={os_file}"
    )


if __name__ == "__main__":
    import argparse

    log_file = setup_logging()

    parser = argparse.ArgumentParser(
        description="Test embedding từ Postgres table bằng Gemini & Qwen, có log, file JSONL và lưu DB"
    )
    parser.add_argument("--table", required=True, help="Tên bảng trong Postgres")
    parser.add_argument("--limit", type=int, default=1000, help="Số dòng tối đa")
    args = parser.parse_args()

    run_test(args.table, args.limit)