import logging
from psycopg2 import sql
from connectDB import (
    get_main_db_connection,
    get_vector_db_connection,
)

from logServer import setup_logging
from data_material import batch_classify_materials


def copy_table_from_main_to_vector(table_name: str):
    """
    Copy toàn bộ table + data
    từ MAIN_DB_DATABASE sang VECTOR_DB_DATABASE.
    """

    main_conn = get_main_db_connection()
    vector_conn = get_vector_db_connection()

    try:
        # -------------------------
        # 1. Lấy cấu trúc table từ MAIN_DB
        # -------------------------
        with main_conn.cursor() as cur:
            cur.execute(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'public'
                    AND table_name = %s
                ORDER BY ordinal_position;
                """,
                (table_name,)
            )

            columns = cur.fetchall()
            if not columns:
                raise RuntimeError(f"Table {table_name} không tồn tại trong MAIN_DB")

        # Build CREATE TABLE SQL
        col_defs = []
        col_names = []
        for col, dtype, nullable in columns:
            null_sql = "" if nullable == "YES" else "NOT NULL"
            col_defs.append(f'"{col}" {dtype} {null_sql}')
            col_names.append(f'"{col}"')

        create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS public."{table_name}" (
                {", ".join(col_defs)}
            );
        """

        # -------------------------
        # 2. Tạo table ở VECTOR_DB
        # -------------------------
        with vector_conn.cursor() as cur:
            cur.execute(create_table_sql)
            cur.execute(f'TRUNCATE TABLE public."{table_name}";')
            vector_conn.commit()

        # -------------------------
        # 3. Copy data
        # -------------------------
        select_sql = f'SELECT {", ".join(col_names)} FROM public."{table_name}";'
        insert_sql = f'''
            INSERT INTO public."{table_name}" ({", ".join(col_names)})
            VALUES ({", ".join(["%s"] * len(col_names))});
        '''

        with main_conn.cursor() as main_cur, vector_conn.cursor() as vec_cur:
            main_cur.execute(select_sql)

            batch_size = 1000
            while True:
                rows = main_cur.fetchmany(batch_size)
                if not rows:
                    break
                vec_cur.executemany(insert_sql, rows)

            vector_conn.commit()

        logging.info(
            f"Đã copy table '{table_name}' từ MAIN_DB sang VECTOR_DB thành công"
        )

    finally:
        main_conn.close()
        vector_conn.close()

def main():
    copy_table_from_main_to_vector("ListMaterialsBOQ")
    copy_table_from_main_to_vector("MD_Material_SAP")
    
# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    log_file = setup_logging(log_dir="logs", name="convertDB")
    main()