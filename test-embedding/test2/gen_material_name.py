import uuid
import json
import pandas as pd
import os

import google.generativeai as genai
from psycopg2 import connect
from psycopg2.extras import RealDictCursor

# ===================== CONFIG =====================
from connectDB import (
    get_main_db_connection,
    get_vector_db_connection,
    map_postgres_type,
)


# ==================================================

My_GOOGLE_API_KEY = os.getenv("My_GOOGLE_API_KEY", "localhost") 


# ================= CONFIG GEMINI =================
genai.configure(
    api_key=os.getenv("My_GOOGLE_API_KEY", "localhost")
)
model = genai.GenerativeModel("gemini-2.5-flash-lite")


OUTPUT_FILE = "ListMaterialsBOQ_MaterialName.xlsx"
BATCH_LOG = 20

import re

def rule_based_material_name(description: str) -> str | None:
    text = description.lower()

    # ---- FABRIC / VẢI ----
    if "vải" in text or "fabric" in text:
        m = re.search(r"(vải[^.\n,]{0,60})", description, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return "Vải bọc nội thất"

    # ---- MARBLE / ĐÁ ----
    if "marble" in text or "đá cẩm thạch" in text:
        return "Đá Marble (Đá cẩm thạch)"

    if "granite" in text:
        return "Đá Granite"

    if "stone" in text or "đá" in text:
        return "Đá tự nhiên"

    # ---- WOOD ----
    if "wood" in text or "gỗ" in text:
        return "Gỗ nội thất"

    # ---- METAL ----
    if "steel" in text or "kim loại" in text:
        return "Kim loại"

    return None

# --------------------------------------------------
def generate_material_name(description: str) -> str:
    """
    Sinh tên vật liệu ngắn gọn từ description
    """

    if not description or not description.strip():
        return "Không xác định"

    # ✅ 1️⃣ RULE-BASED TRƯỚC
    rule_name = rule_based_material_name(description)
    if rule_name:
        return rule_name
      
    prompt = f"""
            You are a material naming assistant.

            From the following description, generate a SHORT, CLEAN Vietnamese material name.

            Rules:
            - Remove specs, notes, approvals
            - Keep material type + main usage
            - If code exists, keep it
            - Max 8–10 words
            - Vietnamese

            Description:
            \"\"\"{description}\"\"\"

            Return ONLY the name.
          """

    try:
        response = model.generate_content(
                prompt,
                request_options={"timeout": 20}
            )
        if response.text:
            return response.text.strip()

    except Exception as e:
        print(f"Gemini error: {e}")

    return "Không xác định"


# --------------------------------------------------
def generate_excel_from_table(
    table_name: str,
    description_column: str,
    id_column: str = "ID",
    limit: int = 10000,
    output_file: str = "material_name_output.xlsx",
):

    conn = get_main_db_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                f'''
                SELECT "{id_column}", "{description_column}"
                FROM public."{table_name}"
                LIMIT %s
                ''',
                (limit,)
            )
            rows = cur.fetchall()

        print(f"Đã đọc {len(rows)} dòng từ bảng {table_name}")

        output_rows = []

        for idx, row in enumerate(rows, 1):
            id_val = row[0]
            desc = row[1] or ""
            
            name_material = generate_material_name(desc)

            output_rows.append({
                "ID": id_val,
                "Name_Material": name_material,
                "ID_Material": str(uuid.uuid4())
            })

            if idx % 20 == 0:
                print(f"Đã xử lý {idx}/{len(rows)}")

        df = pd.DataFrame(output_rows)
        df.to_excel(output_file, index=False)

        print(f"✅ Đã xuất file Excel: {output_file}")

    finally:
        conn.close()


# --------------------------------------------------
if __name__ == "__main__":
    generate_excel_from_table(
        table_name="ListMaterialsBOQ",
        description_column="description",
        id_column="id",
        # limit=10,
        output_file="ListMaterialsBOQ_MaterialName.xlsx"
    )




