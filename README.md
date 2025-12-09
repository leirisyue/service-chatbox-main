Truy cập API tại: http://localhost:8000
Truy cập Swagger UI tại: http://localhost:8000/docs

### 1. tạo môi trường
```bash
python -m venv .venv  
.venv\Scripts\activate
```

### 2. Cài thư viện python
```bash
python -m pip install -r requirements.txt
```

### 3. Build lại image từ Dockerfile (không dùng cache)
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

# fix error
sau khi install thư viện tắt VSCode chạy lại bước 1

### Kiểm tra logs
```bash
docker-compose logs -f rag-service
```



