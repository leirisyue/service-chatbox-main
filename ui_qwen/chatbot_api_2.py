from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
import psycopg2
from psycopg2.extras import RealDictCursor
import google.generativeai as genai
import uuid
import time
import json
from datetime import datetime
from PIL import Image
import os
import re
import pandas as pd
import io
from config import settings
from .textfunc import (format_search_results)

# ========================================
# CONFIGURATION
# ========================================

DB_CONFIG = {
    "dbname": "PRODUCT",
    "user": "postgres",
    "password": "123456",
    "host": "localhost",
    "port": "5432"
}

GEMINI_API_KEY = "AIzaSyCcORIhGV4GbUP9wgSb6FyhzNSw9BUokZ8"
genai.configure(api_key=GEMINI_API_KEY)

app = FastAPI(title="AA Corporation Chatbot API", version="4.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========================================
# DATABASE HELPERS
# ========================================

def get_db():
    return psycopg2.connect(**DB_CONFIG)

# ========================================
# PYDANTIC MODELS
# ========================================

class ChatMessage(BaseModel):
    session_id: str
    message: str
    context: Optional[Dict] = {}

# ========================================
# GEMINI AI HELPERS
# ========================================

def call_gemini_with_retry(model, prompt, max_retries=3):
    """Gọi Gemini với retry logic"""
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            if response.text:
                return response.text
        except Exception as e:
            if "429" in str(e) or "quota" in str(e).lower():
                wait_time = 5 * (2 ** attempt)
                print(f"⏳ Quota exceeded. Đợi {wait_time}s...")
                time.sleep(wait_time)
                continue
            print(f"❌ Lỗi Gemini: {e}")
            return None
    return None

def generate_embedding(text: str):
    """Tạo vector embedding cho text"""
    try:
        result = genai.embed_content(
            model="models/text-embedding-004",
            content=text,
            task_type="retrieval_query"
        )
        return result['embedding']
    except Exception as e:
        print(f"❌ Lỗi embedding: {e}")
        return None





# ========================================
# ========================================
# ✨ [MỚI] HYBRID SEARCH FUNCTIONS
# ========================================

def expand_search_query(user_query: str, params: Dict) -> str:
    """AI mở rộng query ngắn thành mô tả chi tiết"""
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    prompt = f"""
Người dùng tìm: "{user_query}"

Tạo mô tả tìm kiếm tối ưu (2-3 câu ngắn):
1. LOẠI SẢN PHẨM (bàn/ghế/tủ...)
2. VẬT LIỆU CỤ THỂ (gỗ teak/đá marble/da bò...)
3. VỊ TRÍ/CÔNG DỤNG (nhà bếp/phòng khách/dining/coffee...)

VD: "bàn gỗ teak" -> "Bàn làm từ gỗ teak tự nhiên. Dining table hoặc coffee table chất liệu teak wood cao cấp."

Output (chỉ mô tả):
"""
    
    try:
        response = call_gemini_with_retry(model, prompt, max_retries=2)
        if response:
            print(f"✨ Expanded: '{user_query}' -> '{response[:80]}...'")
            return response.strip()
    except:
        pass
    return user_query


def extract_product_keywords(query: str) -> list:
    """Trích xuất từ khóa quan trọng"""
    materials = ["gỗ teak", "gỗ sồi", "gỗ walnut", "đá marble", "đá granite", 
                 "da thật", "da bò", "vải linen", "kim loại", "teak", "oak", 
                 "walnut", "marble", "granite", "leather"]
    
    contexts = ["nhà bếp", "phòng khách", "phòng ngủ", "văn phòng",
                "kitchen", "living room", "dining", "coffee", "bar",
                "bàn ăn", "bàn trà", "bàn làm việc"]
    
    shapes = ["tròn", "vuông", "chữ nhật", "oval", "l-shape", 
              "round", "square", "rectangular"]
    
    types = ["bàn", "ghế", "tủ", "giường", "sofa", "kệ", "đèn",
             "table", "chair", "cabinet", "bed", "shelf", "lamp"]
    
    query_lower = query.lower()
    keywords = []
    
    for word_list in [materials, contexts, shapes, types]:
        for word in word_list:
            if word in query_lower:
                keywords.append(word)
    
    keywords = list(set(keywords))
    if keywords:
        print(f"🔑 Keywords: {keywords}")
    return keywords


def search_products_hybrid(params: Dict):
    """HYBRID: Vector + Keyword Boosting"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # 1. Chuẩn bị query
    if params.get("keywords_vector"):
        base = params["keywords_vector"]
    else:
        parts = [params.get("category", ""), params.get("sub_category", ""), 
                params.get("material_primary", "")]
        base = " ".join([p for p in parts if p]) or "nội thất"
    
    print(f"\n🔍 Query: {base}")
    
    # 2. AI Expansion
    expanded = expand_search_query(base, params)
    
    # 3. Extract keywords
    keywords = extract_product_keywords(expanded)
    
    # 4. Vector
    vector = generate_embedding(expanded)
    if not vector:
        conn.close()
        return {"products": [], "search_method": "failed"}
    
    # 5. SQL Hybrid
    try:
        if keywords:
            conditions = []
            params_list = []
            for kw in keywords:
                conditions.append("(product_name ILIKE %s OR category ILIKE %s OR "
                                "sub_category ILIKE %s OR material_primary ILIKE %s)")
                params_list.extend([f"%{kw}%"] * 4)
            
            boost = f"(CASE WHEN ({' OR '.join(conditions)}) THEN 1 ELSE 0 END)"
        else:
            boost = "0"
            params_list = []
        
        sql = f"""
            SELECT headcode, product_name, category, sub_category, 
                   material_primary, project, project_id,
                   (description_embedding <=> %s::vector) as raw_distance,
                   {boost} as keyword_match
            FROM products
            WHERE description_embedding IS NOT NULL
            ORDER BY (description_embedding <=> %s::vector) - ({boost} * 0.25) ASC
            LIMIT 10
        """
        
        all_params = [vector] + params_list + [vector] + params_list
        cur.execute(sql, all_params)
        results = cur.fetchall()
        
        if results:
            products = [{
                "headcode": r["headcode"],
                "product_name": r["product_name"],
                "category": r.get("category"),
                "sub_category": r.get("sub_category"),
                "material_primary": r.get("material_primary"),
                "project": r.get("project"),
                "project_id": r.get("project_id"),
                "similarity": round(1 - r["raw_distance"], 3),
                "keyword_matched": bool(r.get("keyword_match"))
            } for r in results]
            
            print(f"✅ Found {len(products)} products (Hybrid)")
            conn.close()
            return {
                "products": products,
                "search_method": "hybrid_vector_keyword",
                "expanded_query": expanded
            }
    except Exception as e:
        print(f"❌ Hybrid failed: {e}")
    
    conn.close()
    return {"products": [], "search_method": "hybrid_failed"}

# [NEW] AUTO CLASSIFICATION AI
# ========================================

def auto_classify_product(product_name: str, id_sap: str = "") -> Dict:
    """Tự động phân loại sản phẩm bằng AI"""
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    prompt = f"""
Bạn là chuyên gia phân loại sản phẩm nội thất cao cấp.

INPUT:
- Tên sản phẩm: "{product_name}"
- Mã SAP: "{id_sap}"

NHIỆM VỤ: Phân tích và phân loại sản phẩm theo 3 tiêu chí:

1. **category** (Danh mục chính):
   - Bàn (Table)
   - Ghế (Chair) 
   - Sofa
   - Tủ (Cabinet)
   - Giường (Bed)
   - Đèn (Lamp)
   - Kệ (Shelf)
   - Bàn làm việc (Desk)
   - Khác (Other)

2. **sub_category** (Danh mục phụ - cụ thể hơn):
   VD: "Bàn ăn", "Bàn coffee", "Ghế bar", "Ghế ăn", "Sofa góc", "Tủ quần áo", "Đèn bàn", "Đèn trần"...

3. **material_primary** (Vật liệu chính):
   - Gỗ (Wood)
   - Da (Leather)
   - Vải (Fabric)
   - Kim loại (Metal)
   - Đá (Stone)
   - Kính (Glass)
   - Nhựa (Plastic)
   - Mây tre (Rattan)
   - Hỗn hợp (Mixed)

OUTPUT JSON ONLY (no markdown, no backticks):
{{
  "category": "...",
  "sub_category": "...",
  "material_primary": "..."
}}
"""
    
    response_text = call_gemini_with_retry(model, prompt)
    
    if not response_text:
        return {
            "category": "Chưa phân loại",
            "sub_category": "Chưa phân loại", 
            "material_primary": "Chưa xác định"
        }
    
    try:
        clean = response_text.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        
        result = json.loads(clean)
        return result
    except:
        return {
            "category": "Chưa phân loại",
            "sub_category": "Chưa phân loại",
            "material_primary": "Chưa xác định"
        }

def auto_classify_material(material_name: str, id_sap: str = "") -> Dict:
    """Tự động phân loại vật liệu bằng AI"""
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    prompt = f"""
Phân loại nguyên vật liệu nội thất:

Tên: "{material_name}"
Mã: "{id_sap}"

Xác định:
1. **material_group**: Gỗ, Da, Vải, Đá, Kim loại, Kính, Nhựa, Sơn, Keo, Phụ kiện, Khác
2. **material_subgroup**: Nhóm con cụ thể (VD: "Gỗ tự nhiên", "Da thật", "Vải cao cấp"...)

OUTPUT JSON ONLY:
{{
    "material_group": "...",
  "material_subgroup": "..."
}}
"""
    
    response_text = call_gemini_with_retry(model, prompt)
    
    if not response_text:
        return {
            "material_group": "Chưa phân loại",
            "material_subgroup": "Chưa phân loại"
        }
    
    try:
        clean = response_text.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        
        result = json.loads(clean)
        return result
    except:
        return {
            "material_group": "Chưa phân loại",
            "material_subgroup": "Chưa phân loại"
        }

# ========================================
# [NEW] CHAT HISTORY
# ========================================

# ========================================
# FIX 1: DÒNG ~430-460
# Thay thế hàm save_chat_history
# ========================================

def save_chat_history(session_id: str, user_message: str, bot_response: str, 
                     intent: str, params: Dict, result_count: int,
                     search_type: str = "text",
                     expanded_query: str = None,
                     extracted_keywords: list = None):
    """Lưu lịch sử chat ĐẦY ĐỦ để học - V4.7 FIX"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # ✅ QUAN TRỌNG: Tạo embedding cho query ngay khi lưu
        query_embedding = None
        if user_message:
            query_embedding = generate_embedding(user_message)
        
        sql = """
            INSERT INTO chat_history 
            (session_id, user_message, bot_response, intent, params, result_count,
             search_type, expanded_query, extracted_keywords, query_embedding)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        
        cur.execute(sql, (
            session_id, user_message, bot_response, 
            intent, json.dumps(params), result_count,
            search_type,
            expanded_query,
            json.dumps(extracted_keywords) if extracted_keywords else None,
            query_embedding  # ✅ MỚI: Lưu embedding
        ))
        
        message_id = cur.fetchone()[0]  # ✅ Lấy ID message
        
        conn.commit()
        conn.close()
        print(f"💾 SAVED: msg_id={message_id} | {session_id[:8]}... | {search_type} | {result_count} results")
        
        return message_id  # ✅ Trả về ID để UI dùng
        
    except Exception as e:
        print(f"❌ Lỗi save chat history: {e}")
        return None
# ========================================
# HELPER - LẤY GIÁ MỚI NHẤT
# ========================================

def get_latest_material_price(material_subprice_json: str) -> float:
    """Lấy giá mới nhất từ JSON lịch sử giá"""
    if not material_subprice_json:
        print("⚠️ material_subprice_json is NULL/empty")
        return 0.0
    
    try:
        price_history = json.loads(material_subprice_json)
        if not price_history or not isinstance(price_history, list):
            print(f"⚠️ Invalid price_history: {price_history}")
            return 0.0
        
        sorted_prices = sorted(
            price_history, 
            key=lambda x: x.get('date', '1900-01-01'), 
            reverse=True
        )
        result = float(sorted_prices[0].get('price', 0))
        print(f"✅ Parsed price: {result} VNĐ")
        return result
    except:
        print(f"❌ Price parse error: {e}")
        return 0.0

# ========================================
# INTENT DETECTION
# ========================================

def get_intent_and_params(user_message: str, context: Dict) -> Dict:
    """AI Router với khả năng Reasoning & Soft Clarification"""
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    context_info = ""
    if context.get("current_products"):
        products = context["current_products"]
        context_info = f"\nCONTEXT (User vừa xem): {len(products)} sản phẩm. SP đầu tiên: {products[0]['headcode']} - {products[0]['product_name']}"
    elif context.get("current_materials"):
        materials = context["current_materials"]
        context_info = f"\nCONTEXT (User vừa xem): {len(materials)} vật liệu. VL đầu tiên: {materials[0]['material_name']}"
    
    prompt = f"""
    Bạn là AI Assistant thông minh của AA Corporation (Nội thất cao cấp).
    
    INPUT: "{user_message}"
    {context_info}

    NHIỆM VỤ: Phân tích Intent và Parameters.
    
    QUY TẮC SUY LUẬN (LOGIC):
    1. **Intent Detection**: Xác định user muốn:
       - **search_product**: Tìm kiếm sản phẩm (VD: "Tìm bàn", "Có bàn nào", "Cho tôi xem ghế")
       - **query_product_materials**: Xem vật liệu của SẢN PHẨM (VD: "Vật liệu của bàn B001", "Phân tích vật liệu SP này")
       - **calculate_product_cost**: Tính giá/báo giá SẢN PHẨM (VD: "Giá bàn B001", "Tính giá sản phẩm", "Báo giá")
       
       **MATERIAL FLOW:**
       - **search_material**: Tìm kiếm NGUYÊN VẬT LIỆU (VD: "Tìm gỗ sồi", "Có loại da nào", "Đá marble", "Vật liệu làm bàn")
       - **query_material_detail**: Xem chi tiết VẬT LIỆU + sản phẩm sử dụng (VD: "Chi tiết gỗ sồi", "Xem vật liệu này dùng ở đâu")
       - **list_material_groups**: Liệt kê nhóm vật liệu (VD: "Các loại gỗ", "Danh sách đá")

       ----------------------------------------------------------------
       **[NEW] CROSS-TABLE INTENTS (BỔ SUNG – KHÔNG THAY ĐỔI LOGIC CŨ):**
       - **search_product_by_material**: Tìm sản phẩm LÀM TỪ vật liệu cụ thể
         Ví dụ: "Tìm bàn làm từ đá marble", "Tủ gỗ teak", "Ghế da thật"
       
       - **search_material_for_product**: Tìm vật liệu ĐỂ LÀM sản phẩm cụ thể
         Ví dụ: "Vật liệu làm bàn tròn", "Nguyên liệu ghế sofa", "Đá làm bàn"

       **PHÂN BIỆT RÕ (ƯU TIÊN TUÂN THỦ):**
       - "Tìm bàn gỗ" → search_product
       - "Tìm bàn LÀM TỪ gỗ teak" → search_product_by_material
       - "Tìm gỗ" → search_material
       - "Tìm vật liệu ĐỂ LÀM bàn" → search_material_for_product
       ----------------------------------------------------------------
       
       - **greeting**: Chào hỏi (VD: "Xin chào", "Hello", "Hi")
       - **unknown**: Không rõ ý định
    
    2. **Entity Type Detection**: 
       - Phân biệt: User đang nói về SẢN PHẨM hay VẬT LIỆU?
       - Keyword: "sản phẩm", "bàn", "ghế", "sofa" → PRODUCT
       - Keyword: "vật liệu", "nguyên liệu", "gỗ", "da", "đá", "vải" → MATERIAL
       - "giá" + context sản phẩm → calculate_product_cost
       - "giá" + context vật liệu → query_material_detail
    
    3. **Broad Query Detection**: 
       - Nếu User chỉ nói danh mục lớn (VD: "Tìm bàn", "Ghế", "Đèn", "Tìm gỗ") mà KHÔNG có tính chất cụ thể:
         -> Set `is_broad_query`: true
         -> Tạo `follow_up_question`: Một câu hỏi ngắn gợi ý user thu hẹp phạm vi
       - Nếu User đã cụ thể (VD: "Bàn ăn tròn", "Ghế gỗ sồi", "Đá marble trắng"):
         -> Set `is_broad_query`: false
         -> `follow_up_question`: null
    
    4. **Parameter Extraction**:
       **For PRODUCTS:**
       - `category`: Danh mục sản phẩm
       - `sub_category`: Danh mục phụ
       - `material_primary`: Vật liệu chính
       - `keywords_vector`: Mô tả đầy đủ để search vector
       - `headcode`: Mã sản phẩm (nếu có trong INPUT hoặc Context)
       
       **For MATERIALS:**
       - `material_name`: Tên vật liệu (VD: "gỗ sồi", "da thật")
       - `material_group`: Nhóm vật liệu (VD: "Gỗ", "Da", "Đá", "Vải")
       - `material_subgroup`: Nhóm con
       - `keywords_vector`: Mô tả đặc tính để search (VD: "gỗ làm bàn ăn cao cấp màu nâu")
       - `id_sap`: Mã vật liệu SAP (nếu có)
       - `usage_context`: Ngữ cảnh sử dụng (VD: "làm bàn", "bọc ghế")
    
    5. **Context Awareness**:
       - Nếu User dùng từ đại từ ("cái này", "nó", "sản phẩm đó", "vật liệu này"), hãy lấy từ Context
       - Nếu User hỏi về giá/vật liệu mà không nói rõ, ưu tiên lấy item đầu tiên trong Context

    OUTPUT FORMAT (JSON ONLY - no markdown backticks):
    {{
      "intent": "search_product|search_product_by_material|search_material_for_product|query_product_materials|calculate_product_cost|search_material|query_material_detail|list_material_groups|greeting|unknown",
      "entity_type": "product|material|unknown",
      "params": {{
        "category": "String hoặc null",
        "sub_category": "String hoặc null",
        "material_primary": "String hoặc null",
        "material_name": "String hoặc null",
        "material_group": "String hoặc null",
        "material_subgroup": "String hoặc null",
        "keywords_vector": "Từ khóa mô tả đầy đủ",
        "headcode": "String hoặc null",
        "id_sap": "String hoặc null",
        "usage_context": "String hoặc null"
      }},
      "is_broad_query": boolean,
      "follow_up_question": "String hoặc null",
      "suggested_actions": ["String 1", "String 2"]
    }}
    """
    
    response_text = call_gemini_with_retry(model, prompt)
    if not response_text:
        return {"intent": "error"}
    
    try:
        clean_text = response_text.strip()
        
        if "```json" in clean_text:
            clean_text = clean_text.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_text:
            clean_text = clean_text.split("```")[1].split("```")[0].strip()
        
        result = json.loads(clean_text)
        
        if result["intent"] in ["calculate_product_cost", "query_product_materials"]:
            if not result["params"].get("headcode"):
                match = re.search(r'\b([A-Z0-9]+-?[A-Z0-9]+)\b', user_message.upper())
                if match:
                    result["params"]["headcode"] = match.group(1)
        
        return result
        
    except json.JSONDecodeError as e:
        print(f"JSON Parse Error: {e} - Raw: {response_text}")
        return {"intent": "error", "raw": response_text}
    except Exception as e:
        print(f"Parse Error: {e}")
        return {"intent": "error", "raw": response_text}

# ========================================
# [NEW] CROSS-TABLE SEARCH FUNCTIONS
# ========================================

def search_products_by_material(material_query: str, params: Dict):
    """
    🔍 TÌM SẢN PHẨM ĐƯỢC LÀM TỪ VẬT LIỆU CỤ THỂ
    Ví dụ: "Tìm bàn làm từ đá marble", "Tủ gỗ teak"
    
    Logic: 
    1. Tìm materials phù hợp với query (vector search)
    2. JOIN product_materials để lấy products sử dụng material đó
    3. Rank products theo độ phù hợp
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    print(f"🔗 Cross-table search: Products made from '{material_query}'")
    
    # Bước 1: Tìm vật liệu phù hợp
    material_vector = generate_embedding(material_query)
    
    if not material_vector:
        conn.close()
        return {"products": [], "search_method": "failed"}
    
    try:
        # Tìm top materials phù hợp
        cur.execute("""
            SELECT 
                id_sap, 
                material_name,
                material_group,
                (description_embedding <=> %s::vector) as distance
            FROM materials
            WHERE description_embedding IS NOT NULL
            ORDER BY distance ASC
            LIMIT 5
        """, [material_vector])
        
        matched_materials = cur.fetchall()
        
        if not matched_materials:
            conn.close()
            return {"products": [], "search_method": "no_materials_found"}
        
        material_ids = [m['id_sap'] for m in matched_materials]
        material_names = [m['material_name'] for m in matched_materials]
        
        print(f"✅ Found {len(material_ids)} matching materials: {material_names[:3]}")
        
        # Bước 2: Tìm products sử dụng materials này
        # Kết hợp filter category nếu có
        category_filter = ""
        filter_params = []
        
        if params.get("category"):
            category_filter = "AND p.category ILIKE %s"
            filter_params.append(f"%{params['category']}%")
        
        sql = f"""
            SELECT 
                p.headcode,
                p.product_name,
                p.category,
                p.sub_category,
                p.material_primary,
                p.project,
                p.project_id,
                m.material_name,
                m.id_sap as material_id,
                pm.quantity,
                COUNT(*) OVER (PARTITION BY p.headcode) as material_match_count
            FROM products p
            INNER JOIN product_materials pm ON p.headcode = pm.product_headcode
            INNER JOIN materials m ON pm.material_id_sap = m.id_sap
            WHERE m.id_sap = ANY(%s)
            {category_filter}
            ORDER BY material_match_count DESC, p.product_name ASC
            LIMIT 20
        """
        
        cur.execute(sql, [material_ids] + filter_params)
        results = cur.fetchall()
        
        conn.close()
        
        if not results:
            return {
                "products": [],
                "search_method": "cross_table_no_products",
                "matched_materials": material_names
            }
        
        # Group products (vì 1 product có thể dùng nhiều materials)
        products_dict = {}
        for row in results:
            headcode = row['headcode']
            if headcode not in products_dict:
                products_dict[headcode] = {
                    "headcode": headcode,
                    "product_name": row['product_name'],
                    "category": row['category'],
                    "sub_category": row['sub_category'],
                    "material_primary": row['material_primary'],
                    "project": row['project'],
                    "project_id": row['project_id'],
                    "matched_materials": [],
                    "relevance_score": 0
                }
            
            products_dict[headcode]["matched_materials"].append({
                "name": row['material_name'],
                "id": row['material_id'],
                "quantity": row['quantity']
            })
            products_dict[headcode]["relevance_score"] += 1
        
        products_list = sorted(
            products_dict.values(),
            key=lambda x: x['relevance_score'],
            reverse=True
        )
        
        print(f"✅ Found {len(products_list)} products using these materials")
        
        return {
            "products": products_list[:10],
            "search_method": "cross_table_material_to_product",
            "matched_materials": material_names,
            "explanation": f"Tìm thấy sản phẩm sử dụng: {', '.join(material_names[:3])}"
        }
        
    except Exception as e:
        print(f"❌ Cross-table search failed: {e}")
        conn.close()
        return {"products": [], "search_method": "cross_table_error"}



def search_materials_for_product(product_query: str, params: Dict):
    """
    🔍 TÌM VẬT LIỆU ĐỂ LÀM SẢN PHẨM CỤ THỂ
    Ví dụ: "Vật liệu làm bàn tròn", "Nguyên liệu ghế sofa"
    
    Logic:
    1. Tìm products phù hợp với query
    2. JOIN product_materials để lấy materials được dùng
    3. Aggregate + rank theo tần suất
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    print(f"🔗 Cross-table search: Materials for '{product_query}'")
    
    # Bước 1: Tìm products phù hợp
    product_vector = generate_embedding(product_query)
    
    if not product_vector:
        conn.close()
        return {"materials": [], "search_method": "failed"}
    
    try:
        cur.execute("""
            SELECT 
                headcode,
                product_name,
                category,
                (description_embedding <=> %s::vector) as distance
            FROM products
            WHERE description_embedding IS NOT NULL
            ORDER BY distance ASC
            LIMIT 10
        """, [product_vector])
        
        matched_products = cur.fetchall()
        
        if not matched_products:
            conn.close()
            return {"materials": [], "search_method": "no_products_found"}
        
        product_headcodes = [p['headcode'] for p in matched_products]
        product_names = [p['product_name'] for p in matched_products]
        
        print(f"✅ Found {len(product_headcodes)} matching products: {product_names[:3]}")
        
        # Bước 2: Lấy materials được dùng trong products này
        material_filter = ""
        filter_params = []
        
        if params.get("material_group"):
            material_filter = "AND m.material_group ILIKE %s"
            filter_params.append(f"%{params['material_group']}%")
        
        sql = f"""
            SELECT 
                m.id_sap,
                m.material_name,
                m.material_group,
                m.material_subgroup,
                m.material_subprice,
                m.unit,
                m.image_url,
                COUNT(DISTINCT pm.product_headcode) as usage_count,
                SUM(pm.quantity) as total_quantity,
                array_agg(DISTINCT p.product_name) as used_in_products
            FROM materials m
            INNER JOIN product_materials pm ON m.id_sap = pm.material_id_sap
            INNER JOIN products p ON pm.product_headcode = p.headcode
            WHERE p.headcode = ANY(%s)
            {material_filter}
            GROUP BY m.id_sap, m.material_name, m.material_group, 
                     m.material_subgroup, m.material_subprice, m.unit, m.image_url
            ORDER BY usage_count DESC, m.material_name ASC
            LIMIT 15
        """
        
        cur.execute(sql, [product_headcodes] + filter_params)
        results = cur.fetchall()
        
        conn.close()
        
        if not results:
            return {
                "materials": [],
                "search_method": "cross_table_no_materials",
                "matched_products": product_names
            }
        
        materials_with_context = []
        for mat in results:
            mat_dict = dict(mat)
            mat_dict['price'] = get_latest_material_price(mat['material_subprice'])
            mat_dict['used_in_products_list'] = mat['used_in_products'][:5]  # Top 5
            mat_dict['relevance_score'] = mat['usage_count'] / max_usage if max_usage > 0 else 0.5
            materials_with_context.append(mat_dict)
        
        print(f"✅ Found {len(materials_with_context)} materials used in these products")
        
        return {
            "materials": materials_with_context,
            "search_method": "cross_table_product_to_material",
            "matched_products": product_names[:5],
            "explanation": f"Vật liệu thường dùng cho: {', '.join(product_names[:3])}"
        }
        
    except Exception as e:
        print(f"❌ Cross-table materials search failed: {e}")
        conn.close()
        return {"materials": [], "search_method": "cross_table_error"}


# ========================================
# [NEW] USER FEEDBACK LEARNING SYSTEM
# ========================================


# ========================================
# THAY THẾ hàm save_user_feedback (dòng ~615)
# ========================================

def save_user_feedback(session_id: str, query: str, selected_items: list, 
                       rejected_items: list, search_type: str):
    """
    💾 V5.1 - Lưu feedback VÀ embedding cho query
    """
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # ✅ TẠO EMBEDDING CHO QUERY NGAY KHI LƯU
        query_embedding = generate_embedding(query)
        
        if not query_embedding:
            print("⚠️ Không tạo được embedding, vẫn lưu feedback")
        
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
            query_embedding  # ✅ LƯU EMBEDDING
        ))
        
        feedback_id = cur.fetchone()[0]
        
        conn.commit()
        conn.close()
        
        print(f"💾 Feedback saved: {len(selected_items)} selected, {len(rejected_items)} rejected")
        print(f"   → Feedback ID: {feedback_id}")
        print(f"   → Embedding: {'✅ OK' if query_embedding else '❌ NULL'}")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to save feedback: {e}")
        import traceback
        traceback.print_exc()
        return False






# ======================================
# THAY THẾ hàm get_feedback_boost_for_query (dòng ~900)
# ========================================

def get_feedback_boost_for_query(query: str, search_type: str, similarity_threshold: float = None) -> Dict:
    """
    📊 V5.0 - Vector-based feedback matching
    Tìm feedback từ các query TƯƠNG TỰ (không cần trùng 100%)
    
    Args:
        query: Câu hỏi hiện tại
        search_type: "product" hoặc "material"
        similarity_threshold: Ngưỡng độ tương tự (mặc định từ config)
    
    Returns:
        Dict[item_id, feedback_score]
    """
    from config import settings
    if similarity_threshold is None:
        similarity_threshold = settings.SIMILARITY_THRESHOLD_HIGH
    
    try:
        # 1. Tạo embedding cho query hiện tại
        query_vector = generate_embedding(query)
        
        if not query_vector:
            print("❌ Không tạo được embedding cho query")
            return {}
        
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # 2. Tìm các feedback có query_embedding tương tự (cosine similarity)
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
            print(f"ℹ️ Không có feedback tương tự (threshold={similarity_threshold})")
            return {}
        
        # 3. Tính điểm cho từng item (weighted by similarity)
        item_scores = {}
        
        print(f"\n{'='*60}")
        print(f"📊 FEEDBACK BOOST: Tìm thấy {len(similar_feedbacks)} query tương tự")
        print(f"{'='*60}\n")
        
        for fb in similar_feedbacks:
            sim = fb['similarity']
            
            try:
                # ✅ FIX: Kiểm tra type trước khi parse
                selected_items = fb['selected_items']
                
                # Nếu là string JSON → parse
                if isinstance(selected_items, str):
                    selected = json.loads(selected_items)
                # Nếu đã là list → dùng luôn
                elif isinstance(selected_items, list):
                    selected = selected_items
                else:
                    print(f"⚠️ Unknown type for selected_items: {type(selected_items)}")
                    continue
                
                print(f"✅ Query: '{fb['query'][:50]}...' (sim={sim:.2f})")
                print(f"   → Selected: {selected[:3]}")
                
                for item_id in selected:
                    # Điểm = similarity * 1 (có thể thay bằng decay theo thời gian)
                    item_scores[item_id] = item_scores.get(item_id, 0) + sim
                    
            except Exception as e:
                print(f"⚠️ Skip feedback: {e}")
                continue
        
        if item_scores:
            print(f"\n📈 Kết quả:")
            for item_id, score in sorted(item_scores.items(), key=lambda x: x[1], reverse=True)[:5]:
                print(f"   {item_id}: {score:.2f} điểm")
        else:
            print("ℹ️ Không có item nào được boost")
            
        print(f"{'='*60}\n")
        
        return item_scores
        
    except Exception as e:
        print(f"❌ Failed to get feedback boost: {e}")
        import traceback
        traceback.print_exc()
        return {}
# ========================================
# THAY THẾ hàm rerank_with_feedback (dòng ~570)
# Thêm LOG chi tiết
# ========================================

def rerank_with_feedback(items: list, feedback_scores: Dict, 
                         id_key: str = "headcode", boost_weight: float = 0.5):  # ← ✅ TĂNG từ 0.3 → 0.5
    """
    🎯 V5.6 - Boost weight tăng lên 0.5 để feedback có tác động mạnh hơn
    """
    if not feedback_scores:
        print("⚠️ Không có feedback scores để rerank")
        return items
    
    max_feedback = max(feedback_scores.values()) if feedback_scores else 1
    
    print(f"\n{'='*60}")
    print(f"🎯 RERANKING: {len(items)} items | Boost weight: {boost_weight}")
    print(f"📊 Feedback history: {len(feedback_scores)} items có điểm")
    print(f"{'='*60}\n")
    
    boosted_items = []
    unchanged_items = []
    
    for item in items:
        item_id = item.get(id_key)
        feedback_count = feedback_scores.get(item_id, 0)
        
        # Normalize feedback score 0-1
        feedback_boost = (feedback_count / max_feedback) if max_feedback > 0 else 0
        
        # ✅ QUAN TRỌNG: Dùng 'similarity' (đã được set = personalized_score)
        current_score = item.get('similarity', item.get('relevance_score', 0.5))
        
        # ✅ Công thức mới: Boost weight cao hơn (0.5 thay vì 0.3)
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
                  f"Feedback: {feedback_count:.2f} lần")
        else:
            unchanged_items.append(item)
    
    print(f"\n📈 Kết quả:")
    print(f"   - {len(boosted_items)} items được boost")
    print(f"   - {len(unchanged_items)} items không đổi")
    print(f"{'='*60}\n")
    
    return items  # Không sort ở đây, để search_products() sort sau
# ========================================
# THÊM VÀO chatbot_api.py SAU HÀM rerank_with_feedback
# Dòng ~620
# ========================================

# ========================================
# SỬA trong apply_feedback_to_search (dòng ~720)
# ========================================

def apply_feedback_to_search(items: list, query: str, search_type: str, 
                             id_key: str = "headcode") -> list:
    """
    🎯 V5.6 - Lưu original_rank TRƯỚC khi rerank
    """
    if not items:
        return items
    
    # ✅ LƯU ORIGINAL RANK (dựa trên personalized_score)
    for idx, item in enumerate(items):
        item['original_rank'] = idx + 1
    
    # Get feedback scores
    feedback_scores = get_feedback_boost_for_query(
        query, 
        search_type,
        similarity_threshold=settings.SIMILARITY_THRESHOLD_VERY_HIGH
    )
    
    if not feedback_scores:
        print("ℹ️ Không có feedback history phù hợp")
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
# ========================================
# HOẶC LÀM THRESHOLD ĐỘNG (tùy chọn)
# ========================================

def get_adaptive_threshold(query: str) -> float:
    """
    Tự động điều chỉnh threshold:
    - Query dài, cụ thể → threshold thấp (0.75)
    - Query ngắn, chung chung → threshold cao (0.90)
    """
    words = query.split()
    
    if len(words) >= 8:
        return 0.75  # Query dài → dễ dãi hơn
    elif len(words) >= 5:
        return 0.82
    else:
        return 0.90  # Query ngắn → nghiêm ngặt hơn
    
# Dùng trong apply_feedback_to_search:
# threshold = get_adaptive_threshold(query)
# feedback_scores = get_feedback_boost_for_query(query, search_type, threshold)


def get_ranking_summary(items: list) -> dict:
    """
    📊 Tạo summary về ranking để hiển thị trong UI
    
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
# PRODUCT FUNCTIONS
# ========================================

def search_products(params: Dict, session_id: str = None):
    """🔍 V5.9 - FIXED: Chỉ 1 lớp ranking, không overlap"""
    
    try:
        result = search_products_hybrid(params)
        if result.get("products"):
            products = result["products"]
            
            # ========== STEP 1: BASE SCORES ==========
            for product in products:
                product['base_score'] = float(product.get('similarity', 0.5))
            
            # ========== STEP 2: PERSONALIZATION ==========
            # ✅ CHỈ áp dụng nếu có session_id VÀ user có history
            has_personalization = False
            
            if session_id:
                print(f"\n🎯 Personalization for {session_id[:8]}...")
                
                # ✅ CHECK trước xem user có history không
                conn = get_db()
                cur = conn.cursor()
                cur.execute("""
                    SELECT COUNT(*) FROM user_preferences 
                    WHERE session_id = %s
                """, (session_id,))
                history_count = cur.fetchone()[0]
                conn.close()
                
                if history_count > 0:
                    has_personalization = True
                    print(f"   ✅ Found {history_count} interactions")
                    
                    for product in products:
                        conn = get_db()
                        cur = conn.cursor(cursor_factory=RealDictCursor)
                        
                        cur.execute("""
                            SELECT description_embedding 
                            FROM products 
                            WHERE headcode = %s AND description_embedding IS NOT NULL
                        """, (product['headcode'],))
                        
                        vec_result = cur.fetchone()
                        conn.close()
                        
                        if vec_result and vec_result['description_embedding']:
                            personal_score = calculate_personalized_score(
                                vec_result['description_embedding'],
                                session_id
                            )
                            product['personal_score'] = float(personal_score)
                        else:
                            product['personal_score'] = 0.5
                else:
                    print(f"   ℹ️ No history - Skip personalization")
            
            # ✅ Nếu không có personalization → set neutral 0.5
            if not has_personalization:
                for product in products:
                    product['personal_score'] = 0.5
            
            print(f"✅ Personalization done\n")
            
            # ========== STEP 3: FEEDBACK SCORES ==========
            print(f"🎯 Feedback Scoring...")
            
            feedback_dict = get_feedback_boost_for_query(
                params.get("keywords_vector", ""),
                search_type="product",
                similarity_threshold=settings.SIMILARITY_THRESHOLD_VERY_HIGH
            )
            
            max_feedback = max(feedback_dict.values()) if feedback_dict else 1.0
            
            for product in products:
                headcode = product.get('headcode')
                raw_feedback = feedback_dict.get(headcode, 0)
                
                product['feedback_score'] = float(raw_feedback / max_feedback) if max_feedback > 0 else 0.0
                product['feedback_count'] = float(raw_feedback)
            
            print(f"✅ Feedback Scoring done\n")
            
            # ========== STEP 4: WEIGHTED SUM ==========
            print(f"🎯 Final Ranking (Weighted Sum)...")
            
            # ✅ ADAPTIVE WEIGHTS
            if has_personalization:
                # User có history → ưu tiên personalization
                W_BASE = 0.3
                W_PERSONAL = 0.5
                W_FEEDBACK = 0.2
            else:
                # User mới → ưu tiên base + social proof
                W_BASE = 0.6
                W_PERSONAL = 0.0  # ❌ KHÔNG dùng personal_score
                W_FEEDBACK = 0.4
            
            for idx, product in enumerate(products):
                base = product.get('base_score', 0.5)
                personal = product.get('personal_score', 0.5)
                feedback = product.get('feedback_score', 0.0)
                
                # ✅ Chỉ tính personal nếu has_personalization
                if has_personalization:
                    final_score = (W_BASE * base) + (W_PERSONAL * personal) + (W_FEEDBACK * feedback)
                else:
                    final_score = (W_BASE * base) + (W_FEEDBACK * feedback)
                
                product['final_score'] = float(final_score)
                product['original_rank'] = idx + 1
                
                print(f"  {product['headcode']}: "
                      f"base={base:.3f} | pers={personal:.3f} | fb={feedback:.3f} "
                      f"→ final={final_score:.3f}")
            
            # ========== STEP 5: SORT FINAL ==========
            products.sort(key=lambda x: x.get('final_score', 0), reverse=True)
            
            for idx, product in enumerate(products):
                product['final_rank'] = idx + 1
                
                if product.get('feedback_count', 0) > 0:
                    product['has_feedback'] = True
            
            print(f"✅ Final Ranking complete\n")
            
            result["products"] = products
            result["ranking_summary"] = get_ranking_summary(products)
            result["can_provide_feedback"] = True
            
            return result
            
    except Exception as e:
        print(f"⚠️ TIER 1 failed: {e}")
        import traceback
        traceback.print_exc()
    
    # TIER 2 & 3: Giữ nguyên code cũ (Fallback)
    # ...
    
    # TIER 2 & 3: Giữ nguyên...
    # (code cũ không đổi)
    
    # TIER 2 & 3: GIỮ NGUYÊN CODE CŨ (Fallback)
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    if params.get("keywords_vector"):
        query_text = params["keywords_vector"]
    else:
        query_parts = []
        if params.get("category"): query_parts.append(params["category"])
        if params.get("sub_category"): query_parts.append(params["sub_category"])
        if params.get("material_primary"): query_parts.append(params["material_primary"])
        query_text = " ".join(query_parts) if query_parts else "nội thất"

    query_vector = generate_embedding(query_text)
    
    if not query_vector:
        conn.close()
        return search_products_keyword_only(params)
    
    # TIER 2: Pure Vector
    try:
        sql = """
            SELECT headcode, product_name, category, sub_category, 
                   material_primary, project, project_id,
                   (description_embedding <=> %s::vector) as distance
            FROM products
            WHERE description_embedding IS NOT NULL
            ORDER BY distance ASC
            LIMIT 10
        """
        
        cur.execute(sql, [query_vector])
        results = cur.fetchall()
        
        if results:
            print(f"✅ TIER 2: {len(results)} products")
            products = format_search_results(results[:8])
            conn.close()
            return {"products": products, "search_method": "vector_no_filter"}
    except Exception as e:
        print(f"⚠️ TIER 2 failed: {e}")
    
    # TIER 3: Keyword
    conn.close()
    return search_products_keyword_only(params)

def search_products_keyword_only(params: Dict):
    """TIER 3: Fallback keyword search"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    conditions = []
    values = []
    
    if params.get("category"):
        cat = params['category']
        conditions.append("(category ILIKE %s OR sub_category ILIKE %s OR product_name ILIKE %s)")
        values.extend([f"%{cat}%", f"%{cat}%", f"%{cat}%"])
    
    if params.get("material_primary"):
        mat = params['material_primary']
        conditions.append("(material_primary ILIKE %s OR product_name ILIKE %s)")
        values.extend([f"%{mat}%", f"%{mat}%"])
    
    if conditions:
        where_clause = " OR ".join(conditions)
        sql = f"SELECT * FROM products WHERE {where_clause} LIMIT 12"
    else:
        sql = "SELECT * FROM products ORDER BY RANDOM() LIMIT 10"
        values = []
    
    try:
        cur.execute(sql, values)
        results = cur.fetchall()
        conn.close()
        
        if not results:
            return {
                "response": "Không tìm thấy sản phẩm phù hợp.",
                "products": []
            }
        
        print(f"✅ TIER 3 Success: Found {len(results)} products")
        return {
            "products": [dict(r) for r in results],
            "search_method": "keyword"
        }
    except Exception as e:
        conn.close()
        print(f"❌ TIER 3 failed: {e}")
        return {
            "response": "Lỗi tìm kiếm.",
            "products": []
        }

def get_product_materials(headcode: str):
    """Lấy danh sách vật liệu của SẢN PHẨM"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT product_name FROM products WHERE headcode = %s", (headcode,))
    prod = cur.fetchone()
    
    if not prod:
        conn.close()
        return {"response": f"❌ Không tìm thấy sản phẩm với mã **{headcode}**"}
    
    sql = """
        SELECT 
            m.id_sap,
            m.material_name, 
            m.material_group,
            m.material_subgroup,
            m.material_subprice,
            m.unit as material_unit,
            m.image_url,
            pm.quantity, 
            pm.unit as pm_unit
        FROM product_materials pm
        INNER JOIN materials m ON pm.material_id_sap = m.id_sap
        WHERE pm.product_headcode = %s
        ORDER BY m.material_name ASC
    """
    
    try:
        cur.execute(sql, (headcode,))
        materials = cur.fetchall()
        print(f"📊 Found {len(materials)} materials for {headcode}")
    except Exception as e:
        print(f"❌ Query error: {e}")
        conn.close()
        return {"response": f"Lỗi truy vấn database: {str(e)}"}
    
    conn.close()
    
    if not materials:
        return {
            "response": f"⚠️ Sản phẩm **{prod['product_name']}** ({headcode}) chưa có định mức vật liệu.\n\n"
                        f" Có thể:\n"
                        f"• Sản phẩm mới chưa nhập định mức\n"
                        f"• Chưa import file product_materials.csv\n"
                        f"• Mã sản phẩm trong product_materials không khớp\n\n"
                        f"Vui lòng kiểm tra lại hoặc liên hệ bộ phận kỹ thuật."
        }
    
    total = 0
    materials_with_price = []
    
    for mat in materials:
        latest_price = get_latest_material_price(mat['material_subprice'])
        quantity = float(mat['quantity']) if mat['quantity'] else 0.0 
        total_cost = quantity * latest_price
        total += total_cost
        
        materials_with_price.append({
            'id_sap': mat['id_sap'],
            'material_name': mat['material_name'],
            'material_group': mat['material_group'],
            'material_subgroup': mat['material_subgroup'],
            'material_unit': mat['material_unit'],
            'image_url': mat['image_url'],
            'quantity': quantity,
            'pm_unit': mat['pm_unit'],
            'price': latest_price,
            'unit_price': latest_price,
            'unit': mat['material_unit'],
            'total_cost': total_cost,
            'price_history': mat['material_subprice']
        })
    
    response = f"🎉 **ĐỊNH MỨC VẬT LIỆU: {prod['product_name']}**\n"
    response += f"🏷️ Mã: `{headcode}`\n"
    response += f"📦 Tổng số loại vật liệu: **{len(materials_with_price)}**\n\n"
    response += "---\n\n"
    
    for idx, mat in enumerate(materials_with_price[:10], 1):
        response += f"**{idx}. {mat['material_name']}**\n"
        response += f"   • Mã SAP: `{mat['id_sap']}`\n"
        response += f"   • Nhóm: {mat['material_group']}"
        if mat['material_subgroup']:
            response += f" - {mat['material_subgroup']}"
        response += f"\n"
        response += f"   • Số lượng: {mat['quantity']} {mat['pm_unit']}\n"
        response += f"   • Đơn giá mới nhất: {mat['unit_price']:,.2f} VNĐ\n"
        response += f"   • Thành tiền: **{mat['total_cost']:,.2f} VNĐ**\n"
        
        if mat.get('image_url'):
            response += f"   • [📷 Xem ảnh]({mat['image_url']})\n"
        
        response += "\n"
    
    if len(materials_with_price) > 10:
        response += f"\n*...và {len(materials_with_price)-10} vật liệu khác.*\n"
    
    response += f"\n---\n\n💰 **TỔNG CHI PHÍ NGUYÊN VẬT LIỆU: {total:,.2f} VNĐ**"
    response += f"\n\n⚠️ **Lưu ý:** Giá được tính từ lịch sử mua hàng gần nhất. Giá thực tế có thể thay đổi."
    
    return {
        "response": response,
        "materials": materials_with_price,
        "total_cost": total,
        "product_name": prod['product_name']
    }

# ========================================
# FIX BUG TRONG chatbot_api.py
# Dòng 1230 - 1260 (hàm calculate_product_cost)
# ========================================
# ========================================
# FIX 3: DÒNG ~1288-1370
# Thay thế hàm calculate_product_cost
# ========================================

def calculate_product_cost(headcode: str):
    """Tính CHI PHÍ NGUYÊN VẬT LIỆU sản phẩm (Đơn giản hóa V4.7)"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT product_name, category FROM products WHERE headcode = %s", (headcode,))
    prod = cur.fetchone()
    
    if not prod:
        conn.close()
        return {"response": f"❌ Không tìm thấy sản phẩm với mã **{headcode}**"}
    
    sql = """
        SELECT 
            m.material_name,
            m.material_group,
            m.material_subprice,
            m.unit as material_unit,
            pm.quantity,
            pm.unit as pm_unit
        FROM product_materials pm
        INNER JOIN materials m ON pm.material_id_sap = m.id_sap
        WHERE pm.product_headcode = %s
        ORDER BY m.material_name ASC
    """
    
    try:
        cur.execute(sql, (headcode,))
        materials = cur.fetchall()
        print(f"💰 Cost calculation for {headcode}: {len(materials)} materials")
    except Exception as e:
        print(f"❌ Query error: {e}")
        conn.close()
        return {"response": f"Lỗi truy vấn database: {str(e)}"}
    
    conn.close()
    
    if not materials:
        return {
            "response": f"⚠️ Sản phẩm **{prod['product_name']}** ({headcode}) chưa có định mức vật liệu.\n\n"
                       f"**Nguyên nhân có thể:**\n"
                       f"• Sản phẩm mới chưa nhập định mức\n"
                       f"• Chưa import file `product_materials.csv`\n"
                       f"• Mã sản phẩm trong file CSV không khớp với `{headcode}`\n\n"
                       f"**Giải pháp:**\n"
                       f"1. Kiểm tra file CSV có dòng nào với `product_headcode = {headcode}`\n"
                       f"2. Import lại file qua sidebar: **Import Dữ Liệu → Định Mức**"
        }
    
    # ✅ Tính TỔNG CHI PHÍ VẬT LIỆU
    material_cost = 0.0
    material_count = len(materials)
    materials_detail = []
    
    for mat in materials:
        quantity = float(mat['quantity']) if mat['quantity'] else 0.0
        latest_price = get_latest_material_price(mat['material_subprice'])
        total_cost = quantity * latest_price
        material_cost += total_cost
        
        materials_detail.append({
            'name': mat['material_name'],
            'group': mat['material_group'],
            'quantity': quantity,
            'unit': mat['pm_unit'],
            'unit_price': latest_price,
            'total': total_cost
        })
    
    # ✅ RESPONSE ĐƠN GIẢN - CHỈ CHI PHÍ VẬT LIỆU
    response = f"""
💰 **BÁO GIÁ NGUYÊN VẬT LIỆU**

📦 **Sản phẩm:** {prod['product_name']}
🏷️ **Mã:** `{headcode}`
📂 **Danh mục:** {prod['category'] or 'N/A'}

---

**CHI TIẾT NGUYÊN VẬT LIỆU ({material_count} loại):**

"""
    
    for idx, mat in enumerate(materials_detail[:15], 1):
        response += f"{idx}. **{mat['name']}** ({mat['group']})\n"
        response += f"   • Số lượng: {mat['quantity']} {mat['unit']}\n"
        response += f"   • Đơn giá: {mat['unit_price']:,.0f} VNĐ\n"
        response += f"   • Thành tiền: **{mat['total']:,.0f} VNĐ**\n\n"
    
    if len(materials_detail) > 15:
        response += f"*...và {len(materials_detail)-15} vật liệu khác*\n\n"
    
    response += f"---\n\n"
    response += f"✅ **TỔNG CHI PHÍ NGUYÊN VẬT LIỆU: {material_cost:,.0f} VNĐ**\n\n"
    response += f"📋 **Lưu ý:** Giá được tính từ lịch sử mua hàng gần nhất.\n"
    response += f"💡 **Muốn xem chi tiết định mức?** Hỏi: _\"Phân tích vật liệu {headcode}\"_"
    
    return {
        "response": response,
        "material_cost": material_cost,
        "material_count": material_count,
        "materials": materials_detail,
        "suggested_prompts":[
            "Phân tích vật liệu {headcode}"
        ]
    }

# ========================================
# MATERIAL FUNCTIONS
# ========================================

def search_materials(params: Dict):
    """Tìm kiếm NGUYÊN VẬT LIỆU với giá từ material_subprice"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    query_parts = []
    if params.get("material_name"): 
        query_parts.append(params["material_name"])
    if params.get("material_group"): 
        query_parts.append(params["material_group"])
    if params.get("usage_context"): 
        query_parts.append(params["usage_context"])
    if params.get("keywords_vector"): 
        query_parts.append(params["keywords_vector"])
    
    query_text = " ".join(query_parts) if query_parts else "vật liệu nội thất"
    print(f"🔍 Searching materials for: {query_text}")
    
    query_vector = generate_embedding(query_text)
    
    if query_vector:
        try:
            filter_clause = "1=1"
            filter_params = []
            
            if params.get("material_group"):
                filter_clause = "material_group ILIKE %s"
                filter_params = [f"%{params['material_group']}%"]
            
            sql = f"""
                SELECT 
                    id_sap, material_name, material_group, material_subgroup,
                    material_subprice, unit, image_url,
                    (description_embedding <=> %s::vector) as distance
                FROM materials
                WHERE description_embedding IS NOT NULL AND {filter_clause}
                ORDER BY distance ASC
                LIMIT 10
            """
            
            cur.execute(sql, [query_vector] + filter_params)
            results = cur.fetchall()
            
            if results:
                print(f"✅ Vector search: Found {len(results)} materials")
                
                materials_with_price = []
                for mat in results:
                    mat_dict = dict(mat)
                    mat_dict['price'] = get_latest_material_price(mat_dict['material_subprice'])
                    materials_with_price.append(mat_dict)
                
                conn.close()
                return {
                    "materials": materials_with_price,
                    "search_method": "vector"
                }
        except Exception as e:
            print(f"⚠️ Vector search failed: {e}")
    
    print("ℹ️ Keyword search for materials")
    conditions = []
    values = []
    
    if params.get("material_name"):
        name = params['material_name']
        conditions.append("(material_name ILIKE %s OR material_group ILIKE %s)")
        values.extend([f"%{name}%", f"%{name}%"])
    
    if params.get("material_group"):
        group = params['material_group']
        conditions.append("material_group ILIKE %s")
        values.append(f"%{group}%")
    
    if conditions:
        where_clause = " OR ".join(conditions)
        sql = f"SELECT * FROM materials WHERE {where_clause} LIMIT 15"
    else:
        sql = "SELECT * FROM materials ORDER BY material_name ASC LIMIT 10"
        values = []
    
    try:
        cur.execute(sql, values)
        results = cur.fetchall()
        conn.close()
        
        if not results:
            return {
                "response": "Không tìm thấy vật liệu phù hợp.",
                "materials": []
            }
        
        materials_with_price = []
        for mat in results:
            mat_dict = dict(mat)
            mat_dict['price'] = get_latest_material_price(mat.get('material_subprice'))
            materials_with_price.append(mat_dict)
        
        print(f"✅ Keyword search: Found {len(materials_with_price)} materials")
        return {
            "materials": materials_with_price,
            "search_method": "keyword"
        }
    except Exception as e:
        conn.close()
        print(f"❌ Material search failed: {e}")
        return {
            "response": "Lỗi tìm kiếm vật liệu.",
            "materials": []
        }

def get_material_detail(id_sap: str = None, material_name: str = None):
    """Xem chi tiết VẬT LIỆU + lịch sử giá + sản phẩm sử dụng"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    if id_sap:
        cur.execute("SELECT * FROM materials WHERE id_sap = %s", (id_sap,))
    elif material_name:
        cur.execute("SELECT * FROM materials WHERE material_name ILIKE %s LIMIT 1", (f"%{material_name}%",))
    else:
        conn.close()
        return {"response": "⚠️ Cần cung cấp mã SAP hoặc tên vật liệu."}
    
    material = cur.fetchone()
    
    if not material:
        conn.close()
        return {"response": f"❌ Không tìm thấy vật liệu **{id_sap or material_name}**"}
    
    latest_price = get_latest_material_price(material['material_subprice'])

    sql = """
        SELECT 
            p.headcode,
            p.product_name,
            p.category,
            p.sub_category,
            p.project,
            pm.quantity,
            pm.unit
        FROM product_materials pm
        INNER JOIN products p ON pm.product_headcode = p.headcode
        WHERE pm.material_id_sap = %s
        ORDER BY p.product_name ASC
        LIMIT 20
    """
    
    try:
        cur.execute(sql, (material['id_sap'],))
        used_in_products = cur.fetchall()
        print(f"🔗 Material {material['id_sap']} used in {len(used_in_products)} products")
    except Exception as e:
        print(f"❌ Query error: {e}")
        used_in_products = []
    
    try:
        cur.execute("""
            SELECT 
                COUNT(DISTINCT pm.product_headcode) as product_count,
                COUNT(DISTINCT p.project) as project_count,
                SUM(pm.quantity) as total_quantity
            FROM product_materials pm
            LEFT JOIN products p ON pm.product_headcode = p.headcode
            WHERE pm.material_id_sap = %s
        """, (material['id_sap'],))
        stats = cur.fetchone()
    except Exception as e:
        print(f"❌ Stats query error: {e}")
        stats = {
            'product_count': 0,
            'project_count': 0,
            'total_quantity': 0
        }
    
    conn.close()
    
    price_history = []
    try:
        if material['material_subprice']:
            price_history = json.loads(material['material_subprice'])
    except:
        pass
    
    response = f"🧱 **CHI TIẾT NGUYÊN VẬT LIỆU**\n\n"
    response += f"📦 **Tên:** {material['material_name']}\n\n"
    response += f"🏷️ **Mã SAP:** `{material['id_sap']}\n\n"
    response += f"📂 **Nhóm:** {material['material_group']}\n\n"
    
    if material.get('material_subgroup'):
        response += f" - {material['material_subgroup']}"
    
    response += f"💰 **Giá mới nhất:** {latest_price:,.2f} VNĐ/{material['unit']}\n\n"
    response += f"📊 **THỐNG KÊ SỬ DỤNG:**\n"
    response += f"• Được sử dụng trong **{stats['product_count']} sản phẩm**\n"
    response += f"• Xuất hiện ở **{stats['project_count']} dự án**\n"
    response += f"• Tổng số lượng: **{stats.get('total_quantity', 0) or 0} {material['unit']}**\n\n"
    response += "\n---\n\n"
    
    if price_history and len(price_history) > 0:
        response += "📈 **LỊCH SỬ GIÁ:**\n\n"
        for idx, ph in enumerate(sorted(price_history, key=lambda x: x['date'], reverse=True)[:5], 1):
            response += f"{idx}. **{ph['date']}**: {ph['price']:,.2f} VNĐ\n"
        response += "\n---\n\n"
    
    if used_in_products and len(used_in_products) > 0:
        response += f"🔗 **CÁC SẢN PHẨM SỬ DỤNG VẬT LIỆU NÀY:**\n\n"
        
        for idx, prod in enumerate(used_in_products[:10], 1):
            response += f"{idx}. **{prod['product_name']}** (`{prod['headcode']}`)\n"
            response += f"   • Danh mục: {prod.get('category', 'N/A')}"
            if prod.get('sub_category'):
                response += f" - {prod['sub_category']}"
            response += "\n"
            
            if prod.get('project'):
                response += f"   • Dự án: {prod['project']}\n"
            
            response += f"   • Sử dụng: **{prod['quantity']} {prod['unit']}**\n\n"
        
        if len(used_in_products) > 10:
            response += f"*...và {len(used_in_products)-10} sản phẩm khác*\n\n"
    else:
        response += "🔗 **CHƯA CÓ SẢN PHẨM SỬ DỤNG**\n\n"
        response += "_Vật liệu này chưa được gắn vào sản phẩm nào trong hệ thống._\n\n"
    
    if material.get('image_url'):
        response += f"---\n\n🖼️ **Xem ảnh vật liệu:** [Google Drive Link]({material['image_url']})\n"
        response += f"_(Click để xem ảnh chi tiết)_"
    
    return {
        "response": response,
        # "material_detail": dict(material),
        "materials": [{  # ✅ Đổi thành list giống search_materials
        **dict(material),
        'price': latest_price  # ✅ Thêm key 'price'
    }],
        "latest_price": latest_price,
        "price_history": price_history,
        "used_in_products": [dict(p) for p in used_in_products],
        "stats": dict(stats) if stats else {},
        "has_image": bool(material.get('image_url'))
    }



def list_material_groups():
    """Liệt kê các nhóm vật liệu với giá tính từ material_subprice"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    sql = """
        SELECT 
            material_group,
            COUNT(*) as count,
            array_agg(DISTINCT material_subprice) as all_prices
        FROM materials
        WHERE material_group IS NOT NULL
        GROUP BY material_group
        ORDER BY count DESC
    """
    cur.execute(sql)
    groups = cur.fetchall()
    conn.close()
    
    if not groups:
        return {"response": "Chưa có dữ liệu nhóm vật liệu."}
    
    response = f"📋 **DANH SÁCH NHÓM VẬT LIỆU ({len(groups)} nhóm):**\n\n"
    
    groups_with_stats = []
    for g in groups:
        prices = []
        for price_json in g['all_prices']:
            if price_json:
                latest = get_latest_material_price(price_json)
                if latest > 0:
                    prices.append(latest)
        
        avg_price = sum(prices) / len(prices) if prices else 0
        min_price = min(prices) if prices else 0
        max_price = max(prices) if prices else 0
        
        groups_with_stats.append({
            'material_group': g['material_group'],
            'count': g['count'],
            'avg_price': avg_price,
            'min_price': min_price,
            'max_price': max_price
        })
    
    for idx, g in enumerate(groups_with_stats, 1):
        response += f"{idx}. **{g['material_group']}** ({g['count']} loại)\n"
        if g['avg_price'] > 0:
            response += f"   • Giá TB: {g['avg_price']:,.2f} VNĐ\n"
            response += f"   • Khoảng giá: {g['min_price']:,.2f} - {g['max_price']:,.2f} VNĐ\n"
        response += "\n"
    
    return {
        "response": response,
        "material_groups": groups_with_stats
    }

# ========================================
# MAIN CHAT ENDPOINT
# ========================================

@app.post("/chat")
def chat(msg: ChatMessage):
    """Main chat logic"""
    try:
        user_message = msg.message
        context = msg.context or {}
        
        intent_data = get_intent_and_params(user_message, context)
        
        if intent_data.get("intent") == "error":
            return {"response": "Xin lỗi, hệ thống đang bận. Vui lòng thử lại."}
        
        intent = intent_data["intent"]
        params = intent_data.get("params", {})
        
        result_response = None
        result_count = 0
        
        # GREETING
        if intent == "greeting":
            result_response = {
                "response": "👋 Xin chào! Tôi là trợ lý AI của AA Corporation.\n\n"
                           "Tôi có thể giúp bạn:\n"
                           "• 🔍 **Tìm sản phẩm** (bàn, ghế, sofa...)\n"
                           "• 🧱 **Tìm nguyên vật liệu** (gỗ, da, đá, vải...)\n"
                           "• 💰 **Tính chi phí** sản phẩm\n"
                           "• 📋 **Xem định mức** nguyên vật liệu\n\n"
                           "Bạn cần tìm gì hôm nay?",
                
                "suggested_prompts": [
                    "🔍 Tìm sản phẩm", 
                    "🧱 Tìm nguyên vật liệu", 
                    "💰 Xem giá sản phẩm",
                    "📋 Danh sách nhóm vật liệu"
                ]
            }
        
        # PRODUCT FLOW
        # elif intent == "search_product":
        #     search_result = search_products(params)
        #     products = search_result.get("products", [])
        #     result_count = len(products)
            
        #     if not products:
        #         result_response = {"response": search_result.get("response", "Không tìm thấy sản phẩm.")}
        #     else:
        #         response_text = ""
        #         suggested_prompts = []
                
        #         if intent_data.get("is_broad_query"):
        #             follow_up = intent_data.get("follow_up_question", "Bạn muốn tìm loại cụ thể nào?")
        #             response_text = (
        #                 f"🔎 Tìm thấy **{len(products)} sản phẩm** phù hợp với từ khóa chung.\n"
        #                 f"*(Tôi đã chọn lọc các mẫu phổ biến nhất bên dưới)*\n\n"
        #                 f"💡 **Gợi ý:** {follow_up}"
        #             )
        #             actions = intent_data.get("suggested_actions", [])
        #             suggested_prompts = [f"🔍 {a}" for a in actions] if actions else []
        #         else:
        #             response_text = f"✅ Đã tìm thấy **{len(products)} sản phẩm** đúng yêu cầu của bạn."
        #             suggested_prompts = [
        #                 f"💰 Tính chi phí {products[0]['headcode']}",
        #                 f"📋 Xem vật liệu {products[0]['headcode']}"
        #             ]
                
        #         result_response = {
        #             "response": response_text,
        #             "products": products,
        #             "suggested_prompts": suggested_prompts
        #         }
        #         # CROSS-TABLE: Tìm sản phẩm theo vật liệu
        
        # PRODUCT FLOW - CẬP NHẬT V4.8 (Feedback Ranking)




        elif intent == "search_product":
            search_result = search_products(params, session_id=msg.session_id)
            products = search_result.get("products", [])
            
            # ✅ search_products đã xử lý HẾT ranking rồi, không cần gọi gì thêm
            
            ranking_summary = search_result.get("ranking_summary", {})
            result_count = len(products)
            
            if not products:
                result_response = {"response": search_result.get("response", "Không tìm thấy sản phẩm.")}
            else:





                response_text = ""
                suggested_prompts = []
                
                if intent_data.get("is_broad_query"):
                    follow_up = intent_data.get("follow_up_question", "Bạn muốn tìm loại cụ thể nào?")
                    response_text = (
                        f"🔎 Tìm thấy **{len(products)} sản phẩm** phù hợp với từ khóa chung.\n"
                        f"*(Tôi đã chọn lọc các mẫu phổ biến nhất bên dưới)*\n\n"
                        f"💡 **Gợi ý:** {follow_up}"
                    )
                    actions = intent_data.get("suggested_actions", [])
                    suggested_prompts = [f"🔍 {a}" for a in actions] if actions else []
                else:
                    response_text = f"✅ Đã tìm thấy **{len(products)} sản phẩm** đúng yêu cầu của bạn."
                    
                    # ✅ THÊM: Hiển thị thông tin ranking nếu có
                    if ranking_summary['ranking_applied']:
                        response_text += f"\n\n⭐ **{ranking_summary['boosted_items']} sản phẩm** được ưu tiên dựa trên lịch sử tìm kiếm."
                    
                    suggested_prompts = [
                        f"💰 Tính chi phí {products[0]['headcode']}",
                        f"📋 Xem vật liệu {products[0]['headcode']}"
                    ]
                
                result_response = {
                    "response": response_text,
                    "products": products,
                    "suggested_prompts": suggested_prompts,
                    "ranking_summary": ranking_summary,  # ✅ THÊM
                    "can_provide_feedback": True  # ✅ THÊM
                }
        
        
        elif intent == "search_product_by_material":
            material_query = params.get("material_name") or params.get("material_primary") or params.get("keywords_vector")
            
            if not material_query:
                result_response = {
                    "response": "⚠️ Bạn muốn tìm sản phẩm làm từ vật liệu nào?",
                    "suggested_prompts": [
                        "🔍 Bàn làm từ đá marble",
                        "🔍 Ghế gỗ teak",
                        "🔍 Tủ gỗ sồi"
                    ]
                }
            else:
                search_result = search_products_by_material(material_query, params)
                products = search_result.get("products", [])
                
                feedback_scores = get_feedback_boost_for_query(user_message, "product")
                if feedback_scores:
                    products = rerank_with_feedback(products, feedback_scores, "headcode")
                
                result_count = len(products)
                
                if not products:
                    matched_mats = search_result.get("matched_materials", [])
                    result_response = {
                        "response": f"🔍 Đã tìm thấy vật liệu: **{', '.join(matched_mats)}**\n\n"
                                   f"Nhưng không có sản phẩm nào sử dụng vật liệu này trong hệ thống.\n\n"
                                   f"💡 Thử tìm kiếm khác hoặc mở rộng điều kiện.",
                        "materials": []
                    }
                else:
                    explanation = search_result.get("explanation", "")
                    response_text = f"✅ {explanation}\n\n"
                    response_text += f"📦 Tìm thấy **{len(products)} sản phẩm**:"
                    
                    result_response = {
                        "response": response_text,
                        "products": products,
                        "search_method": "cross_table",
                        "can_provide_feedback": True
                    }

        
    


        # CROSS-TABLE: Tìm vật liệu cho sản phẩm
        elif intent == "search_material_for_product":
            # 1. Lấy query từ params hoặc context
            product_query = params.get("category") or params.get("usage_context") or params.get("keywords_vector")
            
            if not product_query:
                result_response = {
                    "response": "⚠️ Bạn muốn tìm vật liệu để làm sản phẩm gì?",
                    "suggested_prompts": [
                        "🧱 Vật liệu làm bàn ăn",
                        "🧱 Nguyên liệu ghế sofa",
                        "🧱 Đá làm bàn coffee"
                    ]
                }
            else:
                # 2. Gọi hàm tìm kiếm
                search_result = search_materials_for_product(product_query, params)
                materials = search_result.get("materials", [])
                
                # 3. [MỚI] Áp dụng Feedback Ranking (Giống Intent 3)
                # Dùng query gốc của user để tìm feedback tương tự
                feedback_scores = get_feedback_boost_for_query(user_message, "material")
                if feedback_scores:
                    materials = rerank_with_feedback(materials, feedback_scores, "id_sap")
                
                # 4. [MỚI] Lấy thông tin Ranking Summary để hiển thị UI
                ranking_summary = get_ranking_summary(materials)
                
                result_count = len(materials)
                
                if not materials:
                    result_response = {
                        "response": "Không tìm thấy vật liệu phù hợp.",
                        "materials": []
                    }
                else:
                    explanation = search_result.get("explanation", "")
                    
                    response_text = f"✅ {explanation}\n\n"
                    
                    # Hiển thị thông báo nếu có Ranking
                    if ranking_summary['ranking_applied']:
                         response_text += f"⭐ **{ranking_summary['boosted_items']} vật liệu** được ưu tiên dựa trên lịch sử.\n\n"
                         
                    response_text += f"🧱 Tìm thấy **{len(materials)} vật liệu** thường dùng:\n\n"
                    
                    for idx, mat in enumerate(materials[:5], 1):
                        response_text += f"{idx}. **{mat['material_name']}**\n"
                        response_text += f"   • Nhóm: {mat['material_group']}\n"
                        response_text += f"   • Giá: {mat.get('price', 0):,.0f} VNĐ/{mat.get('unit', '')}\n"
                        response_text += f"   • Dùng trong {mat.get('usage_count', 0)} sản phẩm\n\n"
                    
                    result_response = {
                        "response": response_text,
                        "materials": materials,
                        "search_method": "cross_table_product_to_material", # Đánh dấu để UI nhận biết
                        "ranking_summary": ranking_summary,   # Truyền xuống UI
                        "can_provide_feedback": True          # Bật nút Feedback
                    }

        



        elif intent == "query_product_materials":
            headcode = params.get("headcode")
            
            if not headcode and context.get("last_search_results"):
                headcode = context["last_search_results"][0]
                
            if not headcode:
                result_response = {
                    "response": "⚠️ Bạn muốn xem vật liệu của sản phẩm nào? Vui lòng cung cấp mã hoặc tìm kiếm sản phẩm trước.",
                    "suggested_prompts": ["🔍 Tìm ghế sofa", "🔍 Tìm bàn ăn"]
                }
            else:
                result_response = get_product_materials(headcode)
                result_count = len(result_response.get("materials", []))
        
        elif intent == "calculate_product_cost":
            headcode = params.get("headcode")
            
            if not headcode and context.get("last_search_results"):
                headcode = context["last_search_results"][0]
            
            if not headcode:
                result_response = {
                    "response": "⚠️ Bạn muốn xem chi phí sản phẩm nào? Vui lòng cung cấp mã hoặc tìm kiếm sản phẩm trước.",
                    "suggested_prompts": ["🔍 Tìm ghế sofa", "🔍 Tìm bàn ăn"]
                }
            else:
                result_response = calculate_product_cost(headcode)
        
        # MATERIAL FLOW
        # elif intent == "search_material":
        #     search_result = search_materials(params)
        #     materials = search_result.get("materials", [])
        #     result_count = len(materials)
            
        #     if not materials:
        #         result_response = {
        #             "response": search_result.get("response", "Không tìm thấy vật liệu phù hợp."),
        #             "materials": []
        #         }
        #     else:
        #         response_text = ""
                
        #         if intent_data.get("is_broad_query"):
        #             follow_up = intent_data.get("follow_up_question", "Bạn cần tìm loại vật liệu cụ thể nào?")
        #             response_text = (
        #                 f"🔎 Tìm thấy **{len(materials)} nguyên vật liệu** phù hợp.\n\n"
        #                 f"💡 **Gợi ý:** {follow_up}"
        #             )
        #         else:
        #             response_text = f"✅ Đã tìm thấy **{len(materials)} nguyên vật liệu** đúng yêu cầu."
                
        #         response_text += "\n\n📦 **KẾT QUẢ:**\n"
        #         for idx, mat in enumerate(materials[:8], 1):
        #             response_text += f"\n{idx}. **{mat['material_name']}**"
        #             response_text += f"\n   • Mã: `{mat['id_sap']}`"
        #             response_text += f"\n   • Nhóm: {mat['material_group']}"
        #             response_text += f"\n   • Giá: {mat.get('price', 0):,.2f} VNĐ/{mat.get('unit', '')}"
        #             if mat.get('image_url'):
        #                 response_text += f"\n   • [📷 Xem ảnh]({mat['image_url']})"
                
        #         if len(materials) > 8:
        #             response_text += f"\n\n*...và {len(materials)-8} vật liệu khác*"
                
        #         suggested_prompts = []
        #         if materials:
        #             first_mat = materials[0]
        #             suggested_prompts = [
        #                 f"🔍 Chi tiết {first_mat['material_name']}",
        #                 "📋 Xem nhóm vật liệu khác"
        #             ]
                
        #         result_response = {
        #             "response": response_text,
        #             "materials": materials,
        #             "suggested_prompts": suggested_prompts
        #         }
        
      
# MATERIAL FLOW - CẬP NHẬT V4.8 (Feedback Ranking)
        elif intent == "search_material":
            search_result = search_materials(params)
            materials = search_result.get("materials", [])
            
            # 🆕 ÁP DỤNG FEEDBACK RANKING
            materials = apply_feedback_to_search(
                materials,
                user_message,
                search_type="material",
                id_key="id_sap"
            )
            
            # 🆕 Lấy ranking summary
            ranking_summary = get_ranking_summary(materials)
            
            result_count = len(materials)
            
            if not materials:
                result_response = {
                    "response": search_result.get("response", "Không tìm thấy vật liệu phù hợp."),
                    "materials": []
                }
            else:
                response_text = ""
                
                if intent_data.get("is_broad_query"):
                    follow_up = intent_data.get("follow_up_question", "Bạn cần tìm loại vật liệu cụ thể nào?")
                    response_text = (
                        f"🔎 Tìm thấy **{len(materials)} nguyên vật liệu** phù hợp.\n\n"
                        f"💖 **Ghi chú:** {follow_up}"
                    )
                else:
                    response_text = f"✅ Đã tìm thấy **{len(materials)} nguyên vật liệu** đúng yêu cầu."
                    
                    # 🆕 Hiển thị ranking info
                    if ranking_summary['ranking_applied']:
                        response_text += f"\n\n⭐ **{ranking_summary['boosted_items']} vật liệu** được ưu tiên."
                
                response_text += "\n\n📦 **KẾT QUẢ:**\n"
                for idx, mat in enumerate(materials[:8], 1):
                    response_text += f"\n{idx}. **{mat['material_name']}**"
                    response_text += f"\n   • Mã: `{mat['id_sap']}`"
                    response_text += f"\n   • Nhóm: {mat['material_group']}"
                    response_text += f"\n   • Giá: {mat.get('price', 0):,.2f} VNĐ/{mat.get('unit', '')}"
                    
                    # 🆕 Hiển thị feedback indicator
                    if mat.get('has_feedback'):
                        response_text += f"\n   ⭐ {mat['feedback_count']} người đã chọn"
                    
                    if mat.get('image_url'):
                        response_text += f"\n   • [📷 Xem ảnh]({mat['image_url']})"
                
                if len(materials) > 8:
                    response_text += f"\n\n*...và {len(materials)-8} vật liệu khác*"
                
                suggested_prompts = []
                if materials:
                    first_mat = materials[0]
                    suggested_prompts = [
                        f"🔍 Chi tiết {first_mat['material_name']}",
                        "📋 Xem nhóm vật liệu khác"
                    ]
                
                result_response = {
                    "response": response_text,
                    "materials": materials,
                    "suggested_prompts": suggested_prompts,
                    "ranking_summary": ranking_summary,  # 🆕
                    "can_provide_feedback": True  # 🆕
                }      

        elif intent == "query_material_detail":
            id_sap = params.get("id_sap")
            material_name = params.get("material_name")
            
            if not id_sap and not material_name and context.get("current_materials"):
                first_mat = context["current_materials"][0]
                id_sap = first_mat.get("id_sap")
            
            if not id_sap and not material_name:
                result_response = {
                    "response": "⚠️ Bạn muốn xem chi tiết vật liệu nào? Vui lòng cung cấp mã SAP hoặc tên vật liệu.",
                    "suggested_prompts": ["🧱 Tìm gỗ sồi", "📋 Danh sách nhóm vật liệu"]
                }
            else:
                result_response = get_material_detail(id_sap=id_sap, material_name=material_name)
                result_count = len(result_response.get("used_in_products", []))
        
        elif intent == "list_material_groups":
            result_response = list_material_groups()
        
        # UNKNOWN
        else:
            result_response = {
                "response": "Tôi chưa hiểu rõ ý bạn. Hãy thử hỏi về sản phẩm hoặc vật liệu!\n\n"
                           "**Ví dụ:**\n"
                           "• \"Tìm bàn ăn tròn\"\n"
                           "• \"Tìm gỗ sồi\"\n"
                           "• \"Tính chi phí sản phẩm B001\"\n"
                           "• \"Xem vật liệu của ghế G002\"",
                "suggested_prompts": [
                    "🔍 Tìm sản phẩm",
                    "🧱 Tìm vật liệu",
                    "📋 Danh sách nhóm vật liệu"
                ]
            }
        
        # Lấy thông tin mở rộng từ kết quả tìm kiếm
        expanded = None
        keywords = []
        
        if intent == "search_product" and result_response.get("data"):
            expanded = result_response["data"].get("expanded_query")
            # Lấy keywords từ params
            if params.get("keywords_vector"):
                keywords = extract_product_keywords(params["keywords_vector"])
        
        save_chat_history(
            msg.session_id,
            user_message,
            result_response.get("response", ""),
            intent,
            params,
            result_count,
            search_type="text",
            expanded_query=expanded,
            extracted_keywords=keywords
        )


        if result_response:
            result_response["query"] = user_message 

        return result_response
    
    except Exception as e:
        print(f"Server Error: {e}")
        import traceback
        traceback.print_exc()
        return {"response": f"⚠️ Lỗi hệ thống: {str(e)}"}

# ========================================
# BATCH OPERATIONS FOR MULTIPLE PRODUCTS
# ========================================

class BatchProductRequest(BaseModel):
    product_headcodes: List[str]
    session_id: str = ""
    operation: str  # "detail", "materials", "cost"

@app.post("/batch/products")
def batch_product_operations(request: BatchProductRequest):
    """
    🔥 Xử lý batch operations cho nhiều sản phẩm
    Operations: detail, materials, cost
    """
    try:
        if not request.product_headcodes:
            return {"response": "⚠️ Vui lòng chọn ít nhất 1 sản phẩm"}
        
        headcodes = request.product_headcodes
        operation = request.operation
        
        print(f"📦 Batch {operation}: {len(headcodes)} products")
        
        # ========== OPERATION: CHI TIẾT SẢN PHẨM ==========
        if operation == "detail":
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            cur.execute("""
                SELECT headcode, product_name, category, sub_category, 
                       material_primary, project, unit
                FROM products
                WHERE headcode = ANY(%s)
                ORDER BY product_name
            """, (headcodes,))
            
            products = cur.fetchall()
            conn.close()
            
            if not products:
                return {"response": "❌ Không tìm thấy sản phẩm"}
            
            response = f"📋 **CHI TIẾT {len(products)} SẢN PHẨM:**\n\n"
            
            for idx, prod in enumerate(products, 1):
                response += f"**{idx}. {prod['product_name']}**\n"
                response += f"   • Mã: `{prod['headcode']}`\n"
                response += f"   • Danh mục: {prod.get('category', 'N/A')}"
                
                if prod.get('sub_category'):
                    response += f" - {prod['sub_category']}"
                
                response += f"\n   • Vật liệu chính: {prod.get('material_primary', 'N/A')}\n"
                
                if prod.get('project'):
                    response += f"   • Dự án: {prod['project']}\n"
                
                response += "\n"
            
            return {
                "response": response,
                "products": [dict(p) for p in products]
            }
        
        # ========== OPERATION: ĐỊNH MỨC VẬT LIỆU ==========
        elif operation == "materials":
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Lấy tất cả vật liệu của các sản phẩm
            cur.execute("""
                SELECT 
                    p.headcode,
                    p.product_name,
                    m.id_sap,
                    m.material_name,
                    m.material_group,
                    m.material_subprice,
                    m.unit,
                    pm.quantity,
                    pm.unit as pm_unit
                FROM product_materials pm
                INNER JOIN products p ON pm.product_headcode = p.headcode
                INNER JOIN materials m ON pm.material_id_sap = m.id_sap
                WHERE p.headcode = ANY(%s)
                ORDER BY p.product_name, m.material_name
            """, (headcodes,))
            
            records = cur.fetchall()
            conn.close()
            
            if not records:
                return {"response": "⚠️ Các sản phẩm này chưa có định mức vật liệu"}
            
            # Group by product
            products_dict = {}
            for rec in records:
                hc = rec['headcode']
                if hc not in products_dict:
                    products_dict[hc] = {
                        'headcode': hc,
                        'product_name': rec['product_name'],
                        'materials': []
                    }
                
                price = get_latest_material_price(rec['material_subprice'])
                qty = float(rec['quantity']) if rec['quantity'] else 0.0
                
                products_dict[hc]['materials'].append({
                    'id_sap': rec['id_sap'],
                    'name': rec['material_name'],
                    'group': rec['material_group'],
                    'quantity': qty,
                    'unit': rec['pm_unit'],
                    'price': price,
                    'total': qty * price
                })
            
            # Tạo response
            response = f"🧱 **ĐỊNH MỨC VẬT LIỆU - {len(products_dict)} SẢN PHẨM:**\n\n"
            
            for prod_data in products_dict.values():
                response += f"### 📦 {prod_data['product_name']} (`{prod_data['headcode']}`)\n\n"
                
                total_cost = sum(m['total'] for m in prod_data['materials'])
                
                for idx, mat in enumerate(prod_data['materials'][:10], 1):
                    response += f"{idx}. **{mat['name']}** ({mat['group']})\n"
                    response += f"   • Số lượng: {mat['quantity']} {mat['unit']}\n"
                    response += f"   • Đơn giá: {mat['price']:,.0f} VNĐ\n"
                    response += f"   • Thành tiền: **{mat['total']:,.0f} VNĐ**\n\n"
                
                if len(prod_data['materials']) > 10:
                    response += f"*...và {len(prod_data['materials'])-10} vật liệu khác*\n\n"
                
                response += f"💰 **Tổng NVL ({prod_data['headcode']}): {total_cost:,.0f} VNĐ**\n\n"
                response += "---\n\n"
            
            # Tạo materials list để UI có thể render cards
            all_materials = []
            for prod_data in products_dict.values():
                all_materials.extend(prod_data['materials'])
            
            return {
                "response": response,
                "products_materials": products_dict,
                "materials": all_materials  # Để UI render material cards
            }
        
        # ========== OPERATION: CHI PHÍ ==========
        elif operation == "cost":
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            cur.execute("""
                SELECT 
                    p.headcode,
                    p.product_name,
                    p.category,
                    m.material_name,
                    m.material_group,
                    m.material_subprice,
                    pm.quantity,
                    pm.unit
                FROM product_materials pm
                INNER JOIN products p ON pm.product_headcode = p.headcode
                INNER JOIN materials m ON pm.material_id_sap = m.id_sap
                WHERE p.headcode = ANY(%s)
                ORDER BY p.product_name
            """, (headcodes,))
            
            records = cur.fetchall()
            conn.close()
            
            if not records:
                return {"response": "⚠️ Không có dữ liệu định mức"}
            
            # Tính chi phí từng sản phẩm
            products_cost = {}
            for rec in records:
                hc = rec['headcode']
                if hc not in products_cost:
                    products_cost[hc] = {
                        'headcode': hc,
                        'name': rec['product_name'],
                        'category': rec['category'],
                        'material_cost': 0.0,
                        'materials_detail': []
                    }
                
                qty = float(rec['quantity']) if rec['quantity'] else 0.0
                price = get_latest_material_price(rec['material_subprice'])
                total = qty * price
                
                products_cost[hc]['material_cost'] += total
                products_cost[hc]['materials_detail'].append({
                    'name': rec['material_name'],
                    'group': rec['material_group'],
                    'quantity': qty,
                    'unit': rec['unit'],
                    'price': price,
                    'total': total
                })
            
            # Response
            response = f"💰 **BÁO CÁO CHI PHÍ - {len(products_cost)} SẢN PHẨM:**\n\n"
            
            grand_total = 0.0
            
            for prod_data in products_cost.values():
                response += f"### 📦 {prod_data['name']} (`{prod_data['headcode']}`)\n"
                response += f"**Danh mục:** {prod_data['category']}\n\n"
                response += f"**Chi phí nguyên vật liệu:** {prod_data['material_cost']:,.0f} VNĐ\n"
                response += f"   • {len(prod_data['materials_detail'])} loại vật liệu\n\n"
                response += "---\n\n"
                
                grand_total += prod_data['material_cost']
            
            response += f"## 💵 TỔNG CHI PHÍ NVL: {grand_total:,.0f} VNĐ\n\n"
            response += "📋 *Chi phí được tính từ giá nguyên vật liệu gần nhất*"
            
            return {
                "response": response,
                "products_cost": products_cost,
                "grand_total": grand_total
            }
        
        else:
            return {"response": "❌ Operation không hợp lệ"}
    
    except Exception as e:
        print(f"❌ Batch operation error: {e}")
        import traceback
        traceback.print_exc()
        return {"response": f"❌ Lỗi: {str(e)}"}
# ========================================
# MODULE 1: CONSOLIDATED BOM REPORT
# ========================================

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils.dataframe import dataframe_to_rows

class ConsolidatedBOMRequest(BaseModel):
    product_headcodes: List[str]
    session_id: str = ""

import re  # <--- Thêm cái này
from io import BytesIO
from typing import List
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment

# --- TỰ ĐỊNH NGHĨA REGEX ĐỂ LỌC KÝ TỰ LỖI ---
# Regex này lọc các ký tự ASCII điều khiển (Control chars) không hợp lệ trong file Excel (XML)
# Bao gồm: ASCII 0-8, 11-12, 14-31
ILLEGAL_CHARACTERS_RE = re.compile(r'[\000-\010]|[\013-\014]|[\016-\037]')

def generate_consolidated_report(product_headcodes: List[str]) -> BytesIO:
    """
    Tạo báo cáo Excel tổng hợp định mức vật tư cho nhiều sản phẩm
    
    Args:
        product_headcodes: Danh sách mã sản phẩm
    
    Returns:
        BytesIO: File Excel buffer
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # 1. LẤY THÔNG TIN SẢN PHẨM
    cur.execute("""
        SELECT headcode, product_name, category, sub_category, project
        FROM products 
        WHERE headcode = ANY(%s)
        ORDER BY product_name
    """, (product_headcodes,))
    
    selected_products = cur.fetchall()
    
    if not selected_products:
        raise ValueError("Không tìm thấy sản phẩm nào")
    
    # 2. LẤY ĐỊNH MỨC CHI TIẾT (Flatten View)
    cur.execute("""
        SELECT 
            p.headcode,
            p.product_name,
            m.id_sap,
            m.material_name,
            m.material_group,
            m.material_subgroup,
            m.unit as material_unit,
            pm.quantity,
            pm.unit as pm_unit,
            m.material_subprice
        FROM product_materials pm
        INNER JOIN products p ON pm.product_headcode = p.headcode
        INNER JOIN materials m ON pm.material_id_sap = m.id_sap
        WHERE p.headcode = ANY(%s)
        ORDER BY p.product_name, m.material_name
    """, (product_headcodes,))
    
    detail_records = cur.fetchall()
    conn.close()
    
    if not detail_records:
        raise ValueError("Các sản phẩm này chưa có định mức vật tư")
    
    # 3. AGGREGATION - GỘP VẬT TƯ
    material_summary = {}
    
    for record in detail_records:
        id_sap = record['id_sap']
        quantity = float(record['quantity']) if record['quantity'] else 0.0
        
        # Parse giá mới nhất
        latest_price = get_latest_material_price(record['material_subprice'])
        
        if id_sap not in material_summary:
            material_summary[id_sap] = {
                'id_sap': id_sap,
                'material_name': record['material_name'],
                'material_group': record['material_group'],
                'material_subgroup': record['material_subgroup'],
                'unit': record['material_unit'],
                'total_quantity': 0.0,
                'unit_price': latest_price,
                'total_cost': 0.0,
                'used_in_products': []
            }
        
        # Cộng dồn số lượng
        material_summary[id_sap]['total_quantity'] += quantity
        material_summary[id_sap]['used_in_products'].append(
            f"{record['product_name']} ({quantity} {record['pm_unit']})"
        )
    
    # Tính thành tiền
    for mat_id, mat_data in material_summary.items():
        mat_data['total_cost'] = mat_data['total_quantity'] * mat_data['unit_price']
    
    # 4. TẠO EXCEL FILE
    wb = Workbook()
    
    # --- SHEET 1: OVERVIEW (Danh sách SP đã chọn) ---
    ws_overview = wb.active
    ws_overview.title = "Overview"
    
    # Header styling
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=12)
    
    # Headers
    overview_headers = ["STT", "Mã SP", "Tên Sản Phẩm", "Danh Mục", "Dự Án"]
    for col_idx, header in enumerate(overview_headers, 1):
        cell = ws_overview.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    
    # Data rows
    for idx, prod in enumerate(selected_products, 1):
        ws_overview.append([
            idx,
            prod['headcode'],
            prod['product_name'],
            f"{prod.get('category', '')} - {prod.get('sub_category', '')}",
            prod.get('project', '')
        ])
    
    # Auto-adjust column width
    for col in ws_overview.columns:
        max_length = max(len(str(cell.value or "")) for cell in col)
        ws_overview.column_dimensions[col[0].column_letter].width = min(max_length + 2, 50)
    
    # --- SHEET 2: MATERIAL SUMMARY (Tổng hợp vật tư) ---
    ws_summary = wb.create_sheet("Material Summary")
    
    summary_headers = [
        "STT", "Mã SAP", "Tên Vật Liệu", "Nhóm", 
        "Nhóm Con", "Đơn Vị", "Tổng SL", "Đơn Giá (VNĐ)", "Thành Tiền (VNĐ)"
    ]
    
    for col_idx, header in enumerate(summary_headers, 1):
        cell = ws_summary.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    
    # Sort by total_cost DESC
    sorted_materials = sorted(
        material_summary.values(), 
        key=lambda x: x['total_cost'], 
        reverse=True
    )
    
    total_cost_all = 0.0
    
    for idx, mat in enumerate(sorted_materials, 1):
        ws_summary.append([
            idx,
            mat['id_sap'],
            mat['material_name'],
            mat['material_group'],
            mat['material_subgroup'],
            mat['unit'],
            round(mat['total_quantity'], 2),
            round(mat['unit_price'], 2),
            round(mat['total_cost'], 2)
        ])
        total_cost_all += mat['total_cost']
    
    # TỔNG CỘNG ROW
    summary_row = ws_summary.max_row + 1
    ws_summary.cell(row=summary_row, column=7, value="TỔNG CỘNG:").font = Font(bold=True)
    ws_summary.cell(row=summary_row, column=9, value=round(total_cost_all, 2)).font = Font(bold=True, color="FF0000")
    
    for col in ws_summary.columns:
        max_length = max(len(str(cell.value or "")) for cell in col)
        ws_summary.column_dimensions[col[0].column_letter].width = min(max_length + 2, 50)
    
    # --- SHEET 3: DETAILS (Chi tiết theo SP) ---
    ws_details = wb.create_sheet("Details")
    
    detail_headers = [
        "Mã SP", "Tên SP", "Mã SAP", "Tên Vật Liệu", 
        "Nhóm VL", "Số Lượng", "Đơn Vị", "Đơn Giá", "Thành Tiền"
    ]
    
    for col_idx, header in enumerate(detail_headers, 1):
        cell = ws_details.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    
    for record in detail_records:
        quantity = float(record['quantity']) if record['quantity'] else 0.0
        unit_price = get_latest_material_price(record['material_subprice'])
        total_cost = quantity * unit_price
        
        ws_details.append([
            record['headcode'],
            record['product_name'],
            record['id_sap'],
            record['material_name'],
            record['material_group'],
            round(quantity, 2),
            record['pm_unit'],
            round(unit_price, 2),
            round(total_cost, 2)
        ])
    
    for col in ws_details.columns:
        max_length = max(len(str(cell.value or "")) for cell in col)
        ws_details.column_dimensions[col[0].column_letter].width = min(max_length + 2, 50)
    
    # 5. SAVE TO BUFFER
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    
    return buffer


@app.post("/report/consolidated")
def create_consolidated_report(request: ConsolidatedBOMRequest):
    """
    📊 API Endpoint tạo báo cáo tổng hợp định mức vật tư
    
    Input: {"product_headcodes": ["B001", "B002", "G001"], "session_id": "..."}
    Output: File Excel (.xlsx)
    """
    try:
        if not request.product_headcodes or len(request.product_headcodes) == 0:
            return {"message": "⚠️ Vui lòng chọn ít nhất 1 sản phẩm"}
        
        print(f"📊 Generating report for {len(request.product_headcodes)} products...")
        
        # Tạo file Excel
        excel_buffer = generate_consolidated_report(request.product_headcodes)
        
        # Lưu lịch sử (Optional)
        if request.session_id:
            save_chat_history(
                session_id=request.session_id,
                user_message=f"[REPORT] Tổng hợp {len(request.product_headcodes)} sản phẩm",
                bot_response="Đã tạo báo cáo Excel",
                intent="generate_report",
                params={"products": request.product_headcodes},
                result_count=len(request.product_headcodes),
                search_type="report"
            )
        
        # Trả file về client
        from fastapi.responses import StreamingResponse
        
        filename = f"BOM_Consolidated_{len(request.product_headcodes)}SP_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return StreamingResponse(
            excel_buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except ValueError as e:
        return {"message": f"❌ {str(e)}"}
    except Exception as e:
        print(f"❌ Report generation error: {e}")
        import traceback
        traceback.print_exc()
        return {"message": f"❌ Lỗi tạo báo cáo: {str(e)}"}


# ========================================
# MODULE 2: ADAPTIVE USER LEARNING
# ========================================

import numpy as np

class TrackingRequest(BaseModel):
    session_id: str
    product_headcode: str
    interaction_type: str  # 'view', 'reject', 'select'

@app.post("/track/view")
def track_product_view(request: TrackingRequest):
    """
    👁️ Track khi user XEM CHI TIẾT sản phẩm (Positive Signal)
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Lấy embedding của sản phẩm
        cur.execute("""
            SELECT description_embedding 
            FROM products 
            WHERE headcode = %s AND description_embedding IS NOT NULL
        """, (request.product_headcode,))
        
        result = cur.fetchone()
        
        if not result:
            conn.close()
            return {"message": "Product not found or no embedding"}
        
        product_vector = result['description_embedding']
        
        # Lưu vào user_preferences
        cur.execute("""
            INSERT INTO user_preferences 
            (session_id, product_headcode, product_vector, interaction_type, weight)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            request.session_id,
            request.product_headcode,
            product_vector,
            'view',
            1.0  # Positive signal
        ))
        
        conn.commit()
        conn.close()
        
        print(f"✅ Tracked VIEW: {request.product_headcode} by {request.session_id[:8]}")
        
        return {"message": "✅ Tracked successfully", "type": "view"}
        
    except Exception as e:
        print(f"❌ Tracking error: {e}")
        return {"message": f"Error: {str(e)}"}


@app.post("/track/reject")
def track_product_reject(request: TrackingRequest):
    """
    ❌ Track khi user BỎ QUA/REJECT sản phẩm (Negative Signal)
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT description_embedding 
            FROM products 
            WHERE headcode = %s AND description_embedding IS NOT NULL
        """, (request.product_headcode,))
        
        result = cur.fetchone()
        
        if not result:
            conn.close()
            return {"message": "Product not found"}
        
        product_vector = result['description_embedding']
        
        cur.execute("""
            INSERT INTO user_preferences 
            (session_id, product_headcode, product_vector, interaction_type, weight)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            request.session_id,
            request.product_headcode,
            product_vector,
            'reject',
            -1.0  # Negative signal
        ))
        
        conn.commit()
        conn.close()
        
        print(f"❌ Tracked REJECT: {request.product_headcode} by {request.session_id[:8]}")
        
        return {"message": "✅ Tracked rejection", "type": "reject"}
        
    except Exception as e:
        print(f"❌ Tracking error: {e}")
        return {"message": f"Error: {str(e)}"}


# PERSONALIZATION - REFACTORED V5.7
# ========================================

def calculate_personalized_score(
    candidate_vector: list, 
    session_id: str
) -> float:
    """
    🎯 V5.7 - Trả về điểm Personalization RIÊNG (0.0 → 1.0)
    KHÔNG trả về final_score, để search_products tổng hợp sau
    
    Returns:
        float: Personal affinity score (0.0 = không khớp, 1.0 = rất khớp)
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Lấy 10 interactions gần nhất
        cur.execute("""
            SELECT product_vector, weight
            FROM user_preferences
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT 10
        """, (session_id,))
        
        history = cur.fetchall()
        conn.close()
        
        if not history:
            return 0.5  # Neutral score khi chưa có history
        
        # Convert candidate sang numpy
        if isinstance(candidate_vector, str):
            candidate_np = np.array(json.loads(candidate_vector), dtype=np.float32)
        else:
            candidate_np = np.array(candidate_vector, dtype=np.float32)
        
        positive_scores = []
        negative_scores = []
        
        for record in history:
            try:
                vec_data = record['product_vector']
                
                if vec_data is None:
                    continue
                    
                # Parse vector
                if isinstance(vec_data, str):
                    hist_vector = np.array(json.loads(vec_data), dtype=np.float32)
                elif isinstance(vec_data, list):
                    hist_vector = np.array(vec_data, dtype=np.float32)
                else:
                    continue
                
                # Check dimension match
                if len(hist_vector) != len(candidate_np):
                    continue
                
                # Cosine Similarity
                norm_product = np.linalg.norm(candidate_np) * np.linalg.norm(hist_vector)
                if norm_product < 1e-8:
                    continue
                    
                similarity = np.dot(candidate_np, hist_vector) / norm_product
                
                # Phân loại theo weight
                if record['weight'] > 0:
                    positive_scores.append(similarity)
                else:
                    negative_scores.append(similarity)
                    
            except Exception:
                continue
        
        # Fallback nếu không có scores hợp lệ
        if not positive_scores and not negative_scores:
            return 0.5
        
        # Tính điểm affinity thuần túy
        positive_affinity = np.mean(positive_scores) if positive_scores else 0.0
        negative_penalty = np.mean(negative_scores) if negative_scores else 0.0
        
        # Formula: Positive boost - Negative penalty
        personal_score = positive_affinity - (negative_penalty * 0.5)
        
        # Clip về [0, 1]
        personal_score = float(np.clip(personal_score, 0.0, 1.0))
        
        return personal_score
        
    except Exception as e:
        print(f"⚠️ Personalization error: {e}")
        return 0.5
# ========================================
# NEW ENDPOINT: USER FEEDBACK
# ========================================

class FeedbackRequest(BaseModel):
    session_id: str
    query: str
    selected_items: List[str]  # List of headcodes hoặc id_sap
    rejected_items: List[str] = []
    search_type: str  # "product" hoặc "material"

@app.post("/feedback")
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
                "message": "✅ Cảm ơn phản hồi của bạn! Kết quả tìm kiếm sẽ được cải thiện.",
                "saved": True
            }
        else:
            return {
                "message": "⚠️ Không thể lưu phản hồi",
                "saved": False
            }
            
    except Exception as e:
        return {
            "message": f"❌ Lỗi: {str(e)}",
            "saved": False
        }




# ========================================
# IMAGE SEARCH
# ========================================

@app.post("/search-image")
async def search_by_image(
    file: UploadFile = File(...),
    session_id: str = Form(default=str(uuid.uuid4()))
):
    """Tìm kiếm theo ảnh"""
    file_path = f"temp_{uuid.uuid4()}.jpg"
    try:
        with open(file_path, "wb") as buffer:
            import shutil
            shutil.copyfileobj(file.file, buffer)
        
        img = Image.open(file_path)
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        prompt = """
        Đóng vai chuyên gia kỹ thuật AA Corporation.
        Phân tích ảnh nội thất này để trích xuất thông tin tìm kiếm Database.
        
        OUTPUT JSON ONLY (no markdown, no backticks):
        {
          "category": "Loại SP (Bàn, Ghế, Sofa...)",
          "visual_description": "Mô tả chi tiết kỹ thuật dùng cho Vector Search",
          "material_detected": "Vật liệu chính (Gỗ, Da, Vải, Đá...)",
          "color_tone": "Màu chủ đạo"
        }
        """
        
        response = model.generate_content([prompt, img])
        
        if not response.text:
            return {
                "response": "⚠️ Không phân tích được ảnh. Vui lòng thử ảnh khác.",
                "products": []
            }
        
        clean = response.text.strip()
        
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        
        try:
            ai_result = json.loads(clean)
        except json.JSONDecodeError as e:
            print(f"JSON Parse Error: {e}")
            ai_result = {
                "visual_description": clean[:200],
                "category": "Nội thất"
            }
        
        params = {
            "category": ai_result.get("category"),
            "keywords_vector": ai_result.get("visual_description"),
            "material_primary": ai_result.get("material_detected")
        }
        
        search_result = search_products(params)
        products = search_result.get("products", [])
        
        save_chat_history(
            session_id=session_id,
            user_message="[IMAGE_UPLOAD]",
            bot_response=f"Phân tích ảnh: {ai_result.get('visual_description', 'N/A')[:100]}... | Tìm thấy {len(products)} sản phẩm",
            intent="search_product",
            params=params,
            result_count=len(products),
            search_type="image",
            expanded_query=ai_result.get("visual_description"),
            extracted_keywords=[
                ai_result.get("category"),
                ai_result.get("material_detected"),
                ai_result.get("color_tone")
            ]
        )

        if not products:
            return {
                "response": f"📋 **Phân tích ảnh:** Tôi nhận thấy đây là **{ai_result.get('visual_description', 'sản phẩm nội thất')}**.\n\n"
                                f"Tuy nhiên, không tìm thấy sản phẩm tương tự trong kho dữ liệu.\n\n"
                        f"💡 **Gợi ý**: Bạn có thể mô tả chi tiết hơn. Hoặc bạn có thể tìm sản phẩm khác. Tôi sẽ gợi ý cho bạn danh sách sản phẩm",
                "products": [],
                "ai_interpretation": ai_result.get("visual_description", "")
            }
        
        return {
            "response": f"📋 **Phân tích ảnh:** Tôi nhận thấy đây là **{ai_result.get('visual_description', 'sản phẩm')}**.\n\n"
                       f"✅ Đã tìm thấy **{len(products)} sản phẩm** tương đồng:",
            "products": products,
            "ai_interpretation": ai_result.get("visual_description", ""),
            "search_method": "image_vector"
        }
    
    except Exception as e:
        print(f"❌ Image search error: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            "response": f"⚠️ Lỗi xử lý ảnh: {str(e)}. Vui lòng thử lại.",
            "products": []
        }
    
    finally:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass

# ========================================
# IMPORT ENDPOINTS
# ========================================
# ========================================
# THÊM VÀO chatbot_api.py
# ========================================

# [1] BATCH CLASSIFICATION FUNCTIONS
# Thêm sau phần AUTO CLASSIFICATION AI (dòng ~100)

def batch_classify_products(products_batch: List[Dict]) -> List[Dict]:
    """
    Phân loại HÀNG LOẠT sản phẩm - 1 API call cho nhiều sản phẩm
    Input: [{'name': 'BÀN GỖ', 'id_sap': 'SP001'}, ...]
    Output: [{'id_sap': 'SP001', 'category': 'Bàn', ...}, ...]
    """
    if not products_batch:
        return []
    
    # [FIX] Đổi sang model ổn định để tránh lỗi Rate Limit của bản Experimental
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    # Tạo danh sách sản phẩm trong prompt
    products_text = ""
    for i, prod in enumerate(products_batch, 1):
        products_text += f"{i}. ID: {prod['id_sap']}, Tên: {prod['name']}\n"
    
    prompt = f"""
Bạn là chuyên gia phân loại sản phẩm nội thất cao cấp.

Phân loại {len(products_batch)} sản phẩm sau:

{products_text}

Mỗi sản phẩm cần phân loại theo:
1. category: Bàn, Ghế, Sofa, Tủ, Giường, Đèn, Kệ, Bàn làm việc, Khác
2. sub_category: Danh mục phụ cụ thể (VD: "Bàn ăn", "Ghế bar", "Sofa góc"...)
3. material_primary: Gỗ, Da, Vải, Kim loại, Đá, Kính, Nhựa, Mây tre, Hỗn hợp

OUTPUT JSON ARRAY ONLY (no markdown, no backticks):
[
  {{"id_sap": "SP001", "category": "...", "sub_category": "...", "material_primary": "..."}},
  {{"id_sap": "SP002", "category": "...", "sub_category": "...", "material_primary": "..."}}
]
"""
    
    # Gọi AI với retry logic
    response_text = call_gemini_with_retry(model, prompt, max_retries=3)
    
    # Fallback mặc định nếu AI lỗi hẳn
    default_results = [{
        'id_sap': p['id_sap'],
        'category': 'Chưa phân loại',
        'sub_category': 'Chưa phân loại',
        'material_primary': 'Chưa xác định'
    } for p in products_batch]

    if not response_text:
        return default_results
    
    try:
        clean = response_text.strip()
        # Xử lý trường hợp Gemini trả về markdown code block
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        
        results = json.loads(clean)
        
        # Đảm bảo số lượng kết quả khớp với input
        if len(results) != len(products_batch):
            print(f"⚠️ Batch size mismatch: expected {len(products_batch)}, got {len(results)}")
            return default_results
        
        return results
        
    except Exception as e:
        print(f"❌ Batch classification parse error: {e}")
        return default_results
def batch_classify_materials(materials_batch: List[Dict]) -> List[Dict]:
    """
    Phân loại HÀNG LOẠT vật liệu
    Input: [{'name': 'GỖ SỒI', 'id_sap': 'M001'}, ...]
    Output: [{'id_sap': 'M001', 'material_group': 'Gỗ', ...}, ...]
    """
    if not materials_batch:
        return []
    
    # [FIX] Đổi sang model gemini-1.5-flash để ổn định hơn và tránh lỗi Rate Limit
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    materials_text = ""
    for i, mat in enumerate(materials_batch, 1):
        materials_text += f"{i}. ID: {mat['id_sap']}, Tên: {mat['name']}\n"
    
    prompt = f"""
        Phân loại {len(materials_batch)} nguyên vật liệu nội thất:

        {materials_text}

        Xác định:
        1. material_group: Gỗ, Da, Vải, Đá, Kim loại, Kính, Nhựa, Sơn, Keo, Phụ kiện, Khác
        2. material_subgroup: Nhóm con cụ thể (VD: "Gỗ tự nhiên", "Da thật", "Vải cao cấp")

        OUTPUT JSON ARRAY ONLY:
        [
        {{"id_sap": "M001", "material_group": "...", "material_subgroup": "..."}},
        {{"id_sap": "M002", "material_group": "...", "material_subgroup": "..."}}
        ]
    """
    
    # Gọi Gemini với retry
    response_text = call_gemini_with_retry(model, prompt, max_retries=3)
    
    # Tạo kết quả mặc định (Fallback) để trả về nếu AI lỗi
    default_results = [{
        'id_sap': m['id_sap'],
        'material_group': 'Chưa phân loại',
        'material_subgroup': 'Chưa phân loại'
    } for m in materials_batch]

    if not response_text:
        return default_results
    
    try:
        clean = response_text.strip()
        # Xử lý làm sạch markdown JSON
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        
        results = json.loads(clean)
        
        # Kiểm tra số lượng kết quả trả về có khớp input không
        if len(results) != len(materials_batch):
            print(f"⚠️ Batch materials mismatch: expected {len(materials_batch)}, got {len(results)}")
            return default_results
        
        return results
        
    except Exception as e:
        print(f"❌ Batch materials classification error: {e}")
        return default_results


# Thay thế 2 endpoints import cũ
# ========================================

@app.post("/import/products")
async def import_products(file: UploadFile = File(...)):
    """
    [V4.1] Import products - KHÔNG auto classify ngay
    Chỉ import vào DB, classify sau qua endpoint riêng
    """
    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))
        
        # Chuẩn hóa tên cột
        df.columns = df.columns.str.strip().str.lower()
        
        required = ['headcode', 'id_sap', 'product_name']
        missing = [col for col in required if col not in df.columns]
        
        if missing:
            return {
                "message": f"❌ Thiếu các cột bắt buộc: {', '.join(missing)}",
                "required_columns": required,
                "your_columns": list(df.columns)
            }
        
        conn = get_db()
        cur = conn.cursor()
        
        imported = 0
        errors = []
        
        for idx, row in df.iterrows():
            try:
                headcode = str(row['headcode']).strip()
                id_sap = str(row['id_sap']).strip()
                product_name = str(row['product_name']).strip()
                
                if not headcode or not id_sap or not product_name:
                    errors.append(f"Row {idx+2}: Missing required fields")
                    continue
                
                # LẤY TRỰC TIẾP từ CSV (nếu có), KHÔNG gọi AI
                category = str(row.get('category', 'Chưa phân loại')).strip() if pd.notna(row.get('category')) else 'Chưa phân loại'
                sub_category = str(row.get('sub_category', 'Chưa phân loại')).strip() if pd.notna(row.get('sub_category')) else 'Chưa phân loại'
                material_primary = str(row.get('material_primary', 'Chưa xác định')).strip() if pd.notna(row.get('material_primary')) else 'Chưa xác định'
                
                unit = str(row.get('unit', '')).strip() if pd.notna(row.get('unit')) else None
                project = str(row.get('project', '')).strip() if pd.notna(row.get('project')) else None
                project_id = str(row.get('project_id', '')).strip() if pd.notna(row.get('project_id')) else None
                
                sql = """
                    INSERT INTO products (
                        headcode, id_sap, product_name, 
                        category, sub_category, material_primary,
                        unit, project, project_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (headcode) DO UPDATE SET
                        product_name = EXCLUDED.product_name,
                        category = EXCLUDED.category,
                        sub_category = EXCLUDED.sub_category,
                        material_primary = EXCLUDED.material_primary,
                        unit = EXCLUDED.unit,
                        project = EXCLUDED.project,
                        project_id = EXCLUDED.project_id,
                        updated_at = NOW()
                """
                
                cur.execute(sql, (
                    headcode, id_sap, product_name,
                    category, sub_category, material_primary,
                    unit, project, project_id
                ))
                
                imported += 1
                
            except Exception as e:
                errors.append(f"Row {idx+2}: {str(e)[:100]}")
        
        conn.commit()
        conn.close()
        
        # Đếm số sản phẩm cần classify
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM products 
            WHERE category = 'Chưa phân loại' 
            OR sub_category = 'Chưa phân loại'
            OR material_primary = 'Chưa xác định'
        """)
        pending_count = cur.fetchone()[0]
        conn.close()
        
        message = f"✅ Import thành công {imported}/{len(df)} products"
        if pending_count > 0:
            message += f"\n\n⏳ Có {pending_count} sản phẩm chưa phân loại."
            message += f"\n💡 Dùng nút '🤖 Auto Classify' trong sidebar để phân loại hàng loạt."
        
        return {
            "message": message,
            "imported": imported,
            "total": len(df),
            "pending_classification": pending_count,
            "errors": errors[:10] if errors else []
        }
        
    except Exception as e:
        return {"message": f"❌ Lỗi: {str(e)}"}


@app.post("/import/materials")
async def import_materials(file: UploadFile = File(...)):
    """
    [V4.1] Import materials - KHÔNG auto classify ngay
    """
    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))
        
        df.columns = df.columns.str.strip().str.lower()
        
        required = ['id_sap', 'material_name', 'material_group']
        missing = [col for col in required if col not in df.columns]
        
        if missing:
            return {
                "message": f"❌ Thiếu các cột bắt buộc: {', '.join(missing)}",
                "required_columns": required,
                "your_columns": list(df.columns)
            }
        
        conn = get_db()
        cur = conn.cursor()
        
        imported = 0
        errors = []
        
        for idx, row in df.iterrows():
            try:
                id_sap = str(row['id_sap']).strip()
                material_name = str(row['material_name']).strip()
                material_group = str(row['material_group']).strip()
                
                if not id_sap or not material_name or not material_group:
                    errors.append(f"Row {idx+2}: Missing required fields")
                    continue
                
                # KHÔNG gọi AI ngay
                material_subgroup = str(row.get('material_subgroup', 'Chưa phân loại')).strip() if pd.notna(row.get('material_subgroup')) else 'Chưa phân loại'
                
                material_subprice = row.get('material_subprice')
                if pd.notna(material_subprice) and isinstance(material_subprice, str):
                    try:
                        json.loads(material_subprice)
                        material_subprice_json = material_subprice
                    except:
                        material_subprice_json = None
                else:
                    material_subprice_json = None
                
                unit = str(row.get('unit', '')).strip() if pd.notna(row.get('unit')) else None
                image_url = str(row.get('image_url', '')).strip() if pd.notna(row.get('image_url')) else None
                
                sql = """
                    INSERT INTO materials (
                        id_sap, material_name, material_group, material_subgroup,
                        material_subprice, unit, image_url
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id_sap) DO UPDATE SET 
                        material_name = EXCLUDED.material_name,
                        material_group = EXCLUDED.material_group,
                        material_subgroup = EXCLUDED.material_subgroup,
                        material_subprice = EXCLUDED.material_subprice,
                        unit = EXCLUDED.unit,
                        image_url = EXCLUDED.image_url,
                        updated_at = NOW()
                """
                
                cur.execute(sql, (
                    id_sap, material_name, material_group, material_subgroup,
                    material_subprice_json, unit, image_url
                ))
                
                imported += 1
                
            except Exception as e:
                errors.append(f"Row {idx+2}: {str(e)[:100]}")
        
        conn.commit()
        conn.close()
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM materials 
            WHERE material_subgroup = 'Chưa phân loại'
        """)
        pending_count = cur.fetchone()[0]
        conn.close()
        
        message = f"✅ Import thành công {imported}/{len(df)} materials"
        if pending_count > 0:
            message += f"\n\n⏳ Có {pending_count} vật liệu chưa phân loại."
            message += f"\n💡 Dùng nút '🤖 Auto Classify Materials' để phân loại."
        
        return {
            "message": message,
            "imported": imported,
            "total": len(df),
            "pending_classification": pending_count,
            "errors": errors[:10] if errors else []
        }
        
    except Exception as e:
        return {"message": f"❌ Lỗi: {str(e)}"}



@app.post("/import/product-materials")
async def import_product_materials(file: UploadFile = File(...)):
    """
    [V4.5] Import định mức - Tự động tạo vật liệu thiếu (Placeholder)
    - Nếu mã vật liệu chưa có trong kho -> Tự động tạo mới để tránh lỗi
    - Fix lỗi đuôi .0
    """
    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))
        
        # Chuẩn hóa tên cột
        df.columns = df.columns.str.strip().str.lower()
        
        required = ['product_headcode']
        missing = [col for col in required if col not in df.columns]
        
        if missing:
            return {
                "message": f"❌ Thiếu cột bắt buộc: {', '.join(missing)}",
                "required_columns": required,
                "your_columns": list(df.columns)
            }
        
        conn = get_db()
        cur = conn.cursor()
        
        imported = 0
        skipped = 0
        auto_created_materials = 0 # Đếm số vật liệu được tạo tự động
        errors = []
        
        # Pre-load dữ liệu để check nhanh
        cur.execute("SELECT headcode FROM products")
        existing_products = {row[0] for row in cur.fetchall()}
        
        cur.execute("SELECT id_sap FROM materials")
        existing_materials = {row[0] for row in cur.fetchall()}

        # Hàm làm sạch ID
        def clean_id(val):
            if pd.isna(val) or val == '':
                return ""
            s = str(val).strip()
            if s.endswith('.0'):
                return s[:-2]
            return s
        
        for idx, row in df.iterrows():
            savepoint_name = f"sp_{idx}"
            cur.execute(f"SAVEPOINT {savepoint_name}")
            
            try:
                # 1. Xử lý Product (Vẫn bắt buộc phải có trước)
                product_headcode = clean_id(row.get('product_headcode'))
                
                if not product_headcode or product_headcode.lower() == 'nan':
                    errors.append(f"Row {idx+2}: Thiếu Product Headcode")
                    continue 

                if product_headcode not in existing_products:
                    # Tùy chọn: Có thể muốn tự tạo Product luôn, nhưng thường Product cần kiểm soát chặt hơn
                    raise ValueError(f"Product '{product_headcode}' chưa có trong hệ thống")

                # 2. Xử lý Material (Tự động tạo nếu thiếu)
                material_id_sap = clean_id(row.get('material_id_sap'))
                
                if not material_id_sap or material_id_sap.lower() == 'nan':
                    skipped += 1
                    cur.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                    continue 

                # --- LOGIC MỚI: TỰ ĐỘNG TẠO VẬT LIỆU NẾU THIẾU ---
                if material_id_sap not in existing_materials:
                    # Tạo vật liệu tạm
                    temp_name = f"Vật liệu mới {material_id_sap}"
                    
                    cur.execute("""
                        INSERT INTO materials (id_sap, material_name, material_group, material_subgroup)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (id_sap) DO NOTHING
                    """, (material_id_sap, temp_name, "Auto-Created", "Chờ cập nhật"))
                    
                    # Cập nhật vào set để các dòng sau không insert lại
                    existing_materials.add(material_id_sap)
                    auto_created_materials += 1
                # --------------------------------------------------

                # 3. Insert vào bảng định mức
                quantity = float(row['quantity']) if pd.notna(row.get('quantity')) else 0
                unit = str(row.get('unit', '')).strip() if pd.notna(row.get('unit')) else None
                
                sql = """
                    INSERT INTO product_materials (product_headcode, material_id_sap, quantity, unit)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (product_headcode, material_id_sap) DO UPDATE SET
                        quantity = EXCLUDED.quantity,
                        unit = EXCLUDED.unit,
                        updated_at = NOW()
                """
                
                cur.execute(sql, (product_headcode, material_id_sap, quantity, unit))
                
                cur.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                imported += 1
                
            except Exception as e:
                cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                errors.append(f"Row {idx+2}: {str(e)}")

        conn.commit()
        conn.close()
        
        msg = f"✅ Import thành công {imported} dòng."
        if auto_created_materials > 0:
            msg += f"\n🆕 Đã tự động tạo mới {auto_created_materials} mã vật liệu (chưa có thông tin)."
        if skipped > 0:
            msg += f"\n⚠️ Bỏ qua {skipped} dòng do không có mã vật liệu."
            
        return {
            "message": msg,
            "imported": imported,
            "auto_created_materials": auto_created_materials,
            "skipped": skipped,
            "total_rows": len(df),
            "errors": errors[:10] if errors else []
        }
        
    except Exception as e:
        return {"message": f"❌ Lỗi hệ thống: {str(e)}"}


# ========================================
# [3] NEW BATCH CLASSIFICATION ENDPOINTS
# Thêm 2 endpoints mới để classify sau khi import
# ========================================

@app.post("/classify-products")
def classify_pending_products():
    """
    🤖 Phân loại HÀNG LOẠT các sản phẩm chưa phân loại
    Batch size: 8 sản phẩm/lần (tránh quá dài response)
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Lấy sản phẩm chưa phân loại
        cur.execute("""
            SELECT headcode, id_sap, product_name 
            FROM products 
            WHERE category = 'Chưa phân loại' 
               OR sub_category = 'Chưa phân loại'
               OR material_primary = 'Chưa xác định'
            LIMIT 100
        """)
        
        pending_products = cur.fetchall()
        
        if not pending_products:
            conn.close()
            return {
                "message": "✅ Tất cả sản phẩm đã được phân loại!",
                "classified": 0,
                "total": 0,
                "remaining": 0
            }
        
        total_pending = len(pending_products)
        classified = 0
        errors = []
        
        BATCH_SIZE = 8  # Gemini xử lý tốt với 5-10 items
        
        for i in range(0, len(pending_products), BATCH_SIZE):
            batch = pending_products[i:i+BATCH_SIZE]
            
            # Chuẩn bị input cho batch classification
            batch_input = [{
                'id_sap': p['id_sap'],
                'name': p['product_name']
            } for p in batch]
            
            print(f"🤖 Classifying batch {i//BATCH_SIZE + 1} ({len(batch)} products)...")
            
            try:
                # GỌI BATCH CLASSIFICATION
                results = batch_classify_products(batch_input)
                
                # Cập nhật vào DB
                for j, result in enumerate(results):
                    try:
                        cur.execute("""
                            UPDATE products 
                            SET category = %s,
                                sub_category = %s,
                                material_primary = %s,
                                updated_at = NOW()
                            WHERE headcode = %s
                        """, (
                            result['category'],
                            result['sub_category'],
                            result['material_primary'],
                            batch[j]['headcode']
                        ))
                        classified += 1
                    except Exception as e:
                        errors.append(f"{batch[j]['headcode']}: {str(e)[:50]}")
                
                conn.commit()
                
                # Delay giữa các batch để tránh rate limit
                if i + BATCH_SIZE < len(pending_products):
                    time.sleep(4)
                
            except Exception as e:
                print(f"❌ Batch {i//BATCH_SIZE + 1} failed: {e}")
                errors.append(f"Batch {i//BATCH_SIZE + 1}: {str(e)[:100]}")
                # Tiếp tục với batch tiếp theo
                continue
        
        conn.close()
        
        # Kiểm tra còn bao nhiêu chưa phân loại
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM products 
            WHERE category = 'Chưa phân loại' 
            OR sub_category = 'Chưa phân loại'
            OR material_primary = 'Chưa xác định'
        """)
        remaining = cur.fetchone()[0]
        conn.close()
        
        return {
            "message": f"✅ Đã phân loại {classified}/{total_pending} sản phẩm",
            "classified": classified,
            "total": total_pending,
            "remaining": remaining,
            "errors": errors[:10] if errors else []
        }
        
    except Exception as e:
        return {
            "message": f"❌ Lỗi: {str(e)}",
            "classified": 0,
            "total": 0,
            "remaining": 0
        }


@app.post("/classify-materials")
def classify_pending_materials():
    """
    🤖 Phân loại HÀNG LOẠT các vật liệu chưa phân loại
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT id_sap, material_name, material_group
            FROM materials 
            WHERE material_subgroup = 'Chưa phân loại'
            LIMIT 100
        """)
        
        pending_materials = cur.fetchall()
        
        if not pending_materials:
            conn.close()
            return {
                "message": "✅ Tất cả vật liệu đã được phân loại!",
                "classified": 0,
                "total": 0,
                "remaining": 0
            }
        
        total_pending = len(pending_materials)
        classified = 0
        errors = []
        
        BATCH_SIZE = 10
        
        for i in range(0, len(pending_materials), BATCH_SIZE):
            batch = pending_materials[i:i+BATCH_SIZE]
            
            batch_input = [{
                'id_sap': m['id_sap'],
                'name': m['material_name']
            } for m in batch]
            
            print(f"🤖 Classifying materials batch {i//BATCH_SIZE + 1} ({len(batch)} items)...")
            
            try:
                results = batch_classify_materials(batch_input)
                
                for j, result in enumerate(results):
                    try:
                        cur.execute("""
                            UPDATE materials 
                            SET material_subgroup = %s,
                                updated_at = NOW()
                            WHERE id_sap = %s
                        """, (
                            result['material_subgroup'],
                            batch[j]['id_sap']
                        ))
                        classified += 1
                    except Exception as e:
                        errors.append(f"{batch[j]['id_sap']}: {str(e)[:50]}")
                
                conn.commit()
                
                if i + BATCH_SIZE < len(pending_materials):
                    time.sleep(4)
                
            except Exception as e:
                print(f"❌ Materials batch {i//BATCH_SIZE + 1} failed: {e}")
                errors.append(f"Batch {i//BATCH_SIZE + 1}: {str(e)[:100]}")
                continue
        
        conn.close()
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM materials 
            WHERE material_subgroup = 'Chưa phân loại'
        """)
        remaining = cur.fetchone()[0]
        conn.close()
        
        return {
            "message": f"✅ Đã phân loại {classified}/{total_pending} vật liệu",
            "classified": classified,
            "total": total_pending,
            "remaining": remaining,
            "errors": errors[:10] if errors else []
        }
        
    except Exception as e:
        return {
            "message": f"❌ Lỗi: {str(e)}",
            "classified": 0,
            "total": 0,
            "remaining": 0
        }





# ========================================
# GENERATE EMBEDDINGS
# ========================================

@app.post("/generate-embeddings")
def generate_product_embeddings():
    """Táº¡o embeddings cho products"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT headcode, product_name, category, sub_category, material_primary
        FROM products 
        WHERE name_embedding IS NULL OR description_embedding IS NULL
        LIMIT 100
    """)
    
    products = cur.fetchall()
    
    if not products:
        conn.close()
        return {"message": "âœ… Táº¥t cáº£ products Ä‘Ã£ cÃ³ embeddings"}
    
    success = 0
    errors = []
    
    for prod in products:
        try:
            name_text = f"{prod['product_name']}"
            name_emb = generate_embedding(name_text)
            
            desc_text = f"{prod['product_name']} {prod.get('category', '')} {prod.get('sub_category', '')} {prod.get('material_primary', '')}"
            desc_emb = generate_embedding(desc_text)
            
            if name_emb and desc_emb:
                cur.execute("""
                    UPDATE products 
                    SET name_embedding = %s, description_embedding = %s, updated_at = NOW()
                    WHERE headcode = %s
                """, (name_emb, desc_emb, prod['headcode']))
                
                success += 1
                time.sleep(0.5)
            
        except Exception as e:
            errors.append(f"{prod['headcode']}: {str(e)[:50]}")
    
    conn.commit()
    conn.close()
    
    return {
        "message": f"âœ… Ä Ã£ táº¡o embeddings cho {success}/{len(products)} products",
        "success": success,
        "total": len(products),
        "errors": errors[:5] if errors else []
    }

@app.post("/generate-material-embeddings")
def generate_material_embeddings():
    """Táº¡o embeddings cho materials"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT id_sap, material_name, material_group, material_subgroup
        FROM materials 
        WHERE name_embedding IS NULL OR description_embedding IS NULL
        LIMIT 100
    """)
    
    materials = cur.fetchall()
    
    if not materials:
        conn.close()
        return {"message": "âœ… Táº¥t cáº£ materials Ä‘Ã£ cÃ³ embeddings"}
    
    success = 0
    errors = []
    
    for mat in materials:
        try:
            name_text = f"{mat['material_name']}"
            name_emb = generate_embedding(name_text)
            
            desc_text = f"{mat['material_name']} {mat.get('material_group', '')} {mat.get('material_subgroup', '')}"
            desc_emb = generate_embedding(desc_text)
            
            if name_emb and desc_emb:
                cur.execute("""
                    UPDATE materials 
                    SET name_embedding = %s, description_embedding = %s, updated_at = NOW()
                    WHERE id_sap = %s
                """, (name_emb, desc_emb, mat['id_sap']))
                
                success += 1
                time.sleep(0.5)
            
        except Exception as e:
            errors.append(f"{mat['id_sap']}: {str(e)[:50]}")
    
    conn.commit()
    conn.close()
    
    return {
        "message": f"âœ… Ä Ã£ táº¡o embeddings cho {success}/{len(materials)} materials",
        "success": success,
        "total": len(materials),
        "errors": errors[:5] if errors else []
    }

# ========================================
# DEBUG ENDPOINTS
# ========================================

@app.get("/debug/products")
def debug_products():
    """Debug info vá»  products"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT COUNT(*) as total FROM products")
    total = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as with_emb FROM products WHERE description_embedding IS NOT NULL")
    with_emb = cur.fetchone()['with_emb']
    
    cur.execute("SELECT category, COUNT(*) as count FROM products GROUP BY category ORDER BY count DESC")
    by_category = cur.fetchall()
    
    conn.close()
    
    return {
        "total_products": total,
        "with_embeddings": with_emb,
        "coverage_percent": round(with_emb / total * 100, 1) if total > 0 else 0,
        "by_category": [dict(c) for c in by_category]
    }

@app.get("/debug/materials")
def debug_materials():
    """Debug info vá»  materials"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT COUNT(*) as total FROM materials")
    total = cur.fetchone()['total']
    
    cur.execute("SELECT COUNT(*) as with_emb FROM materials WHERE description_embedding IS NOT NULL")
    with_emb = cur.fetchone()['with_emb']
    
    cur.execute("SELECT material_group, COUNT(*) as count FROM materials GROUP BY material_group ORDER BY count DESC")
    by_group = cur.fetchall()
    
    conn.close()
    
    return {
        "total_materials": total,
        "with_embeddings": with_emb,
        "coverage_percent": round(with_emb / total * 100, 1) if total > 0 else 0,
        "by_group": [dict(g) for g in by_group]
    }

@app.get("/debug/chat-history")
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

# ========================================
# [4] UPDATE ROOT ENDPOINT
# Cập nhật danh sách endpoints
# ========================================

@app.get("/")
def root():
    return {
        "app": "AA Corporation Chatbot API", 
        "version": "4.1",
        "status": "Running",
        "features": [
            "✅ Queue-based batch classification",
            "✅ Import trước, classify sau",
            "✅ Batch size 8-10 items/call",
            "✅ Tiết kiệm quota Gemini",
            "✅ NULL safety 100%"
        ],
        "endpoints": {
            "chat": "POST /chat",
            "search_image": "POST /search-image",
            "import_products": "POST /import/products",
            "import_materials": "POST /import/materials",
            "import_pm": "POST /import/product-materials",
            "classify_products": "POST /classify-products 🆕",
            "classify_materials": "POST /classify-materials 🆕",
            "generate_embeddings": "POST /generate-embeddings",
            "generate_material_embeddings": "POST /generate-material-embeddings",
            "debug": "GET /debug/products, /debug/materials, /debug/chat-history"
        }
    }

@app.get("/history/{session_id}")
def get_session_history(session_id: str):
    """Xem lịch sử của 1 user - V4.6"""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        sql = """
            SELECT 
                user_message,
                intent,
                search_type,
                expanded_query,
                extracted_keywords,
                result_count,
                created_at
            FROM chat_history
            WHERE session_id = %s
            ORDER BY created_at DESC
            LIMIT 20
        """
        
        cur.execute(sql, (session_id,))
        history = cur.fetchall()
        conn.close()
        
        return {
            "session_id": session_id,
            "total_queries": len(history),
            "history": [dict(h) for h in history]
        }
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)