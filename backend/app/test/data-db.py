import psycopg2
from psycopg2 import sql
import numpy as np

# Lấy danh sách bảng động từ TableSelectorLLM
from app.table_selector_llm import selector

# Kết nối database (giữ nguyên cấu hình mẫu; cập nhật theo môi trường của bạn)
conn = psycopg2.connect(database="your_db", user="your_user")
cursor = conn.cursor()

# Vector đầu vào (ví dụ: 768 dimensions)
input_vector = np.random.randn(768).tolist()

# Xây dựng truy vấn động dựa trên self.tables, không cố định bảng
tables = [(t.schema, t.table) for t in selector.tables]
if not tables:
    raise RuntimeError("Không có bảng nào trong selector.tables để truy vấn")

# Mỗi bảng tạo một SELECT trả về cùng schema cột để UNION ALL
select_clauses = []
params = []
for schema_name, table_name in tables:
    select_sql = sql.SQL(
        "SELECT {source} AS source_table, content_text, embedding <=> %s AS distance FROM {schema}.{table}"
    ).format(
        source=sql.Literal(sql.SQL("{}.{}".format(schema_name, table_name)).as_string(cursor)),
        schema=sql.Identifier(schema_name),
        table=sql.Identifier(table_name),
    )
    select_clauses.append(select_sql)
    params.append(input_vector)

union_sql = sql.SQL(" UNION ALL ").join(select_clauses)
final_sql = sql.SQL("SELECT * FROM ( ") + union_sql + sql.SQL(
    " ) AS all_results ORDER BY distance ASC LIMIT %s"
)

params.append(5)  # LIMIT

cursor.execute(final_sql, params)
results = cursor.fetchall()