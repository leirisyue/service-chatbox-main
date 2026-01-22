Truy cập API tại: http://localhost:8000

Truy cập Swagger UI tại: http://localhost:8000/docs

Trong /app/config.py thay đổi file .env theo cấu hình phù hợp (docker/local)

# Run with docker compose

### 1. Tạo môi trường
```bash
python -m venv .venv  
.venv\Scripts\activate
```

### 2. Build lại image từ Dockerfile (không dùng cache)
```bash
docker-compose build --no-cache
```
### 4. Khởi động với Docker Compose 
```bash
docker-compose up
# or
docker-compose up -d
# or
docker-compose up --build
```
### Kiểm tra logs
```bash
docker-compose logs -f rag-service
```

# Run locally (without docker)

### 0. Prerequisites (Windows)
- Install Python 3.10+ and ensure `python` is on PATH.
- Install PostgreSQL and create database 
- Install or run Ollama locally: https://ollama.com
- 

### 1. Tạo môi trường
```bash
python -m venv .venv  
.venv\Scripts\activate
```

### 2. Install python lib
```bash
# Nếu chưa có pip
python -m pip install --upgrade pip
# Cài đặt thư viện cần thiết
pip install -r requirements.txt
```

### 3. Start Ollama service and pull model
```bash
ollama pull qwen3-embedding:latest
```

### 4. Configure environment
Tạo biến môi trường từ mẫu `.env.example` 
Chú ý thay đổi thông tin phù hợp
```bash
cp .env.example .env
```

### 5. Run the API locally
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```


đang tìm kiếm trong cơ sở dữ liệu