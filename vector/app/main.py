from datetime import datetime
from typing import Dict, Any
from decimal import Decimal

from .db import (
    get_origin_tables,
    ensure_target_table,
    fetch_rows_from_origin,
    insert_vector_rows,
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
    logger.info("Total rows to process in %s: %d", table_name, len(rows))

    batch = []
    for idx, row in enumerate(rows, start=1):
        content_text = row_to_text(columns, row)
        if not content_text.strip():
            logger.warning("Row %d in table %s has empty content_text, skipping", idx, table_name)
            continue

        try:
            embedding = embedding_service.embed(content_text)
        except Exception as e:
            logger.exception(
                "Failed to generate embedding for row %d in table %s", idx, table_name
            )
            continue

        original_data = row_to_original_data(columns, row)

        batch.append(
            {
                "original_data": original_data,
                "content_text": content_text,
                "embedding": embedding,
                "created_at": datetime.utcnow(),
            }
        )

        if len(batch) >= batch_size:
            insert_vector_rows(table_name, batch)
            logger.info(
                "[%s] Inserted batch of %d rows (up to row %d)",
                table_name,
                len(batch),
                idx,
            )
            batch.clear()

    if batch:
        insert_vector_rows(table_name, batch)
        logger.info(
            "[%s] Inserted final batch of %d rows",
            table_name,
            len(batch),
        )

    logger.info("=== Done processing table: %s ===", table_name)


def main():
    logger.info("Starting RAG vector build process")
    tables = get_origin_tables()
    for tbl in tables:
        process_table(tbl, limit=None)  # có thể đổi limit=100 để test
    logger.info("All tables processed successfully")


if __name__ == "__main__":
    main()