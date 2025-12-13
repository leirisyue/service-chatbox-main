import psycopg2
import numpy as np

# Kết nối database
conn = psycopg2.connect(database="your_db", user="your_user")
cursor = conn.cursor()

# Vector đầu vào (ví dụ: 768 dimensions)
input_vector = np.random.randn(768).tolist()

# Truy vấn
cursor.execute("""
    SELECT content_text, embedding <=> %s AS distance
    FROM bompk_data
    ORDER BY embedding <=> %s
    LIMIT 5
""", (input_vector, input_vector))

results = cursor.fetchall()