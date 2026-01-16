
import json
from typing import Dict

import psycopg2
from config import settings
from fastapi import APIRouter
from psycopg2.extras import RealDictCursor
from chatapi.unit import FeedbackRequest
from chatapi.embeddingapi import generate_embedding_qwen

def get_db():
    return psycopg2.connect(**settings.DB_CONFIG)

router = APIRouter()
# ================================================================================================
# FUNCTION DEFINITIONS
# ================================================================================================

def get_feedback_boost_for_query(query: str, search_type: str, similarity_threshold: float = 0.7) -> Dict:
    """
    V5.0 - Vector-based feedback matching
    Find feedback from SIMILAR queries (doesn't need to match 100%)
    
    Args:
        query: Current question
        search_type: "product" or "material"
        similarity_threshold: Similarity threshold (0.6 = 60%)
    
    Returns:
        Dict[item_id, feedback_score]
    """
    try:
        # 1. Generate embedding for current query
        query_vector = generate_embedding_qwen(query)
        
        if not query_vector:
            print("ERROR: Cannot generate embedding for query")
            return {}
        
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # 2. Find feedbacks with similar query_embedding (cosine similarity)
        cur.execute("""
            SELECT 
                query,
                selected_items,
                (1 - (query_embedding <=> %s::vector)) as similarity
            FROM user_feedback
            WHERE search_type = %s
              AND query_embedding IS NOT NULL
              AND (1 - (query_embedding <=> %s::vector)) >= %s
            ORDER BY similarity DESC
            LIMIT 20
        """, (query_vector, search_type, query_vector, similarity_threshold))
        
        similar_feedbacks = cur.fetchall()
        conn.close()
        
        if not similar_feedbacks:
            print(f"INFO: No similar feedback found (threshold={similarity_threshold})")
            return {}
        
        # 3. Calculate score for each item (weighted by similarity)
        item_scores = {}
        
        print(f"\n{'='*60}")
        print(f"INFO: FEEDBACK BOOST: Found {len(similar_feedbacks)} similar queries")
        print(f"{'='*60}\n")
        
        for fb in similar_feedbacks:
            sim = fb['similarity']
            
            try:
                # FIX: Check type before parsing
                selected_items = fb['selected_items']
                
                # If string JSON → parse
                if isinstance(selected_items, str):
                    selected = json.loads(selected_items)
                # If already list → use directly
                elif isinstance(selected_items, list):
                    selected = selected_items
                else:
                    print(f"WARNING: Unknown type for selected_items: {type(selected_items)}")
                    continue
                
                print(f"SUCCESS: Query: '{fb['query'][:50]}...' (sim={sim:.2f})")
                print(f"→ Selected: {selected[:3]}")
                
                for item_id in selected:
                    # Score = similarity * 1 (can be replaced with time decay)
                    item_scores[item_id] = item_scores.get(item_id, 0) + sim
                    
            except Exception as e:
                print(f"WARNING: Skip feedback: {e}")
                continue
        
        if item_scores:
            print(f"\nINFO: Kết quả:")
            for item_id, score in sorted(item_scores.items(), key=lambda x: x[1], reverse=True)[:5]:
                print(f"   {item_id}: {score:.2f} điểm")
        else:
            print("INFO: Không có item nào được boost")
            
        print(f"{'='*60}\n")
        
        return item_scores
        
    except Exception as e:
        print(f"ERROR: Failed to get feedback boost: {e}")
        import traceback
        traceback.print_exc()
        return {}

def save_user_feedback(session_id: str, query: str, selected_items: list, rejected_items: list, search_type: str):
    """
    Lưu phản hồi của user về kết quả tìm kiếm
    
    Args:
        session_id: ID session
        query: Câu hỏi gốc
        selected_items: List các item user chọn là ĐÚNG (headcode hoặc id_sap)
        rejected_items: List các item user bỏ qua/từ chối
        search_type: "product" hoặc "material"
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # TẠO EMBEDDING CHO QUERY NGAY KHI LƯU
        query_embedding = generate_embedding_qwen(query)
        
        if not query_embedding:
            print("WARNING: Không tạo được embedding, vẫn lưu feedback")
        
        sql = """
            INSERT INTO user_feedback 
            (session_id, query, selected_items, rejected_items, search_type, query_embedding)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        
        cur.execute(sql, (
            session_id,
            query,
            json.dumps(selected_items),
            json.dumps(rejected_items),
            search_type,
            query_embedding 
        ))
        
        feedback_id = cur.fetchone()[0]
        
        conn.commit()
        conn.close()
        
        print(f"Feedback saved: {len(selected_items)} selected, {len(rejected_items)} rejected")
        print(f"   → Feedback ID: {feedback_id}")
        print(f"   → Embedding: {'OK' if query_embedding else 'ERROR NULL'}")
        
        return True
        
    except Exception as e:
        print(f"ERROR: Failed to save feedback: {e}")
        import traceback
        traceback.print_exc()
        return False

# ================================================================================================
# API ENDPOINTS
# ================================================================================================

@router.post("/feedback", tags=["Feedback"])
def submit_feedback(feedback: FeedbackRequest):
    """
    📝 Endpoint nhận feedback từ user về kết quả tìm kiếm
    """
    try:
        success = save_user_feedback(
            feedback.session_id,
            feedback.query,
            feedback.selected_items,
            feedback.rejected_items,
            feedback.search_type
        )
        
        if success:
            return {
                "message": "SUCCESS: Cảm ơn phản hồi của bạn! Kết quả tìm kiếm sẽ được cải thiện.",
                "saved": True
            }
        else:
            return {
                "message": "WARNING: Không thể lưu phản hồi",
                "saved": False
            }
            
    except Exception as e:
        return {
            "message": f"ERROR: {str(e)}",
            "saved": False
        }


