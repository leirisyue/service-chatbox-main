import json
import logging
import os
import time
from typing import Any, List, Optional, Tuple

import requests
import torch
from psycopg2.extras import RealDictCursor
from logServer import setup_logging
from connectDB import get_vector_db_connection

try:
    import tiktoken
except ImportError:
    tiktoken = None


QWEN_EMBED_MODEL = os.getenv("QWEN_EMBED_MODEL", "qwen3-embedding:latest")
QWEN_API_BASE = os.getenv("QWEN_API_BASE", "http://localhost:11434")  # ví dụ Ollama

# Kiểu lưu embedding trong DB: "vector" (pgvector) hoặc "jsonb"
EMBEDDING_STORAGE_TYPE = os.getenv("EMBEDDING_STORAGE_TYPE", "vector").lower()


# =========================
# 2. Helper: token counting
# =========================

def estimate_tokens(texts: List[str], model_name: str = "gpt-4o-mini") -> int:
    """Ước lượng tổng số token của 1 list text.

    Dùng tiktoken nếu có, nếu không thì ước lượng đơn giản theo số từ.
    """
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


def insert_embedding_rows(
    model: str,
    table_name: str,
    texts: List[str],
    raw_rows: List[Any],
    embeddings: List[Any],
):
    if not embeddings:
        logging.info(f"No embeddings to insert for model={model}")
        return

    if model == "qwen":
        target_table = "qwen_embeddings"
    else:
        raise ValueError("Unsupported model type")

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

def ensure_table_embedding_columns(table_name: str):
    """Đảm bảo bảng đích có các cột name_embedding, description_embedding, updated_at.

    - Nếu thiếu name_embedding/description_embedding thì tự động ADD COLUMN
      với kiểu VECTOR hoặc JSONB tùy EMBEDDING_STORAGE_TYPE.
    - Nếu thiếu updated_at thì thêm cột TIMESTAMPTZ.
    """
    conn = get_vector_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                """,
                (table_name,),
            )
            existing_cols = {row[0] for row in cur.fetchall()}

            if "name_embedding" not in existing_cols:
                if EMBEDDING_STORAGE_TYPE == "vector":
                    cur.execute(
                        f'ALTER TABLE public."{table_name}" ADD COLUMN name_embedding vector;'
                    )
                else:
                    cur.execute(
                        f'ALTER TABLE public."{table_name}" ADD COLUMN name_embedding jsonb;'
                    )

            if "description_embedding" not in existing_cols:
                if EMBEDDING_STORAGE_TYPE == "vector":
                    cur.execute(
                        f'ALTER TABLE public."{table_name}" ADD COLUMN description_embedding vector;'
                    )
                else:
                    cur.execute(
                        f'ALTER TABLE public."{table_name}" ADD COLUMN description_embedding jsonb;'
                    )

            if "updated_at" not in existing_cols:
                cur.execute(
                    f'ALTER TABLE public."{table_name}" ADD COLUMN updated_at TIMESTAMPTZ;'
                )

        conn.commit()
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
    
    if True:
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

        conn = get_vector_db_connection()
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


def generate_material_embeddings(table_name: str, limit: int = 1000, batch_size: int = 100):
    """Tạo embeddings name_embedding và description_embedding cho bảng materials-like theo batch.

    - Chỉ xử lý các dòng chưa có name_embedding hoặc description_embedding.
    - Xử lý theo từng batch_size, commit xong một batch mới đọc batch tiếp theo
      để tránh nghẽn database và quá tải model Qwen.
    - Có thể giới hạn tối đa `limit` bản ghi sẽ được xử lý.
    - name_embedding: embedding của material_name.
    - description_embedding: embedding của "material_name material_group material_subgroup".
    """

    ensure_table_embedding_columns(table_name)

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

    total_success = 0
    total_rows = 0
    errors: List[str] = []
    all_texts_for_token_est: List[str] = []

    start = time.time()
    batch_index = 0

    while True:
        # Nếu đã đạt tới limit tổng thì dừng
        if total_rows >= limit:
            break

        # Tính số bản ghi còn lại cần xử lý trong giới hạn
        remaining = max(limit - total_rows, 0)
        if remaining == 0:
            break

        current_limit = min(batch_size, remaining)

        conn = get_vector_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        query = f'''
            SELECT id_sap, material_name, material_group, material_subgroup
            FROM public."{table_name}"
            WHERE name_embedding IS NULL OR description_embedding IS NULL
            ORDER BY id_sap
            LIMIT %s
        '''

        cur.execute(query, (current_limit,))
        materials = cur.fetchall()

        if not materials:
            conn.close()
            break

        batch_index += 1
        logging.info(
            "[materials-embed] Bắt đầu batch %d, số bản ghi: %d", batch_index, len(materials)
        )

        total_rows += len(materials)

        try:
            for mat in materials:
                try:
                    material_name = (mat.get("material_name") or "").strip()
                    material_group = (mat.get("material_group") or "").strip()
                    material_subgroup = (mat.get("material_subgroup") or "").strip()
                    id_sap = mat.get("id_sap")

                    if id_sap is None:
                        errors.append("Bỏ qua một bản ghi không có id_sap")
                        continue

                    name_text = material_name
                    desc_text = f"{material_name} {material_group} {material_subgroup}".strip()

                    name_emb = _call_qwen(name_text)
                    desc_emb = _call_qwen(desc_text)

                    all_texts_for_token_est.append(name_text + " " + desc_text)

                    if EMBEDDING_STORAGE_TYPE == "vector":
                        name_emb_str = "[" + ",".join(str(float(x)) for x in name_emb) + "]"
                        desc_emb_str = "[" + ",".join(str(float(x)) for x in desc_emb) + "]"
                        update_sql = (
                            f'UPDATE public."{table_name}" '
                            "SET name_embedding = %s::vector, "
                            "    description_embedding = %s::vector, "
                            "    updated_at = NOW() "
                            "WHERE id_sap = %s"
                        )
                        params = (name_emb_str, desc_emb_str, id_sap)
                    else:
                        update_sql = (
                            f'UPDATE public."{table_name}" '
                            "SET name_embedding = %s::jsonb, "
                            "    description_embedding = %s::jsonb, "
                            "    updated_at = NOW() "
                            "WHERE id_sap = %s"
                        )
                        params = (
                            json.dumps(name_emb),
                            json.dumps(desc_emb),
                            id_sap,
                        )

                    cur.execute(update_sql, params)
                    total_success += 1

                    # tránh spam API quá nhanh
                    time.sleep(0.5)

                except Exception as e:  # pragma: no cover - logging lỗi runtime
                    errors.append(f"{mat.get('id_sap')}: {str(e)[:100]}")

            conn.commit()
        finally:
            conn.close()

    elapsed = time.time() - start
    token_est = estimate_tokens(all_texts_for_token_est)

    if total_rows == 0:
        return {
            "message": f"Tất cả bản ghi trong bảng {table_name} đã có embeddings",
            "success": 0,
            "total": 0,
            "errors": [],
            "elapsed": elapsed,
            "tokens": token_est,
        }

    return {
        "message": f"Đã tạo embeddings cho {total_success}/{total_rows} bản ghi trong bảng {table_name}",
        "success": total_success,
        "total": total_rows,
        "errors": errors[:5] if errors else [],
        "elapsed": elapsed,
        "tokens": token_est,
    }



if __name__ == "__main__":
    import argparse

    log_file = setup_logging(log_dir="logs", name="main_embedding")

    parser = argparse.ArgumentParser(
        description="Tạo embeddings Qwen cho bảng materials theo batch, lưu trực tiếp vào các cột embedding"
    )
    parser.add_argument("--table", required=True, help="Tên bảng trong Postgres")
    parser.add_argument("--limit", type=int, default=1000, help="Tổng số bản ghi tối đa cần xử lý")
    parser.add_argument("--batch-size", type=int, default=100, help="Số bản ghi xử lý trong mỗi batch")
    args = parser.parse_args()

    result = generate_material_embeddings(
        table_name=args.table,
        limit=args.limit,
        batch_size=args.batch_size,
    )

    logging.info(result.get("message"))
    print(json.dumps(result, ensure_ascii=False, indent=2))
