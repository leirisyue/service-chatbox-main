python -m venv .venv  
.venv\Scripts\activate

# Cài đặt thư viện cần thiết
pip install -r requirements.txt

# Đã cấu hình .env 
python embed_test.py --table MD_Material_SAP --limit 100

python embed_test_with_logging.py --table MD_Material_SAP --limit 100


### main
python embed_test_with_logging_and_db.py --table MD_Material_SAP_T --limit 1000
python embed_test_with_logging_and_db_config.py --table materials_qwen --limit 1000

python embed_test_with_logging_and_db_batch.py --table MD_Material_SAP --limit 10


psql -U postgres -d db_vector -f pgvector.sql   

python test_search_accuracy.py --model gemini --query "GỖ" --top_k 10
python test_search_accuracy.py --model qwen --query "GỖ" --top_k 10
python test_search_accuracy.py --model opensearch_sparse --query "GỖ" --top_k 10