
import re
from typing import Dict, List, Optional

from pydantic import BaseModel

# ================================================================================================

class FeedbackRequest(BaseModel):
    session_id: str
    query: str
    selected_items: List[str]  # List of headcodes hoặc id_sap
    rejected_items: List[str] = []
    search_type: str  # "product" hoặc "material"

class ChatMessage(BaseModel):
    session_id: str
    message: str
    email: Optional[str] = None  # Make email optional for backward compatibility
    context: Optional[Dict] = {}

class BatchProductRequest(BaseModel):
    product_headcodes: List[str]
    session_id: str = ""
    operation: str  # "detail", "materials", "cost"

class ConsolidatedBOMRequest(BaseModel):
    product_headcodes: List[str]
    session_id: str = ""
    
class TrackingRequest(BaseModel):
    session_id: str
    product_headcode: str
    interaction_type: str  # 'view', 'reject', 'select'

