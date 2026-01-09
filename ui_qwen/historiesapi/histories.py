
import json
from typing import Dict

import psycopg2
from config import settings
from fastapi import APIRouter, HTTPException, Request
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
import json

def get_db():
    return psycopg2.connect(**settings.DB_CONFIG)

router = APIRouter()
# ================================================================================================
# FUNCTION DEFINITIONS
# ================================================================================================

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
            print(f" INFO: UPDATED id={message_id} | session={session_id[:8]}... | {search_type} | {result_count} results")
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
def save_chat_to_histories(email: str, 
                        session_id: str, 
                        question: str, 
                        answer: str,
                        messages: str = None,
                        session_name:str="New Session"):
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
            "messages": messages or []
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
                (email, session_name, session_id, chat_date, time_block, history)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """
            history_json = json.dumps([new_chat_entry])
            cur.execute(insert_sql, (email, session_name, session_id, chat_date, time_block, history_json))
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
                session_name,
                isDeleted,
                chat_date,
                time_block,
                history,
                created_at,
                updated_at
            FROM chat_histories
            WHERE email = %s AND session_id = %s AND isDeleted = false
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
            "session_name": record['session_name'],
            "total_records": len(records),
            "total_chats": len(all_chats),
            "chats": all_chats
        }
        
    except Exception as e:
        print(f"Error retrieving chat history: {e}")
        return None

# ================================================================================================
# API ENDPOINTS
# ================================================================================================

# ============ CHAT HISTORY APIs ============

@router.get("/chat_histories/session_id/{session_id}", tags=["Chat History"])
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
                session_name,
                email,
                created_at,
                updated_at
            FROM chat_histories
            WHERE session_id = %s AND isDeleted = false
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
            "session_name": record['session_name'],
            "total_queries": len(histories_list),
            "histories": histories_list
        }
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Error in get_session_history: {error_detail}")
        return {"Error": str(e), "detail": error_detail}

@router.get("/chat_histories/email/{email}", tags=["Chat History"])
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
                session_name,
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
            WHERE email = %s AND isDeleted = false
            GROUP BY session_id,session_name
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

@router.get("/chat_histories/{email}/{session_id}", tags=["Chat History"])
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
                "session_name":result.get("session_name",""),
                "chats": []
            }
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============ MESSAGES APIs ============

@router.get("/chat_histories/session_id/{session_id}/list", tags=["Chat History"])
def get_sessionId_messages_list(session_id: str):
    """
    Phiên bản nâng cao: Xử lý timestamp chính xác hơn
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        sql = """
            SELECT 
                chat_date,
                time_block,
                history::text as history_json,
                created_at,
                updated_at
            FROM chat_histories
            WHERE session_id = %s AND isDeleted = false
            ORDER BY chat_date ASC, time_block ASC, created_at ASC
        """
        cur.execute(sql, (session_id,))
        records = cur.fetchall()
        conn.close()

        all_messages = []
        
        for record in records:
            chat_date = record['chat_date']
            time_block = record['time_block']
            history_json = record['history_json']
            record_created_at = record['created_at']
            
            try:
                history_list = json.loads(history_json)
            except:
                history_list = []
            
            if isinstance(history_list, list):
                for idx, qa in enumerate(history_list):
                    # Tính toán timestamp dựa trên created_at của record và thứ tự trong mảng
                    # Giả sử mỗi Q&A cách nhau 1 giây
                    message_timestamp = record_created_at
                    if idx > 0:
                        message_timestamp = record_created_at + timedelta(seconds=idx)
                    
                    # Xử lý question và answer (giống như phiên bản trước)
                    question = ""
                    answer = ""
                    
                    if isinstance(qa, dict):
                        # Xác định cấu trúc dữ liệu
                        if "question" in qa and "answer" in qa:
                            question = qa.get("question", "")
                            answer = qa.get("answer", "")
                            # Kiểm tra xem có timestamp riêng không
                            if "timestamp" in qa:
                                try:
                                    message_timestamp = datetime.fromisoformat(
                                        qa["timestamp"].replace('Z', '+00:00')
                                    )
                                except:
                                    pass
                        elif "q" in qa and "a" in qa:
                            question = qa.get("q", "")
                            answer = qa.get("a", "")
                        else:
                            # Xử lý các cấu trúc khác
                            question = qa.get("content", qa.get("message", qa.get("query", "")))
                            answer = qa.get("response", qa.get("reply", ""))
                    
                    # Chuyển answer thành string
                    if isinstance(answer, dict) or isinstance(answer, list):
                        answer = json.dumps(answer, ensure_ascii=False)
                    
                    all_messages.append({
                        "q": str(question) if question else "",
                        "a": str(answer) if answer else "",
                        "timestamp": message_timestamp.isoformat(),
                        "messages": qa.get("messages", []) if isinstance(qa, dict) else []
                    })
        
        # Sắp xếp theo timestamp
        all_messages.sort(key=lambda x: x['timestamp'])
        
        return all_messages
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Error in get_sessionId_messages_list: {error_detail}")
        return {"Error": str(e), "detail": error_detail}

@router.get("chat_histories/session_id/{session_id}/messages", tags=["Chat History"])
def get_sessionId_messages(session_id: str):
    """
    Phiên bản nâng cao với logic xác định welcome message thông minh hơn
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        sql = """
            SELECT 
                chat_date,
                time_block,
                history::text as history_json,
                created_at
            FROM chat_histories
            WHERE session_id = %s AND isDeleted = false
            ORDER BY chat_date ASC, time_block ASC, created_at ASC
        """
        cur.execute(sql, (session_id,))
        records = cur.fetchall()
        conn.close()

        all_messages = []
        first_message_processed = False
        
        for record in records:
            chat_date = record['chat_date']
            time_block = record['time_block']
            history_json = record['history_json']
            record_created_at = record['created_at']
            
            try:
                history_list = json.loads(history_json)
            except:
                history_list = []
            
            if isinstance(history_list, list):
                for idx, qa in enumerate(history_list):
                    # Tính toán timestamp
                    base_timestamp = record_created_at
                    if idx > 0:
                        base_timestamp = record_created_at + timedelta(seconds=idx)
                    
                    # Xác định loại message và nội dung
                    message_type = None
                    question = ""
                    answer = ""
                    
                    if isinstance(qa, dict):
                        # Lấy thông tin từ qa
                        if "question" in qa and "answer" in qa:
                            question = qa.get("question", "")
                            answer = qa.get("answer", "")
                            message_type = qa.get("type")
                        elif "q" in qa and "a" in qa:
                            question = qa.get("q", "")
                            answer = qa.get("a", "")
                            message_type = qa.get("type")
                        else:
                            question = qa.get("content", qa.get("message", qa.get("query", "")))
                            answer = qa.get("response", qa.get("reply", ""))
                            message_type = qa.get("type")
                    
                    # Xác định timestamp
                    if isinstance(qa, dict) and "timestamp" in qa:
                        try:
                            q_timestamp = datetime.fromisoformat(
                                qa["timestamp"].replace('Z', '+00:00')
                            )
                            question_timestamp = int(q_timestamp.timestamp() * 1000)
                            answer_timestamp = question_timestamp + 1000
                        except:
                            question_timestamp = int(base_timestamp.timestamp() * 1000)
                            answer_timestamp = question_timestamp + 1000
                    else:
                        question_timestamp = int(base_timestamp.timestamp() * 1000)
                        answer_timestamp = question_timestamp + 1000
                    
                    
                    
                    # Thêm message user (câu hỏi)
                    if question:
                        user_message = {
                            "role": "user",
                            "content": str(question).strip(),
                            "timestamp": question_timestamp,
                            "view_history": True
                        }
                        all_messages.append(user_message)
                    
                    # Thêm message bot (câu trả lời)
                    if answer:
                                                
                        # Lấy danh sách messages từ qa
                        messages_list = qa.get("messages", []) if isinstance(qa, dict) else []
                        
                        # Phân loại thành products và materials dựa trên dataTemplate
                        products = []
                        materials = []
                        
                        for item in messages_list:
                            if isinstance(item, dict):
                                # Xác định loại dựa trên các trường đặc trưng
                                is_product = False
                                is_material = False
                                
                                # Các trường đặc trưng của product (theo dataTemplate)
                                product_fields = ["category", "project", "product_name", "sub_category", 
                                                "project_id", "final_rank", "original_rank", "total_cost"]
                                
                                # Các trường đặc trưng của material (theo dataTemplate)
                                material_fields = ["material_group", "material_name", "material_subgroup", 
                                                "unit", "price", "id_sap", "distance"]
                                
                                # Kiểm tra xem item có trường nào của product không
                                for field in product_fields:
                                    if field in item:
                                        is_product = True
                                        break
                                
                                # Kiểm tra xem item có trường nào của material không
                                for field in material_fields:
                                    if field in item:
                                        is_material = True
                                        break
                                
                                # Phân loại
                                if is_product and not is_material:
                                    products.append(item)
                                elif is_material and not is_product:
                                    materials.append(item)
                                elif is_product and is_material:
                                    # Nếu có cả hai, ưu tiên phân loại dựa trên trường quan trọng nhất
                                    if "category" in item or "product_name" in item:
                                        products.append(item)
                                    elif "material_group" in item or "material_name" in item:
                                        materials.append(item)
                                    else:
                                        products.append(item)  # Mặc định
                        
                        bot_message = {
                            "role": "bot",
                            "content": str(answer).strip(),
                            "timestamp": answer_timestamp,
                            "view_history": True,
                            "data":{
                                "products": products,
                                "materials": materials
                            }
                        }
                        
                        # Xác định có phải là welcome message không
                        # Logic 1: Nếu được chỉ định type trong dữ liệu
                        if message_type:
                            bot_message["type"] = message_type
                        # Logic 2: Nếu là message bot đầu tiên và có chứa từ khóa chào hỏi
                        elif not first_message_processed:
                            # Kiểm tra nếu nội dung có chứa từ khóa chào hỏi
                            welcome_keywords = ["xin chào", "hello", "hi", "chào bạn", "welcom"]
                            content_lower = str(answer).lower()
                            if any(keyword in content_lower for keyword in welcome_keywords):
                                bot_message["type"] = "welcome"
                            
                            first_message_processed = True

                        
                        all_messages.append(bot_message)
        
        # Sắp xếp theo timestamp tăng dần
        all_messages.sort(key=lambda x: x['timestamp'])
        
        return all_messages
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Error in get_sessionId_messages: {error_detail}")
        return {"Error": str(e), "detail": error_detail}

# ============ SESSION MANAGEMENT APIs ============

@router.put("/chat_histories/session/{session_id}/rename", tags=["Chat History"])
def rename_session(session_id: str, request: Request):
    """
    API để thay đổi session_name của một session
    Body: {"session_name": "New Session Name"}
    """
    try:
        # Lấy dữ liệu từ request body
        import asyncio
        body = asyncio.run(request.json())
        new_session_name = body.get("session_name")
        
        if not new_session_name:
            raise HTTPException(status_code=400, detail="session_name is required")
        
        conn = get_db()
        cur = conn.cursor()
        
        # Kiểm tra session có tồn tại không
        check_sql = """
            SELECT COUNT(*) FROM chat_histories 
            WHERE session_id = %s AND isDeleted = false
        """
        cur.execute(check_sql, (session_id,))
        count = cur.fetchone()[0]
        
        if count == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Cập nhật session_name cho tất cả records của session này
        update_sql = """
            UPDATE chat_histories 
            SET session_name = %s, updated_at = NOW()
            WHERE session_id = %s AND isDeleted = false
        """
        cur.execute(update_sql, (new_session_name, session_id))
        updated_count = cur.rowcount
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "message": f"Session name updated successfully",
            "session_id": session_id,
            "new_session_name": new_session_name,
            "updated_records": updated_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Error renaming session: {error_detail}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/chat_histories/session/{session_id}", tags=["Chat History"])
def delete_session(session_id: str):
    """
    API để xóa session (soft delete)
    Đánh dấu isDeleted = true cho tất cả records của session
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Kiểm tra session có tồn tại không
        check_sql = """
            SELECT COUNT(*) FROM chat_histories 
            WHERE session_id = %s AND isDeleted = false
        """
        cur.execute(check_sql, (session_id,))
        count = cur.fetchone()[0]
        
        if count == 0:
            conn.close()
            raise HTTPException(status_code=404, detail="Session not found")
        
        # Soft delete: Đánh dấu isDeleted = true
        delete_sql = """
            UPDATE chat_histories 
            SET isDeleted = true, updated_at = NOW()
            WHERE session_id = %s AND isDeleted = false
        """
        cur.execute(delete_sql, (session_id,))
        deleted_count = cur.rowcount
        
        conn.commit()
        conn.close()
        
        return {
            "success": True,
            "message": f"Session deleted successfully",
            "session_id": session_id,
            "deleted_records": deleted_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Error deleting session: {error_detail}")
        raise HTTPException(status_code=500, detail=str(e))
