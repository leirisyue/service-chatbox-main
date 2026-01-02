
import json
from datetime import datetime
from typing import Dict
from fastapi import APIRouter
from psycopg2.extras import RealDictCursor
from typing import Dict
import psycopg2
from config import settings

def get_db():
    return psycopg2.connect(**settings.DB_CONFIG)

router = APIRouter()
# ========================================
# FUNCTION DEFINITIONS
# ========================================

# FUNC cũ để lưu lịch sử chat
def save_chat_to_history(session_id: str, user_message: str, bot_response: str, 
                    intent: str, params: Dict, result_count: int,
                    search_type: str = "text",
                    expanded_query: str = None,
                    extracted_keywords: list = None,
                    email: str = None):
    """Lưu lịch sử chat vào bảng chat_histories - V4.7 FIX with UPSERT"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Lấy thời gian hiện tại
        now = datetime.now()
        chat_date = now.date()
        # time_block: 1 = 0-12h, 2 = 12-24h
        time_block = 1 if now.hour < 12 else 2
        
        # Tạo history JSON entry
        history_entry = {
            "user_message": user_message,
            "bot_response": bot_response,
            "intent": intent,
            "params": params,
            "result_count": result_count,
            "search_type": search_type,
            "expanded_query": expanded_query,
            "extracted_keywords": extracted_keywords,
            "timestamp": now.isoformat()
        }
        
        # Check if record exists for this email, session, date, and time_block
        check_sql = """
            SELECT id, history 
            FROM chat_histories 
            WHERE email = %s 
                AND session_id = %s 
                AND chat_date = %s 
                AND time_block = %s
                AND session_id = %s
        """
        cur.execute(check_sql, (email, session_id, chat_date, time_block))
        existing = cur.fetchone()
        
        if existing:
            # UPDATE: Append to existing history
            record_id = existing[0]
            existing_history = existing[1]
            
            # If existing_history is a dict (old format), convert to list
            if isinstance(existing_history, dict):
                existing_history = [existing_history]
            
            # Append new entry
            existing_history.append(history_entry)
            
            update_sql = """
                UPDATE chat_histories 
                SET history = %s, updated_at = %s
                WHERE id = %s
                RETURNING id
            """
            cur.execute(update_sql, (json.dumps(existing_history), now, record_id))
            message_id = cur.fetchone()[0]
            print(f"INFO: UPDATED id={message_id} | session={session_id[:8]}... | {search_type} | {result_count} results")
        else:
            # INSERT: Create new record
            insert_sql = """
                INSERT INTO chat_histories 
                (email, session_id, chat_date, time_block, history, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """
            
            history_json = json.dumps([history_entry])
            cur.execute(insert_sql, (
                email,
                session_id,
                chat_date,
                time_block,
                history_json,
                now,
                now
            ))
            
            message_id = cur.fetchone()[0]
            print(f"INFO: CREATED id={message_id} | session={session_id[:8]}... | {search_type} | {result_count} results")
        
        conn.commit()
        conn.close()
        
        return message_id
        
    except Exception as e:
        print(f"Lỗi save chat history: {e}")
        import traceback
        traceback.print_exc()
        return None

def get_time_block(hour: int) -> int:
    """Determine time block based on hour
    Returns 1 for 0-12h, 2 for 12-24h
    """
    return 1 if hour < 12 else 2

# FUNC mới để lưu lịch sử chat theo block thời gian
def save_chat_to_histories(email: str, session_id: str, question: str, answer: str):
    """
    Save or update chat history based on date and time block
    - If same day and time block: UPDATE existing record (append to JSONB)
    - If different time block: CREATE new record
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Get current datetime
        now = datetime.now()
        chat_date = now.date()
        current_hour = now.hour
        time_block = get_time_block(current_hour)
        timestamp = now.isoformat()
        
        # Create new chat entry
        new_chat_entry = {
            "q": question,
            "a": answer,
            "timestamp": timestamp,
        }
        
        # Check if record exists for this email, session, date, and time_block
        check_sql = """
            SELECT id, history 
            FROM chat_histories 
            WHERE email = %s 
                AND session_id = %s 
                AND chat_date = %s 
                AND time_block = %s
        """
        cur.execute(check_sql, (email, session_id, chat_date, time_block))
        existing = cur.fetchone()
        
        if existing:
            # UPDATE: Append to existing history
            record_id = existing[0]
            existing_history = existing[1]
            
            # Append new entry
            existing_history.append(new_chat_entry)
            
            update_sql = """
                UPDATE chat_histories 
                SET history = %s
                WHERE id = %s
            """
            cur.execute(update_sql, (json.dumps(existing_history), record_id))
            print(f"UPDATED chat history: {email} | {session_id[:8]}... | {chat_date} | Block {time_block}")

        else:
            # INSERT: Create new record
            insert_sql = """
                INSERT INTO chat_histories 
                (email, session_id, chat_date, time_block, history)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """
            
            history_json = json.dumps([new_chat_entry])
            cur.execute(insert_sql, (email, session_id, chat_date, time_block, history_json))
            record_id = cur.fetchone()[0]
            print(f"CREATED chat_histories: {email} | {session_id[:8]}... | {chat_date} | Block {time_block}")
        
        conn.commit()
        conn.close()
        return True
        
    except Exception as e:
        print(f"Error saving chat history: {e}")
        return False

def get_session_chat_history(email: str, session_id: str):
    """
    Retrieve all chat history for a user session across all days
    Returns sorted by date and time_block
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        sql = """
            SELECT 
                id,
                email,
                session_id,
                chat_date,
                time_block,
                history,
                created_at,
                updated_at
            FROM chat_histories
            WHERE email = %s AND session_id = %s
            ORDER BY chat_date ASC, time_block ASC
        """
        cur.execute(sql, (email, session_id))
        records = cur.fetchall()
        conn.close()
        
        # Flatten all history entries
        all_chats = []
        for record in records:
            history_entries = record['history']
            for entry in history_entries:
                all_chats.append({
                    "question": entry['q'],
                    "answer": entry['a'],
                    "timestamp": entry['timestamp'],
                    "date": str(record['chat_date']),
                    "time_block": record['time_block']
                })
        return {
            "email": email,
            "session_id": session_id,
            "total_records": len(records),
            "total_chats": len(all_chats),
            "chats": all_chats
        }
        
    except Exception as e:
        print(f"Error retrieving chat history: {e}")
        return None

# ========================================
# API ENDPOINTS
# ========================================

@router.get("/debug/products")
def debug_products():
    """Debug info vá»  products"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT COUNT(*) as total FROM products_qwen")
    total = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as with_emb FROM products_qwen WHERE description_embedding IS NOT NULL")
    with_emb = cur.fetchone()['with_emb']
    
    cur.execute("SELECT category, COUNT(*) as count FROM products_qwen GROUP BY category ORDER BY count DESC")
    by_category = cur.fetchall()
    
    conn.close()
    
    return {
        "total_products": total,
        "with_embeddings": with_emb,
        "coverage_percent": round(with_emb / total * 100, 1) if total > 0 else 0,
        "by_category": [dict(c) for c in by_category]
    }

@router.get("/debug/materials")
def debug_materials():
    """Debug info vá»  materials"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT COUNT(*) as total FROM materials_qwen")
    total = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as with_emb FROM materials_qwen WHERE description_embedding IS NOT NULL")
    with_emb = cur.fetchone()['with_emb']
    
    cur.execute("SELECT material_group, COUNT(*) as count FROM materials_qwen GROUP BY material_group ORDER BY count DESC")
    by_group = cur.fetchall()
    
    conn.close()
    
    return {
        "total_materials": total,
        "with_embeddings": with_emb,
        "coverage_percent": round(with_emb / total * 100, 1) if total > 0 else 0,
        "by_group": [dict(g) for g in by_group]
    }

@router.get("/debug/chat-history")
def debug_chat_history():
    """Xem lá»‹ch sá»­ chat gáº§n Ä‘Ã¢y"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT 
            session_id,
            user_message,
            intent,
            result_count,
            created_at
        FROM chat_history
        ORDER BY created_at DESC
        LIMIT 20
    """)
    
    history = cur.fetchall()
    conn.close()
    
    return {
        "recent_chats": [dict(h) for h in history]
    }

