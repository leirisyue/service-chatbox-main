from typing import List, Optional
from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from fastapi import status
from app.schemas import QueryResponse, HealthStatusResponse, DocumentCountResponse, ContextDocument
from app.ocr import ocr_images_to_text, health_check_ocr
from app.db import health_check_db, similarity_search_table, count_documents_per_table, get_embedding_dimension
from app.llm import generate_answer, health_check_gemini
from app.config import settings
from app.table_selector import selector
from PIL import Image
from io import BytesIO
rag_router = APIRouter()

from app.logger import setup_logger
logger = setup_logger(__name__)

@rag_router.post("/api/query", response_model=QueryResponse, summary="Query the RAG system with a text query")
async def query_rag(
    text: Optional[str] = Form(default=None, description="Câu hỏi/đoạn văn bản"),
    top_k: int = Form(default=settings.APP_TOP_K, ge=1, le=50),
    min_score: float = Form(default=settings.APP_MIN_SCORE, ge=0.0, le=1.0),
    # files: Optional[List[UploadFile]] = File(default=None, description="Danh sách ảnh (image/*)"),
):
    logger.info("Received /api/query request: text=%s, top_k=%d, min_score=%.3f",text, top_k, min_score)
    try:
        image_bytes_list: List[bytes] = []
        pil_images: List[Image] = []
        # if files:```
        #     for f in files:
        #         content = await f.read()
        #         if content:
        #             image_bytes_list.append(content)
        #             try:
        #                 pil_images.append(Image.open(BytesIO(content)).convert("RGB"))
        #             except Exception:
        #                 pass

        ocr_text = ocr_images_to_text(image_bytes_list) if image_bytes_list else ""
        user_text = (text or "").strip()
        merged_text = " ".join([t for t in [user_text, ocr_text] if t]).strip()
        if not merged_text:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Thiếu input: cần cung cấp text hoặc ít nhất một ảnh chứa chữ.")

        selected = selector.select_best_table(merged_text)
        if not selected:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy bảng phù hợp theo schema mô tả.")
        schema, table, table_score = selected
        logger.info("Selected table: %s.%s (score=%.3f)", schema, table, table_score)

        # Truy vấn similarity trực tiếp với text (db sẽ dùng EmbeddingService để embed bằng đúng model)
        hits = similarity_search_table(schema, table, merged_text, top_k=top_k, min_score=min_score)

        context_strings: List[str] = []
        used_contexts: List[ContextDocument] = []
        for h in hits:
            ctx_line = f"[{h['table']}#{h['id']} score={h['score']:.3f}]\noriginal_data: {h.get('original_data')}\ncontent_text: {h.get('content_text')}"
            context_strings.append(ctx_line)
            used_contexts.append(ContextDocument(
                table=h["table"],
                id=h["id"],
                score=float(h["score"] or 0.0),
                original_data=h.get("original_data"),
                content_text=h.get("content_text"),
            ))

        if not context_strings:
            context_strings = [f"Không tìm thấy tài liệu phù hợp trong bảng {schema}.{table} cho câu hỏi này."]

        answer = generate_answer(user_text or merged_text, context_strings, images=pil_images if pil_images else None)

        return QueryResponse(answer=answer, ocr_text=ocr_text, used_contexts=used_contexts)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unhandled error in /query: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Lỗi nội bộ khi xử lý truy vấn: {str(e)}")