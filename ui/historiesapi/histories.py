
import json
from datetime import datetime
from typing import Dict, List, Optional

import psycopg2
from config import settings
from fastapi import APIRouter, HTTPException, Request
from psycopg2.extras import RealDictCursor


DB_CONFIG = {
    "dbname": "db_vector",
    "user": "postgres",
    "password": "postgres",
    "host": "localhost",
    "port": "5432"
}

def get_db():
    return psycopg2.connect(**DB_CONFIG)

router = APIRouter()
# ========================================
# DATABASE HELPERS
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
            print(f"💾 UPDATED: id={message_id} | session={session_id[:8]}... | {search_type} | {result_count} results")
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
            print(f"💾 CREATED: id={message_id} | session={session_id[:8]}... | {search_type} | {result_count} results")
        
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


@router.get("/history/{session_id}")
def get_session_history(session_id: str):
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        sql = """
            SELECT 
                id,
                history::text as history_json,
                time_block,
                chat_date,
                session_id,
                email,
                created_at,
                updated_at
            FROM chat_histories
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT 20
        """
        cur.execute(sql, (session_id,))
        history = cur.fetchall()
        conn.close()

        histories_list = []
        for h in history:
            record = dict(h)

            # Convert datetime/date → string
            if record.get("chat_date"):
                record["chat_date"] = str(record["chat_date"])

            if record.get("created_at"):
                record["created_at"] = record["created_at"].isoformat()

            if record.get("updated_at"):
                record["updated_at"] = record["updated_at"].isoformat()

            # Parse history từ JSON string
            if record.get("history_json"):
                try:
                    record["history"] = json.loads(record["history_json"])
                except:
                    record["history"] = []
                del record["history_json"]
            else:
                record["history"] = []

            histories_list.append(record)

        return {
            "session_id": session_id,
            "total_queries": len(histories_list),
            "histories": histories_list
        }

    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"❌ Error in get_session_history: {error_detail}")
        return {"error": str(e), "detail": error_detail}

    
@router.get("/chat_histories/{email}")
def get_all_sessions_by_email(email: str):
    """
    Lấy danh sách tất cả sessions của một user, grouped by session_id
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        sql = """
            SELECT 
                session_id,
                MIN(chat_date) as first_chat_date,
                MAX(chat_date) as last_chat_date,
                MAX(updated_at) as last_updated,
                COUNT(DISTINCT chat_date) as total_days,
                SUM(
                    CASE 
                        WHEN jsonb_typeof(history) = 'array' 
                        THEN jsonb_array_length(history)
                        ELSE 0
                    END
                ) as total_messages
            FROM chat_histories
            WHERE email = %s
            GROUP BY session_id
            ORDER BY MAX(updated_at) DESC
        """
        
        cur.execute(sql, (email,))
        sessions = cur.fetchall()
        conn.close()
        
        # Format response
        sessions_list = []
        for s in sessions:
            session_dict = dict(s)
            # Convert date/datetime to string
            if session_dict.get("first_chat_date"):
                session_dict["first_chat_date"] = str(session_dict["first_chat_date"])
            if session_dict.get("last_chat_date"):
                session_dict["last_chat_date"] = str(session_dict["last_chat_date"])
            if session_dict.get("last_updated"):
                session_dict["last_updated"] = session_dict["last_updated"].isoformat()
            sessions_list.append(session_dict)
        
        return {
            "email": email,
            "total_sessions": len(sessions_list),
            "sessions": sessions_list
        }
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Error retrieving sessions: {error_detail}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat_histories/{email}/{session_id}")
def get_chat_history_by_session(email: str, session_id: str):
    """
    Lấy toàn bộ lịch sử chat của user theo session
    Trả về tất cả chat từ nhiều ngày, sắp xếp theo thời gian
    """
    try:
        result = get_session_chat_history(email, session_id)
        
        if result is None:
            raise HTTPException(status_code=500, detail="Error retrieving chat history")
        
        if result["total_chats"] == 0:
            return {
                "message": "No chat history found",
                "email": email,
                "session_id": session_id,
                "chats": []
            }
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error in endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


