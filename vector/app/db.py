from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from datetime import datetime
from typing import List, Any, Dict
import json

from .config import settings
from .logger import setup_logger

logger = setup_logger(__name__)


def make_pg_url(user, password, host, port, db):
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


origin_engine: Engine = create_engine(
    make_pg_url(
        settings.ORIGIN_DB_USER,
        settings.ORIGIN_DB_PASSWORD,
        settings.ORIGIN_DB_HOST,
        settings.ORIGIN_DB_PORT,
        settings.ORIGIN_DB_NAME,
    )
)

target_engine: Engine = create_engine(
    make_pg_url(
        settings.APP_PG_USER,
        settings.APP_PG_PASSWORD,
        settings.APP_PG_HOST,
        settings.APP_PG_PORT,
        settings.APP_PG_DATABASE,
    )
)

logger.info(
    "Origin DB connected to %s:%s/%s, Target DB connected to %s:%s/%s",
    settings.ORIGIN_DB_HOST,
    settings.ORIGIN_DB_PORT,
    settings.ORIGIN_DB_NAME,
    settings.APP_PG_HOST,
    settings.APP_PG_PORT,
    settings.APP_PG_DATABASE,
)


def get_origin_tables() -> List[str]:
    sql = """
    SELECT tablename
    FROM pg_tables
    WHERE schemaname = 'public';
    """
    with origin_engine.connect() as conn:
        rows = conn.execute(text(sql)).fetchall()
    tables = [r[0] for r in rows]
    logger.info("Found %d tables in origin DB: %s", len(tables), tables)
    return tables


def ensure_target_table(table_name: str):
    logger.info("Ensuring target table exists: %s", table_name)
    create_sql = f"""
    CREATE TABLE IF NOT EXISTS public."{table_name}" (
        id BIGSERIAL PRIMARY KEY,
        original_data JSONB,
        content_text TEXT,
        embedding DOUBLE PRECISION[],
        created_at TIMESTAMPTZ DEFAULT NOW()
    );
    """
    with target_engine.begin() as conn:
        conn.execute(text(create_sql))
    logger.info("Table %s is ready in target DB", table_name)


def fetch_rows_from_origin(table_name: str, limit: int | None = None):
    sql = f'SELECT * FROM public."{table_name}"'
    if limit:
        sql += f" LIMIT {limit}"
        logger.info("Fetching up to %d rows from origin table %s", limit, table_name)
    else:
        logger.info("Fetching ALL rows from origin table %s", table_name)

    with origin_engine.connect() as conn:
        result = conn.execute(text(sql))
        rows = result.fetchall()
        columns = result.keys()
    logger.info("Fetched %d rows from origin table %s", len(rows), table_name)
    return columns, rows


def insert_vector_rows(
    table_name: str,
    rows: List[Dict[str, Any]],
):
    if not rows:
        logger.info("No rows to insert into %s", table_name)
        return

    serialized_rows = []
    for r in rows:
        r = r.copy()
        if isinstance(r.get("original_data"), dict):
            r["original_data"] = json.dumps(r["original_data"], ensure_ascii=False)
        serialized_rows.append(r)

    logger.info("Inserting %d vector rows into target table %s", len(serialized_rows), table_name)
    insert_sql = f"""
    INSERT INTO public."{table_name}" (original_data, content_text, embedding, created_at)
    VALUES (:original_data, :content_text, :embedding, :created_at)
    """
    with target_engine.begin() as conn:
        conn.execute(text(insert_sql), serialized_rows)
    logger.info("Inserted %d rows into %s successfully", len(serialized_rows), table_name)