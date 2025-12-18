from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ContextDocument(BaseModel):
    table: str
    id: int
    score: float
    # DB may return JSON/dict for original_data; accept structured types
    original_data: Optional[Dict[str, Any]] = None
    content_text: Optional[str] = None

class QueryResponse(BaseModel):
    """Schema cho response từ /api/query"""
    answer: str
    ocr_text: str = ""
    used_contexts: List[ContextDocument] = []

class HealthStatusResponse(BaseModel):
    db_ok: bool
    ollama_ok: bool
    gemini_ok: bool
    ocr_ok: bool

class DocumentCountResponse(BaseModel):
    total: int
    per_table: Dict[str, int]
    
    
from pydantic import BaseModel, Field
from typing import List, Optional

class QueryRequest(BaseModel):
    """Schema cho request đến /api/query"""
    text: str = Field(..., description="Câu hỏi/đoạn văn bản")
    top_k: int = Field(default=5, ge=1, le=50, description="Số lượng kết quả trả về")
    min_score: float = Field(default=0.1, ge=0.0, le=1.0, description="Điểm tối thiểu")
    images: Optional[List[str]] = Field(
        default=None, 
        description="Danh sách ảnh dạng base64 string"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "text": "text",
                "top_k": 2,
                "min_score": 0.1
            }
        }