import logging
from psycopg2 import sql
from connectDB import (
    get_main_db_connection,
    get_vector_db_connection,
    get_fetch_db_connection,
    map_postgres_type,
)

from logServer import setup_logging
from func_gen_material_group import batch_classify_materials

_MAIN_DB_TUNNEL = None

def ensure_target_table_exists(target_table: str):
    """Đảm bảo TABLE đích tồn tại trong VECTOR_DB.

    Tạo đơn giản với các cột tối thiểu nếu chưa có.
    """
    conn = get_vector_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{target_table}" (
                    id SERIAL PRIMARY KEY,
                    id_sap TEXT UNIQUE,
                    material_name TEXT,
                    material_group TEXT,
                    material_subgroup TEXT,
                    idx INTEGER
                );
                """
            )
            # Với các bảng đã tồn tại từ trước, đảm bảo vẫn có cột id tự tăng và cột idx
            cur.execute(
                f"""
                ALTER TABLE "{target_table}"
                ADD COLUMN IF NOT EXISTS id SERIAL;
                """
            )
            cur.execute(
                f"""
                ALTER TABLE "{target_table}"
                ADD COLUMN IF NOT EXISTS idx INTEGER;
                """
            )
            conn.commit()
    finally:
        conn.close()

def classify_and_update_material_subgroup(
    source_view="MD_Material_SAP",
    target_table="MD_Material_SAP",
    batch_size=50,
):
    """Đọc dữ liệu từ VIEW trong FETCH_DB và cập nhật sang TABLE trong VECTOR_DB.

    - source_view: tên VIEW/BẢNG trong DB fetch (kết nối get_fetch_db_connection)
    - target_table: tên TABLE trong DB vector (kết nối get_vector_db_connection)
    """

    fetch_conn = get_fetch_db_connection()
    vector_conn = get_vector_db_connection()

    # Đảm bảo bảng đích tồn tại trước khi UPDATE
    ensure_target_table_exists(target_table)

    try:
        # Đọc dữ liệu nguồn từ VIEW/BẢNG trong FETCH_DB, bỏ các dòng không có id_sap
        with fetch_conn.cursor() as cur:
            cur.execute(
                f'''
                SELECT  "id_sap", "material_name", "material_group", "idx"
                FROM "{source_view}"
                WHERE "id_sap" IS NOT NULL AND "id_sap" <> ''
                OFFSET 20396 LIMIT 3000
                '''
            )
            rows = cur.fetchall()

        logging.info(f"Tổng material cần classify: {len(rows)}")

        # Gọi Gemini theo batch và ghi kết quả sang TABLE ở VECTOR_DB
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]

            materials_batch = [
                {
                    "id_sap": r[0],
                    "material_name": r[1] or "",
                    "material_group": r[2] or "",
                    "idx": r[3] or 0,
                }
                for r in batch
            ]

            # Map để lấy lại material_name, idx theo id_sap khi ghi sang bảng đích
            name_by_id = {
                m["id_sap"]: m["material_name"] for m in materials_batch
            }

            results = batch_classify_materials(materials_batch)

            with vector_conn.cursor() as cur:
                current_id_sap = None
                try:
                    for r in results:
                        # Bỏ qua kết quả không có id_sap để tránh chèn NULL vào khóa chính
                        if not r.get("id_sap"):
                            logging.warning("Bỏ qua kết quả không có id_sap: %s", r)
                            continue

                        material_name = name_by_id.get(r["id_sap"], "")
                        current_id_sap = r["id_sap"]

                        cur.execute(
                            f'''
                            INSERT INTO "{target_table}" (
                                id_sap,
                                material_name,
                                material_group,
                                material_subgroup,
                                idx
                            )
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (id_sap) DO NOTHING
                            RETURNING id_sap
                            ''',
                            (
                                r["id_sap"],
                                material_name,
                                r["material_group"],
                                r["material_subgroup"],
                                r.get("idx", 0)
                            ),
                        )

                        inserted_row = cur.fetchone()
                        if inserted_row is None:
                            logging.info(
                                "CONFLICT: id_sap=%s đã tồn tại trong bảng %s, bỏ qua không chèn mới",
                                r["id_sap"],
                                target_table,
                            )

                    # Sau khi xử lý xong cả batch_size thì mới commit một lần
                    vector_conn.commit()
                except Exception as e:
                    logging.exception(
                        "Không thể ghi dữ liệu cho id_sap=%s trong batch bắt đầu tại index=%s: %s",
                        current_id_sap,
                        i,
                        e,
                    )
                    vector_conn.rollback()

            logging.info(
                f"Đã xử lý {min(i + batch_size, len(rows))}/{len(rows)}"
            )

    finally:
        fetch_conn.close()
        vector_conn.close()


# ----------------------------------------------------------------------------------------------------
# tạo subgroup cho vật liệu
def main_classify_materials():
    classify_and_update_material_subgroup(
        source_view="VIEW_MATERIAL_MERGE",
        target_table="material_merge",
        batch_size=30
    )

# ----------------------------------------------------------------------------------------------------
if __name__ == "__main__":

    log_file = setup_logging(log_dir="logs", name="main_gen_material_group")
    
    main_classify_materials()
