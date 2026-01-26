from datetime import datetime
from typing import Dict, Any, Union
from decimal import Decimal
from typing import List

from .db import (
    get_origin_tables,
    ensure_target_table,
    fetch_rows_from_origin,
    insert_vector_rows,
    update_vector_rows,
    update_origin_rows,
    insert_origin_rows,
)
from .embedding_service import embedding_service
from .logger import setup_logger

logger = setup_logger(__name__)

def _sanitize_value(val: Any) -> Any:
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, datetime):
        return val.isoformat()
    return val

def row_to_text(columns, row) -> str:
    parts = []
    for col, val in zip(columns, row):
        if val is None:
            continue
        parts.append(f"{col}: {_sanitize_value(val)}")
    return "\n".join(parts)

def row_to_original_data(columns, row) -> Dict[str, Any]:
    return {col: _sanitize_value(row[i]) for i, col in enumerate(columns)}

def process_table(table_name: str, limit: int | None = None, batch_size: int = 50):
    logger.info("=== Start processing table: %s ===", table_name)
    ensure_target_table(table_name)
    columns, rows = fetch_rows_from_origin(table_name, limit=limit)

    batch = []
    for idx, row in enumerate(rows, start=1):
        content_text = row_to_text(columns, row)
        if not content_text.strip():
            continue

        try:
            embedding = embedding_service.embed(content_text)
        except Exception:
            logger.exception("Embedding failed at row %d", idx)
            continue

        batch.append(
            {
                "original_data": row_to_original_data(columns, row),
                "content_text": content_text,
                "embedding": embedding,
                "created_at": datetime.utcnow(),
            }
        )

        if len(batch) >= batch_size:
            insert_vector_rows(table_name, batch)
            batch.clear()

    if batch:
        insert_vector_rows(table_name, batch)

    logger.info("=== Done table: %s ===", table_name)

def run_all_tables():
    logger.info("Starting full vector build")
    for tbl in get_origin_tables():
        process_table(tbl)
    logger.info("Finished full vector build")

def record_to_text(data: Dict[str, Any]) -> str:
    parts = []
    for k, v in data.items():
        if v is None:
            continue
        parts.append(f"{k}: {v}")
    return "\n".join(parts)

def insert_records(
    table_name: str,
    records: Union[Dict[str, Any], List[Dict[str, Any]]],
):
    # Chuẩn hóa: cho phép truyền 1 object hoặc list object
    if isinstance(records, dict):
        records_list: List[Dict[str, Any]] = [records]
    else:
        records_list = records or []

    logger.info("Inserting %d records into %s", len(records_list), table_name)

    # 1) Insert trực tiếp vào bảng gốc (origin DB)
    try:
        insert_origin_rows(table_name, records_list)
    except Exception:
        logger.exception("Failed to insert into origin table %s", table_name)

    # 1b) Tạo name_embedding và description_embedding cho bảng gốc (nếu cần)
    # Áp dụng cho các bảng có trường material_name hoặc tương tự
    origin_embed_rows: List[Dict[str, Any]] = []
    
    for idx, record in enumerate(records_list, start=1):
        # Yêu cầu có id_sap để update embedding
        if "id_sap" not in record:
            logger.warning("Missing 'id_sap' in record %d for origin embedding, skip", idx)
            continue

        # Lấy tên vật liệu (name_text)
        name_text = str(record.get("material_name") or "")
        
        # Tạo mô tả từ các field khác (loại bỏ id_sap và material_name)
        desc_source = {
            k: v for k, v in record.items() 
            if k not in ["id_sap", "material_name"] and v is not None
        }
        desc_text = record_to_text(desc_source) if desc_source else name_text

        # Tạo embeddings
        name_embedding = None
        description_embedding = None

        try:
            if name_text.strip():
                name_embedding = embedding_service.embed(name_text)
        except Exception:
            logger.exception("Failed to create name_embedding for record %d", idx)

        try:
            if desc_text.strip():
                description_embedding = embedding_service.embed(desc_text)
        except Exception:
            logger.exception("Failed to create description_embedding for record %d", idx)

        # Chỉ update nếu có ít nhất 1 embedding
        if name_embedding is not None or description_embedding is not None:
            payload: Dict[str, Any] = {"id_sap": record["id_sap"]}
            
            if name_embedding is not None:
                payload["name_embedding"] = name_embedding
            
            if description_embedding is not None:
                payload["description_embedding"] = description_embedding

            origin_embed_rows.append(payload)

    # Update embeddings vào bảng gốc
    if origin_embed_rows:
        try:
            update_origin_rows(table_name, origin_embed_rows)
            logger.info("Updated %d origin embeddings for %s", len(origin_embed_rows), table_name)
        except Exception:
            logger.exception("Failed to update origin embeddings for table %s", table_name)

    # 2) Insert vào bảng vector (target DB)
    ensure_target_table(table_name)

    batch = []

    for idx, record in enumerate(records_list, start=1):
        content_text = record_to_text(record)

        if not content_text.strip():
            logger.warning("Empty content at record %d, skip", idx)
            continue

        try:
            embedding = embedding_service.embed(content_text)
        except Exception:
            logger.exception("Embedding failed at record %d", idx)
            continue

        batch.append(
            {
                "original_data": record,
                "content_text": content_text,
                "embedding": embedding,
                "created_at": datetime.utcnow(),
            }
        )

    if batch:
        insert_vector_rows(table_name, batch)

    logger.info("Inserted %d records into %s", len(batch), table_name)
    
    

def update_records(
    table_name: str,
    records: List[Dict[str, Any]],
):
    logger.info("Updating %d records in %s", len(records), table_name)
    ensure_target_table(table_name)

    # 1) Update trực tiếp bảng gốc (origin DB)
    try:
        update_origin_rows(table_name, records)
    except Exception:
        logger.exception("Failed to update origin table %s", table_name)

    # 2) Update bảng vector (target DB)
    batch = []

    for idx, record in enumerate(records, start=1):
        # Yêu cầu mỗi record phải có khóa 'id_sap' để xác định dòng cần update
        if "id_sap" not in record:
            logger.warning("Missing 'id_sap' in record %d, skip", idx)
            continue

        record_id = record["id_sap"] # filter key[]
        # Giữ nguyên toàn bộ record (bao gồm id_sap) trong original_data
        content_text = record_to_text(record)

        if not content_text.strip():
            logger.warning("Empty content at record %d, skip", idx)
            continue

        try:
            embedding = embedding_service.embed(content_text)
        except Exception:
            logger.exception("Embedding failed at record %d", idx)
            continue

        batch.append(
            {
                "id_sap": record_id,
                "original_data": record,
                "content_text": content_text,
                "embedding": embedding,
                "created_at": datetime.utcnow(),
            }
        )

    if batch:
        update_vector_rows(table_name, batch)

    logger.info("Updated %d records in %s", len(batch), table_name)