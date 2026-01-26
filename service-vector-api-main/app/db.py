from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from datetime import datetime
from typing import List, Any, Dict, Optional
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
    with target_engine.begin() as conn:
        # Tạo bảng vector nếu chưa có
        create_sql = f"""
        CREATE TABLE IF NOT EXISTS public."{table_name}" (
            id BIGSERIAL PRIMARY KEY,
            original_data JSONB,
            content_text TEXT,
            embedding DOUBLE PRECISION[],
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """

        conn.execute(text(create_sql))

        # Nếu bảng đã tồn tại với schema khác (ví dụ bảng business sẵn có),
        # bổ sung các cột phục vụ vector store nếu thiếu.
        alter_sql = f"""
        ALTER TABLE public."{table_name}"
            ADD COLUMN IF NOT EXISTS original_data JSONB,
            ADD COLUMN IF NOT EXISTS content_text TEXT,
            ADD COLUMN IF NOT EXISTS embedding DOUBLE PRECISION[],
            ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
        """

        conn.execute(text(alter_sql))
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


def insert_origin_rows(
    table_name: str,
    rows: List[Dict[str, Any]],
):
    """Insert vào bảng gốc (origin DB) theo data gửi lên.

    - table_name: tên bảng gốc, ví dụ "materials_qwen"
    - mỗi record: key = tên cột, value = giá trị cần insert
    """
    if not rows:
        logger.info("No rows to insert into origin table %s", table_name)
        return

    with origin_engine.begin() as conn:
        for r in rows:
            if not r:
                continue

            cols = list(r.keys())
            col_names = ", ".join(f'"{c}"' for c in cols)
            values_placeholders = ", ".join(f':{c}' for c in cols)

            insert_sql = text(
                f'INSERT INTO public."{table_name}" ({col_names}) '
                f'VALUES ({values_placeholders})'
            )

            conn.execute(insert_sql, r)

    logger.info(
        "Inserted %d rows into origin table %s",
        len(rows),
        table_name,
    )



def update_origin_rows(
    table_name: str,
    rows: List[Dict[str, Any]],
):
    if not rows:
        logger.info("No rows to update in origin table %s", table_name)
        return

    total_updated = 0

    with origin_engine.begin() as conn:
        for r in rows:
            if "id_sap" not in r:
                raise ValueError("Missing 'id_sap' in origin row for update")

            # tách id_sap và các cột cần update
            id_sap_val = r["id_sap"]
            columns_to_update = {k: v for k, v in r.items() if k != "id_sap"}

            if not columns_to_update:
                continue

            set_clauses = []
            params: Dict[str, Any] = {"id_sap": id_sap_val}

            for col, val in columns_to_update.items():
                # dùng tên cột đúng như key trong JSON
                set_clauses.append(f'"{col}" = :{col}')
                params[col] = val

            set_sql = ", ".join(set_clauses)

            update_sql = text(
                f'UPDATE public."{table_name}" '
                f'SET {set_sql} '
                f'WHERE "id_sap" = :id_sap'
            )

            result = conn.execute(update_sql, params)
            total_updated += result.rowcount or 0

    logger.info(
        "Updated %d rows in origin table %s",
        total_updated,
        table_name,
    )

def update_vector_rows(
    table_name: str,
    rows: List[Dict[str, Any]],
):
    if not rows:
        logger.info("No rows to update in %s", table_name)
        return

    serialized_rows = []

    for r in rows:
        r = r.copy()
        print('id_sap',r.get("id_sap"))
        print('content_text',r.get("content_text"))

        if "id_sap" not in r:
            raise ValueError("Missing 'id_sap' in row for update")

        # serialize json safely
        if isinstance(r.get("original_data"), dict):
            r["original_data"] = json.dumps(
                r["original_data"], ensure_ascii=False
            )

        serialized_rows.append(r)

    logger.info(
        "Updating %d vector rows in target table %s",
        len(serialized_rows),
        table_name,
    )

    update_sql = f"""
    UPDATE public."{table_name}"
    SET
        original_data = CAST(:original_data AS jsonb),
        content_text  = :content_text,
        embedding     = :embedding,
        created_at    = :created_at
    WHERE
        COALESCE(
            CAST(original_data AS jsonb) ->> 'id_sap',
            CAST(original_data AS jsonb) ->> 'ID_SAP'
        ) = :id_sap
    """

    with target_engine.begin() as conn:
        result = conn.execute(text(update_sql), serialized_rows)

    logger.info(
        "Updated %d rows in %s successfully",
        result.rowcount,
        table_name,
    )


def get_id_sap_by_material_name(
    table_name: str,
    material_name: str,
) -> Optional[Any]:
    """Tìm id_sap trong bảng gốc dựa vào material_name.

    Dùng cho API update theo key khi client chỉ gửi material_name.
    """

    query = text(
        f'SELECT "id_sap" FROM public."{table_name}" '
        f'WHERE "material_name" = :material_name LIMIT 1'
    )

    with origin_engine.connect() as conn:
        row = conn.execute(query, {"material_name": material_name}).first()

    if not row:
        return None

    return row[0]