from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import psycopg2
from historiesapi.histories import router as history_router
from imageapi.media import router as media_router
from chatapi.classifyapi import router as classify_router
from chatapi.debugapi import router as debug_router
from chatapi.embeddingapi import router as embeddings_router
from chatapi.importapi import router as importapi_router
from chatapi.textapi_qwen import router as textapi_router
from config import settings

def get_db():
    return psycopg2.connect(**settings.DB_CONFIG)

app = FastAPI(title="AA Corporation Chatbot API", version="4.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {
        "app": "AA Corporation Chatbot API", 
        "version": "4.2",
        "status": "Running",
        "features": [
            "✅ Queue-based batch classification",
            "✅ Import first, classify later",
            "✅ Batch size 8-10 items/call",
            "✅ Save Gemini quota",
            "✅ NULL safety 100%",
            "✅ Chat history with time blocks (0-12h, 12-24h)"
        ],
        "endpoints": {
            "chat": "POST /chat",
            "search_image": "POST /search-image",
            "import_products": "POST /import/products",
            "import_materials": "POST /import/materials",
            "import_pm": "POST /import/product-materials",
            "classify_products": "POST /classify-products 🆕",
            "classify_materials": "POST /classify-materials 🆕",
            "generate_embeddings": "POST /generate-embeddings",
            "generate_material_embeddings": "POST /generate-material-embeddings",
            "chat_histories": "GET /chat_histories/{email}/{session_id} 🆕",
            "user_sessions": "GET /chat_histories/{email} 🆕",
            "debug": "GET /debug/products, /debug/materials, /debug/chat-history"
        }
    }

app.include_router(media_router)
app.include_router(history_router)
app.include_router(classify_router)
app.include_router(debug_router)
app.include_router(embeddings_router)
app.include_router(importapi_router)    
app.include_router(textapi_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)