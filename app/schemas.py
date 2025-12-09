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
    answer: str
    ocr_text: str = ""
    used_contexts: List[ContextDocument] = Field(default_factory=list)

class HealthStatusResponse(BaseModel):
    db_ok: bool
    ollama_ok: bool
    gemini_ok: bool
    ocr_ok: bool

class DocumentCountResponse(BaseModel):
    total: int
    per_table: Dict[str, int]