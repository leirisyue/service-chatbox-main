import logging
from psycopg2 import sql
from connectDB import (
    get_main_db_connection,
    get_vector_db_connection,
    map_postgres_type,
)

from logServer import setup_logging
from data_material import batch_classify_materials

_MAIN_DB_TUNNEL = None


def get_table_columns(conn, table_name, schema="public"):
    query = """
        SELECT
            column_name,
            data_type,
            is_nullable,
            column_default,
            udt_name
        FROM information_schema.columns
        WHERE table_schema = %s
            AND table_name = %s
        ORDER BY ordinal_position;
    """
    with conn.cursor() as cur:
        cur.execute(query, (schema, table_name))
        return cur.fetchall()


def create_table_on_vector_db(
    source_table_name,
    selected_columns,
    source_schema="public",
    target_schema="public",
    drop_if_exists=True,
):
    """
    - Giữ NGUYÊN tên bảng
    - Giữ NGUYÊN tên cột trong SELECTED_COLUMNS (hoa/thường)
    """

    # 1. Lấy schema từ MAIN_DB
    main_conn = get_main_db_connection()
    try:
        columns = get_table_columns(
            main_conn,
            source_table_name,
            source_schema,
        )
    finally:
        main_conn.close()

    column_map = {c[0]: c for c in columns}

    # 2. Validate SELECTED_COLUMNS
    for col in selected_columns:
        if col not in column_map:
            raise ValueError(f"Cột '{col}' không tồn tại")

    column_defs = []

    # 3. id auto increment
    column_defs.append(
        sql.SQL("id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY")
    )

    # 4. Các cột dữ liệu – QUAN TRỌNG: dùng Identifier
    for col in selected_columns:
        _, data_type, is_nullable, _, udt_name = column_map[col]
        col_type = map_postgres_type(data_type, udt_name)
        nullable_sql = "" if is_nullable == "YES" else "NOT NULL"

        column_defs.append(
            sql.SQL("{} {} {}").format(
                sql.Identifier(col), 
                sql.SQL(col_type),
                sql.SQL(nullable_sql),
            )
        )

    # 5. CREATE TABLE
    create_sql = sql.SQL("""
        CREATE TABLE {schema}.{table} (
            {columns}
        )
        """).format(
            schema=sql.Identifier(target_schema),
            table=sql.Identifier(source_table_name),
            columns=sql.SQL(", ").join(column_defs),
        )

    vector_conn = get_vector_db_connection()
    try:
        with vector_conn.cursor() as cur:
            if drop_if_exists:
                cur.execute(
                    sql.SQL("DROP TABLE IF EXISTS {schema}.{table} CASCADE")
                    .format(
                        schema=sql.Identifier(target_schema),
                        table=sql.Identifier(source_table_name),
                    )
                )

            cur.execute(create_sql)
            vector_conn.commit()
    finally:
        vector_conn.close()

    logging.info(
        f"Đã tạo bảng VECTOR_DB: {target_schema}.{source_table_name}"
    )


def copy_data_to_vector_db_new(
    table_name,
    selected_columns,
    source_pk=None,
    source_schema="public",
    target_schema="public",
    batch_size=1000,
):

    if source_pk and source_pk in selected_columns:
        raise ValueError(
            f"selected_columns KHÔNG được chứa source_pk ({source_pk})"
        )

    main_conn = get_main_db_connection()
    vector_conn = get_vector_db_connection()

    try:
        main_cur = main_conn.cursor(name="server_cursor")
        vector_cur = vector_conn.cursor()

        # SELECT từ MAIN_DB
        select_fields = (
            [source_pk] + selected_columns
            if source_pk else selected_columns
        )

        select_sql = sql.SQL("""
            SELECT {fields}
            FROM {schema}.{table}
            LIMIT 1000
        """).format(
            fields=sql.SQL(", ").join(map(sql.Identifier, select_fields)),
            schema=sql.Identifier(source_schema),
            table=sql.Identifier(table_name),
        )

        # INSERT vào VECTOR_DB
        insert_cols = (
            ["source_id"] + selected_columns
            if source_pk else selected_columns
        )

        insert_sql = sql.SQL("""
            INSERT INTO {schema}.{table} ({fields})
            VALUES ({placeholders})
        """).format(
            schema=sql.Identifier(target_schema),
            table=sql.Identifier(table_name),
            fields=sql.SQL(", ").join(map(sql.Identifier, insert_cols)),
            placeholders=sql.SQL(", ").join(
                sql.Placeholder() * len(insert_cols)
            ),
        )

        main_cur.execute(select_sql)

        while True:
            rows = main_cur.fetchmany(batch_size)
            if not rows:
                break

            values = []
            for row in rows:
                row = list(row)

                if source_pk:
                    source_id = row[0]
                    data_cols = row[1:]
                    values.append([source_id] + data_cols)
                else:
                    values.append(row)

            vector_cur.executemany(insert_sql, values)
            vector_conn.commit()

            logging.info(f"Inserted {len(values)} rows")

    finally:
        main_cur.close()
        vector_cur.close()
        main_conn.close()
        vector_conn.close()


def classify_and_update_material_subgroup(
    table_name="MD_Material_SAP",
    batch_size=50
):
    conn = get_vector_db_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(f'''
                SELECT "ID_Material_SAP", "Des_Material_Sap"
                FROM "{table_name}"
                WHERE Material_Subgroup IS NULL
                    OR Material_Subgroup = ''
            ''')
            rows = cur.fetchall()

        logging.info(f"Tổng material cần classify: {len(rows)}")

        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]

            materials_batch = [
                {
                    "ID_Material_SAP": r[0],
                    "name": r[1] or ""
                }
                for r in batch
            ]

            results = batch_classify_materials(materials_batch)
            # logging.info(
            #     f"Kết quả: {results}"
            # )
            with conn.cursor() as cur:
                for r in results:
                    cur.execute(
                        f'''
                        UPDATE "{table_name}"
                        SET Material_Subgroup = %s
                        WHERE "ID_Material_SAP" = %s
                        ''',
                        (
                            r["material_subgroup"],
                            r["ID_Material_SAP"]
                        )
                    )
                conn.commit()

            logging.info(
                f"Đã xử lý {min(i + batch_size, len(rows))}/{len(rows)}"
            )

    finally:
        conn.close()


def add_material_subgroup_column(
    table_name,
    schema="public"
):
    conn = get_vector_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f'''
                ALTER TABLE "{schema}"."{table_name}"
                ADD COLUMN IF NOT EXISTS Material_Subgroup TEXT
            ''')
            conn.commit()
            logging.info("Đã thêm cột Material_Subgroup vào VECTOR_DB")
    finally:
        conn.close()


def sync_table_columns_generic(
    source_table,
    target_table,
    source_columns,
    target_columns,
    key_target_col,  
    key_source_col,   

    source_schema="public",
    target_schema="public",

    batch_size=1000,
):
    if len(source_columns) != len(target_columns):
        raise ValueError(
            "source_columns và target_columns phải có cùng độ dài"
        )

    main_conn = get_main_db_connection()
    vector_conn = get_vector_db_connection()

    try:
        main_cur = main_conn.cursor(name="sync_cursor")
        vector_cur = vector_conn.cursor()

        # SELECT source
        select_sql = sql.SQL("""
            SELECT {fields}
            FROM {schema}.{table}
            WHERE {key} IS NOT NULL
        """).format(
            fields=sql.SQL(", ").join(map(sql.Identifier, source_columns)),
            schema=sql.Identifier(source_schema),
            table=sql.Identifier(source_table),
            key=sql.Identifier(key_source_col),
        )

        main_cur.execute(select_sql)

        # UPDATE SQL
        update_cols = [
            col for col in target_columns
            if col != key_target_col
        ]

        update_sql = sql.SQL("""
            UPDATE {schema}.{table}
            SET {updates}
            WHERE {key} = %s
        """).format(
            schema=sql.Identifier(target_schema),
            table=sql.Identifier(target_table),
            key=sql.Identifier(key_target_col),
            updates=sql.SQL(", ").join(
                sql.SQL("{} = %s").format(sql.Identifier(col))
                for col in update_cols
            ),
        )

        # INSERT SQL
        insert_sql = sql.SQL("""
            INSERT INTO {schema}.{table}
                ({fields})
            VALUES ({placeholders})
        """).format(
            schema=sql.Identifier(target_schema),
            table=sql.Identifier(target_table),
            fields=sql.SQL(", ").join(map(sql.Identifier, target_columns)),
            placeholders=sql.SQL(", ").join(
                sql.Placeholder() * len(target_columns)
            ),
        )

        total = 0

        while True:
            rows = main_cur.fetchmany(batch_size)
            if not rows:
                break

            for row in rows:
                data_map = dict(zip(target_columns, row))
                key_value = data_map[key_target_col]

                update_values = [
                    data_map[col] for col in update_cols
                ] + [key_value]

                vector_cur.execute(update_sql, update_values)

                if vector_cur.rowcount == 0:
                    vector_cur.execute(insert_sql, row)

            vector_conn.commit()
            total += len(rows)

            logging.info(f"Đã sync {total} records")

    finally:
        main_cur.close()
        vector_cur.close()
        main_conn.close()
        vector_conn.close()


# ----------------------------------------------------------------------------------------------------
def main():
    SOURCE_TABLE = "MD_Material_SAP"
    SELECTED_COLUMNS = [
        "ID_Material_SAP",
        "Des_Material_Sap"
    ]

    try:
        logging.info("Bắt đầu migrate schema + data")

        create_table_on_vector_db(
            source_table_name=SOURCE_TABLE,
            selected_columns=SELECTED_COLUMNS,
            drop_if_exists=True,
        )
        
        logging.info("copy data...")
        
        copy_data_to_vector_db_new(
            table_name=SOURCE_TABLE,
            selected_columns=SELECTED_COLUMNS,
        )
        
        logging.info("Xử lý data...")
        add_material_subgroup_column(SOURCE_TABLE)
        
        logging.info("Hoàn tất migrate DB")
        
    except Exception:
        logging.exception("Migration failed")
        raise

    finally:
        global _MAIN_DB_TUNNEL
        if _MAIN_DB_TUNNEL:
            _MAIN_DB_TUNNEL.stop()
            _MAIN_DB_TUNNEL = None

# ----------------------------------------------------------------------------------------------------
# đồng bộ dữ liệu từ MAIN_DB sang VECTOR_DB
def main_sync_data():
    sync_table_columns_generic(
        source_table="ListMaterialsBOQ",
        target_table="MD_Material_SAP",

        source_columns=[
            "idMaterial",
            "NameMaterial",
        ],
        target_columns=[
            "ID_Material_SAP",
            "Des_Material_Sap",
        ],
        key_target_col="ID_Material_SAP",
        key_source_col="idMaterial",
        batch_size=1000,
    )

# ----------------------------------------------------------------------------------------------------
# tạo subgroup cho vật liệu
def main_classify_materials():
    classify_and_update_material_subgroup(
        table_name="MD_Material_SAP",
        batch_size=30
    )

# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":

    log_file = setup_logging(log_dir="logs", name="convertDB")

    # main()
    # main_sync_data()
    # main_classify_materials()