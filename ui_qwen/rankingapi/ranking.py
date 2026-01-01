
import json
from datetime import datetime
from typing import Dict, List, Optional

import psycopg2
from config import settings
from fastapi import APIRouter, HTTPException, Request
from psycopg2.extras import RealDictCursor
from chatapi.unit import FeedbackRequest
from feedbackapi.feedback import get_feedback_boost_for_query

def get_db():
    return psycopg2.connect(**settings.DB_CONFIG)

router = APIRouter()
# ========================================
# FUNCTION DEFINITIONS
# ========================================
def rerank_with_feedback(items: list, feedback_scores: Dict, id_key: str = "headcode", boost_weight: float = 0.3):
    
    if not feedback_scores:
        print("WARNING: Không có feedback scores để rerank")
        return items
    
    max_feedback = max(feedback_scores.values()) if feedback_scores else 1
    
    print(f"\n{'='*60}")
    print(f"RERANKING: {len(items)} items | Boost weight: {boost_weight}")
    print(f"Feedback history: {len(feedback_scores)} items có điểm")
    print(f"{'='*60}\n")
    
    boosted_items = []
    unchanged_items = []
    
    for item in items:
        item_id = item.get(id_key)
        feedback_count = feedback_scores.get(item_id, 0)
        
        # Normalize feedback score 0-1
        feedback_boost = (feedback_count / max_feedback) if max_feedback > 0 else 0
        
        # Tính điểm hiện tại
        current_score = item.get('similarity', item.get('relevance_score', 0.5))
        
        # Kết hợp: weighted average
        new_score = (1 - boost_weight) * current_score + boost_weight * feedback_boost
        
        item['final_score'] = new_score
        item['feedback_boost'] = feedback_boost
        item['feedback_count'] = feedback_count
        item['original_score'] = current_score
        
        # Phân loại
        if feedback_count > 0:
            boosted_items.append(item)
            print(f"SUCCESS: BOOSTED: {item_id[:20]:20} | "
                    f"Original: {current_score:.3f} → "
                    f"Final: {new_score:.3f} | "
                    f"Feedback: {feedback_count:.2f} lần")
        else:
            unchanged_items.append(item)
    
    # Sort lại theo final_score
    items.sort(key=lambda x: x.get('final_score', 0), reverse=True)
    
    print(f"\nINFO: Kết quả:")
    print(f"   - {len(boosted_items)} items được boost")
    print(f"   - {len(unchanged_items)} items không đổi")
    print(f"{'='*60}\n")
    
    return items



def apply_feedback_to_search(items: list, query: str, search_type: str, id_key: str = "headcode") -> list:
    """
    Tự động áp dụng feedback ranking cho MỌI loại search
    - Lấy feedback history
    - Rerank items
    - Thêm metadata để UI hiển thị
    
    Args:
        items: Danh sách products/materials
        query: Câu query gốc
        search_type: "product" hoặc "material"
        id_key: "headcode" hoặc "id_sap"
    
    Returns:
        List items đã được rerank + metadata
    """
    if not items:
        return items
    
    # ✅ TĂNG threshold từ 0.7 → 0.85
    feedback_scores = get_feedback_boost_for_query(
        query, 
        search_type,
        similarity_threshold=0.85  # ✅ CHỈ KHỚP QUERY RẤT GIỐNG NHAU
    )
    
    if not feedback_scores:
        print("INFO: Không có feedback history phù hợp (similarity < 0.85)")
        # Thêm metadata mặc định
        for item in items:
            item['has_feedback'] = False
            item['feedback_count'] = 0
            item['original_rank'] = items.index(item) + 1
            item['final_rank'] = items.index(item) + 1
        return items
    
    # Apply reranking
    print(f"\nINFO: Áp dụng feedback ranking cho {len(items)} items...")
    
    # Lưu rank gốc
    for idx, item in enumerate(items):
        item['original_rank'] = idx + 1
    
    # Rerank
    reranked_items = rerank_with_feedback(
        items, 
        feedback_scores, 
        id_key=id_key, 
        boost_weight=0.3
    )
    
    # Thêm final rank
    for idx, item in enumerate(reranked_items):
        item['final_rank'] = idx + 1
        item['has_feedback'] = item.get('feedback_count', 0) > 0
    
    print(f"SUCCESS: Reranking hoàn tất\n")
    return reranked_items



def get_ranking_summary(items: list) -> dict:
    """
    Tạo summary về ranking để hiển thị trong UI
    Returns:
        {
            "total_items": 10,
            "boosted_items": 3,
            "max_boost": 5,
            "ranking_changes": [
                {"id": "B001", "from": 5, "to": 1},
                ...
            ]
        }
    """
    if not items:
        return {
            "total_items": 0,
            "boosted_items": 0,
            "ranking_applied": False
        }
    
    boosted = [i for i in items if i.get('feedback_count', 0) > 0]
    
    changes = []
    for item in items:
        orig = item.get('original_rank')
        final = item.get('final_rank')
        
        if orig and final and orig != final:
            changes.append({
                "id": item.get('headcode') or item.get('id_sap'),
                "name": (item.get('product_name') or item.get('material_name', ''))[:30],
                "from_rank": orig,
                "to_rank": final,
                "boost": orig - final  # Positive = moved up
            })
    
    # Sort by biggest boost first
    changes.sort(key=lambda x: x['boost'], reverse=True)
    
    return {
        "total_items": len(items),
        "boosted_items": len(boosted),
        "ranking_applied": len(boosted) > 0,
        "max_feedback_count": max([i.get('feedback_count', 0) for i in items]),
        "ranking_changes": changes[:5]  # Top 5 changes
    }
    
# ========================================
# API ENDPOINTS
# ========================================
