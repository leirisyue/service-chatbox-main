import logging
from psycopg2 import sql
from connectDB import (
    get_fetch_db_connection
)

from logServer import setup_logging
from data_material import batch_classify_materials

def validate_main_tables_exist():
    conn = get_fetch_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
            AND table_name IN ('ListMaterialsBOQ', 'MD_Material_SAP');
    """)

    tables = {row[0] for row in cur.fetchall()}
    cur.close()
    conn.close()

    missing = {"ListMaterialsBOQ", "MD_Material_SAP"} - tables
    if missing:
        raise RuntimeError(f"Missing tables in MAIN DB: {missing}")


def generate_cross_db_view_sql(
    fdw_schema,
    table_1,
    table_2,
    columns_t1,
    columns_t2,
    alias_columns,
    join_condition,
    view_schema,
    view_name,
    separator=" - ",
):
    """(Giữ lại để tham khảo SQL VIEW, nhưng không còn dùng để CREATE VIEW).

    Hàm này hiện không còn được dùng trong main(); logic chính đã
    chuyển sang tạo bảng merge trong VECTOR DB để tránh lỗi quyền
    CREATE VIEW trên MAIN DB.
    """

    select_parts = []
    for c1, c2, alias in zip(columns_t1, columns_t2, alias_columns):
        select_parts.append(
            f"CONCAT_WS('{separator}', "
            f"t1.\"{c1}\", t2.\"{c2}\") AS \"{alias}\""
        )

    return f"""
            CREATE VIEW "{view_schema}".{view_name} AS
            SELECT
                {", ".join(select_parts)}
            FROM "{fdw_schema}"."{table_1}" t1
            JOIN "{fdw_schema}"."{table_2}" t2
                ON {join_condition};
            """.strip()


def build_merge_rows_from_main_db():
    conn = get_fetch_db_connection()
    try:
        with conn.cursor() as cur:
            # 1. Create or replace VIEW
            cur.execute(
                '''
                CREATE VIEW public."VIEW_MATERIAL_MERGE" AS
                SELECT
                    CONCAT_WS(' - ',
                        t1."idMaterial",
                        t1."NameMaterial"
                    ) AS name,
                    t1."NameMaterial" AS description
                FROM public."ListMaterialsBOQ" t1

                UNION ALL

                SELECT
                    CONCAT_WS(' - ',
                        t2."ID_Material_SAP",
                        t2."Des_Material_Sap"
                    ) AS name,
                    t2."Des_Material_Sap" AS description
                FROM public."MD_Material_SAP" t2;
                '''
            )

            # 2. Query view
            cur.execute(
                'SELECT name, description FROM public."VIEW_MATERIAL_MERGE";'
            )
            rows = cur.fetchall()

            logging.info(f"Đã merge {len(rows)} dòng từ VIEW")
            return rows
    finally:
        conn.close()


def build_merge_view_in_pthsp():
    conn = get_fetch_db_connection()
    try:
        with conn.cursor() as cur:
            # kiểm tra db
            cur.execute("SELECT current_database();")
            db = cur.fetchone()[0]
            logging.info(f"Connected DB: {db}")

            cur.execute(
                '''
                CREATE OR REPLACE VIEW public."VIEW_MATERIAL_MERGE" AS
                SELECT
                    t1."idMaterial" AS id_sap,
                    t1."NameMaterial" AS description,
                    t1."codeSuplier" AS material_group,
                    t1."unit" AS unit,
                    t1."imagesURL" as images_url,
                    t1."createdAt" as created_at,
                    t1."updatedAt" as updated_at
                FROM public."ListMaterialsBOQ" t1

                UNION ALL

                SELECT
                    t2."ID_Material_SAP" AS id_sap,
                    t2."Des_Material_Sap" AS description,
                    t2."materialGroupDescription" AS material_group,
                    t2."Base_Unit" AS unit,
                    t2."images_url" as images_url,
                    t2."createdAt" as created_at,
                    t2."updatedAt" as updated_at
                FROM public."MD_Material_SAP" t2;
                '''
            )

            conn.commit()

            logging.info("VIEW VIEW_MATERIAL_MERGE đã được lưu trong DB PTHSP")

    finally:
        conn.close()


def main():
    try:
        logging.info("Validate source tables in MAIN DB")
        validate_main_tables_exist()

        logging.info("Merge dữ liệu từ 2 table (NO JOIN)")
        build_merge_view_in_pthsp()

        logging.info("Hoàn tất merge dữ liệu")

    except Exception:
        logging.exception("Merge failed")
        raise

# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    log_file = setup_logging(log_dir="logs", name="convertDB")
    main()