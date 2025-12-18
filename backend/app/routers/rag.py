from typing import List, Optional
from fastapi import APIRouter, HTTPException
from fastapi import status
from app.schemas import QueryRequest, QueryResponse, HealthStatusResponse, DocumentCountResponse, ContextDocument
from app.ocr import ocr_images_to_text, health_check_ocr
from app.db import health_check_db, similarity_search_table, count_documents_per_table, get_embedding_dimension
from app.llm import generate_answer, health_check_gemini
from app.config import settings
from app.table_selector_llm import selector
from PIL import Image
from io import BytesIO
import base64
rag_router = APIRouter()

from app.logger import setup_logger
logger = setup_logger(__name__)

@rag_router.post("/api/query", response_model=QueryResponse, summary="Query the RAG system with a text query")
async def query_rag(
    request: QueryRequest
):
    """
    Nhận object JSON với các trường:
    - text: Câu hỏi/đoạn văn bản (bắt buộc)
    - top_k: Số lượng kết quả trả về (mặc định từ settings)
    - min_score: Điểm tối thiểu (mặc định từ settings)
    - images: Danh sách base64 encoded images (tùy chọn)
    """
    logger.info("Received /api/query request: text=%s, top_k=%d, min_score=%.3f", 
                request.text, request.top_k, request.min_score)
    
    try:
        pil_images: List[Image.Image] = []
        
        # Xử lý images nếu có
        if request.images:
            for img_base64 in request.images:
                try:
                    # Loại bỏ phần header nếu có (data:image/png;base64,...)
                    if ',' in img_base64:
                        img_base64 = img_base64.split(',')[1]
                    
                    img_data = base64.b64decode(img_base64)
                    pil_images.append(Image.open(BytesIO(img_data)).convert("RGB"))
                except Exception as e:
                    logger.warning(f"Failed to decode base64 image: {e}")
                    # Tiếp tục xử lý các ảnh khác nếu có lỗi
        
        # Xử lý OCR từ ảnh
        ocr_text = ""
        if pil_images:
            # Chuyển đổi PIL Image sang bytes để sử dụng OCR
            image_bytes_list = []
            for img in pil_images:
                img_byte_arr = BytesIO()
                img.save(img_byte_arr, format='PNG')
                image_bytes_list.append(img_byte_arr.getvalue())
            
            if image_bytes_list:
                ocr_text = ocr_images_to_text(image_bytes_list)
        
        # Kết hợp text từ input và OCR
        user_text = (request.text or "").strip()
        merged_text = " ".join([t for t in [user_text, ocr_text] if t]).strip()
        
        if not merged_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Thiếu input: cần cung cấp text hoặc ít nhất một ảnh chứa chữ."
            )

        # Chọn bảng phù hợp
        selected = selector.select_best_table(merged_text)
        if not selected:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, 
                detail="Không tìm thấy bảng phù hợp theo schema mô tả."
            )
        
        schema, table, table_score = selected
        logger.info("Selected table: %s.%s (score=%.3f)", schema, table, table_score)

        # Truy vấn similarity
        hits = similarity_search_table(
            schema, 
            table, 
            merged_text, 
            top_k=request.top_k, 
            min_score=request.min_score
        )

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

        # Tạo câu trả lời
        answer = generate_answer(
            user_text or merged_text, 
            context_strings, 
            images=pil_images if pil_images else None
        )

        return QueryResponse(
            answer=answer, 
            ocr_text=ocr_text, 
            used_contexts=used_contexts
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unhandled error in /query: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail=f"Lỗi nội bộ khi xử lý truy vấn: {str(e)}"
        )