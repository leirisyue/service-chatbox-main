
### 1. Tạo môi trường
```bash
python -m venv .venv  
.venv\Scripts\activate
uvicorn app.main:app --reload
```
### 2. Bật entrypoint trong git
```bash
chmod +x ollama-entrypoint.sh
```
### 3. Run docker
```bash
docker-compose up --build
```

### 4. Shutdown docker
```bash
docker-compose down
```
