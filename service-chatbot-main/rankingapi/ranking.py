
from typing import Dict

import psycopg2
from config import settings
from fastapi import APIRouter
from feedbackapi.feedback import get_feedback_boost_for_query

def get_db():
    return psycopg2.connect(**settings.DB_CONFIG)

router = APIRouter()
# ================================================================================================
# FUNCTION DEFINITIONS
# ================================================================================================

def rerank_with_feedback(items: list, feedback_scores: Dict, 
                         id_key: str = "headcode", boost_weight: float = 0.5):  # ← ✅ INCREASED from 0.3 → 0.5
    """
    🎯 V5.6 - Boost weight increased to 0.5 for stronger feedback impact
    """
    if not feedback_scores:
        print("⚠️ No feedback scores to rerank")
        return items
    
    max_feedback = max(feedback_scores.values()) if feedback_scores else 1
    
    print(f"\n{'='*60}")
    print(f"🎯 RERANKING: {len(items)} items | Boost weight: {boost_weight}")
    print(f"📊 Feedback history: {len(feedback_scores)} items have scores")
    print(f"{'='*60}\n")
    
    boosted_items = []
    unchanged_items = []
    
    for item in items:
        item_id = item.get(id_key)
        feedback_count = feedback_scores.get(item_id, 0)
        
        # Normalize feedback score 0-1
        feedback_boost = (feedback_count / max_feedback) if max_feedback > 0 else 0
        
        # ✅ IMPORTANT: Use 'similarity' (already set = personalized_score)
        current_score = item.get('similarity', item.get('relevance_score', 0.5))
        
        # ✅ New formula: Higher boost weight (0.5 instead of 0.3)
        new_score = (1 - boost_weight) * current_score + boost_weight * feedback_boost
        
        item['final_score'] = float(new_score)
        item['feedback_boost'] = float(feedback_boost)
        item['feedback_count'] = float(feedback_count)
        item['original_score'] = float(current_score)
        
        if feedback_count > 0:
            boosted_items.append(item)
            print(f"✅ BOOSTED: {item_id[:20]:20} | "
                  f"Original: {current_score:.3f} → "
                  f"Final: {new_score:.3f} | "
                  f"Feedback: {feedback_count:.2f} times")
        else:
            unchanged_items.append(item)
    
    print(f"\n📈 Results:")
    print(f"   - {len(boosted_items)} items boosted")
    print(f"   - {len(unchanged_items)} items unchanged")
    print(f"{'='*60}\n")
    
    return items  # Don't sort here, let search_products() sort later

def apply_feedback_to_search(items: list, query: str, search_type: str, 
                                id_key: str = "headcode") -> list:
    """
    🎯 V5.6 - Save original_rank BEFORE reranking
    """
    if not items:
        return items
    
    # ✅ SAVE ORIGINAL RANK (based on personalized_score)
    for idx, item in enumerate(items):
        item['original_rank'] = idx + 1
    
    # Get feedback scores
    feedback_scores = get_feedback_boost_for_query(
        query, 
        search_type,
        similarity_threshold=settings.SIMILARITY_THRESHOLD_MEDIUM
    )
    
    if not feedback_scores:
        print("ℹ️ No relevant feedback history")
        for item in items:
            item['has_feedback'] = False
            item['feedback_count'] = 0
            item['final_rank'] = items.index(item) + 1
            item['final_score'] = item.get('similarity', 0.5)
        return items
    
    print(f"\n🎯 Step 2: Feedback Ranking for {len(items)} items...")
    
    # Apply reranking
    reranked_items = rerank_with_feedback(
        items, 
        feedback_scores, 
        id_key=id_key, 
        boost_weight=0.5  # ✅ Boost weight cao
    )
    
    # ✅ SORT theo final_score (search_products sẽ sort lại lần cuối)
    reranked_items.sort(key=lambda x: x.get('final_score', 0), reverse=True)
    
    # Update final rank
    for idx, item in enumerate(reranked_items):
        item['final_rank'] = idx + 1
        item['has_feedback'] = item.get('feedback_count', 0) > 0
    
    print(f"✅ Feedback Ranking done\n")
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
    
# ================================================================================================
# API ENDPOINTS
# ================================================================================================
