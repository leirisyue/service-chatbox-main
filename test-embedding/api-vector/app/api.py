from fastapi import APIRouter
from pydantic import BaseModel
from .services.qwen_service import embed_with_qwen_service
from .services.func import fetch_rows_from_table, ensure_embedding_tables
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/embeddings", tags=["Embeddings"])

class EmbedRequest(BaseModel):
    table_name: str
    limit: int = 1000

@router.post("/qwen")
def embed_qwen(req: EmbedRequest):
    logger.warning("POST /embeddings/qwen")
    ensure_embedding_tables()

    texts, raw_rows = fetch_rows_from_table(
        req.table_name,
        limit=req.limit
    )

    result = embed_with_qwen_service(
        table_name=req.table_name,
        texts=texts,
        raw_rows=raw_rows,
    )

    return {
        "status": "success",
        "data": result,
    }
