from typing import List, Optional
from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from fastapi import status
from app.schemas import QueryResponse, HealthStatusResponse, DocumentCountResponse, ContextDocument
from app.ocr import ocr_images_to_text, health_check_ocr
from app.embedding import embed_text, health_check_ollama
from app.db import health_check_db, similarity_search_table, count_documents_per_table, get_embedding_dimension
from app.llm import generate_answer, health_check_gemini
from app.config import settings
from app.table_selector import selector
from PIL import Image
from io import BytesIO
import logging

rag_router = APIRouter()
log = logging.getLogger("rag")

def _align_vector_dim(vec: List[float], target_dim: Optional[int]) -> List[float]:
    """
    Căn chỉnh chiều vector truy vấn cho phù hợp với cột 'embedding' trong bảng:
    - Nếu target_dim None: trả nguyên vec.
    - Nếu vec dài hơn: cắt bớt.
    - Nếu vec ngắn hơn: padding 0.
    """
    if not isinstance(vec, list) or target_dim is None:
        return vec
    if len(vec) == target_dim:
        return vec
    if len(vec) > target_dim:
        return vec[:target_dim]
    # pad
    return vec + [0.0] * (target_dim - len(vec))

@rag_router.post("/query", response_model=QueryResponse, summary="Query the RAG system with a text query")
async def query_rag(
    text: Optional[str] = Form(default=None, description="Câu hỏi/đoạn văn bản"),
    top_k: int = Form(default=settings.APP_TOP_K, ge=1, le=50),
    min_score: float = Form(default=settings.APP_MIN_SCORE, ge=0.0, le=1.0),
    files: Optional[List[UploadFile]] = File(default=None, description="Danh sách ảnh (image/*)"),
):
    try:
        # Collect images
        image_bytes_list: List[bytes] = []
        pil_images: List[Image] = []
        if files:
            for f in files:
                content = await f.read()
                if content:
                    image_bytes_list.append(content)
                    try:
                        pil_images.append(Image.open(BytesIO(content)).convert("RGB"))
                    except Exception:
                        pass

        ocr_text = ocr_images_to_text(image_bytes_list) if image_bytes_list else ""
        user_text = (text or "").strip()
        merged_text = " ".join([t for t in [user_text, ocr_text] if t]).strip()
        if not merged_text:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Thiếu input: cần cung cấp text hoặc ít nhất một ảnh chứa chữ.")

        # 1) Select one table
        selected = selector.select_best_table(merged_text)
        if not selected:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy bảng phù hợp theo schema mô tả.")
        schema, table, table_score = selected

        # 2) Embed query
        query_vec = embed_text(merged_text)

        # 3) Align dimension to table vector dim
        dim = get_embedding_dimension(schema, table)
        query_vec_aligned = _align_vector_dim(query_vec, dim)

        # 4) Vector search within selected table
        hits = similarity_search_table(schema, table, query_vec_aligned, top_k=top_k, min_score=min_score)

        # Build contexts
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

        # Nếu không có hit nào, vẫn gọi LLM với thông điệp rõ ràng
        if not context_strings:
            context_strings = [f"Không tìm thấy tài liệu phù hợp trong bảng {schema}.{table} cho câu hỏi này."]

        answer = generate_answer(user_text or merged_text, context_strings, images=pil_images if pil_images else None)

        return QueryResponse(answer=answer, ocr_text=ocr_text, used_contexts=used_contexts)

    except HTTPException:
        # fastapi HTTPException giữ nguyên
        raise
    except Exception as e:
        # Log lỗi nội bộ để tiện debug, trả về 500 có message ngắn gọn
        log.exception("Unhandled error in /query: %s", e)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Lỗi nội bộ khi xử lý truy vấn. Vui lòng kiểm tra nhật ký server.")

@rag_router.get("/health", response_model=HealthStatusResponse, summary="Get health status of the RAG system components.")
async def health():
    return HealthStatusResponse(
        db_ok=health_check_db(),
        ollama_ok=health_check_ollama(),
        gemini_ok=health_check_gemini(),
        ocr_ok=health_check_ocr(),
    )

@rag_router.get("/documents/count", response_model=DocumentCountResponse, summary="Get the total number of documents in the vector store.")
async def documents_count():
    per_table = count_documents_per_table()
    return DocumentCountResponse(total=sum(per_table.values()), per_table=per_table)