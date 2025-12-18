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

# ========================================
# CONFIGURATION
# ========================================

DB_CONFIG = {
    "dbname": "db_vector",
    "user": "postgres",
    "password": "postgres",
    "host": "localhost",
    "port": "5432"
}

GEMINI_API_KEY = 
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
# ✨ [MỚI] HYBRID SEARCH FUNCTIONS
# ========================================

def expand_search_query(user_query: str, params: Dict) -> str:
    """AI mở rộng query ngắn thành mô tả chi tiết"""
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    
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
                "keyword_matched": bool(r.get("keyword_match")),
                "total_cost": 0.0  # Khởi tạo, sẽ được tính sau
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

# ========================================
# [NEW] AUTO CLASSIFICATION AI
# ========================================

def auto_classify_product(product_name: str, id_sap: str = "") -> Dict:
    """Tự động phân loại sản phẩm bằng AI"""
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    
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
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    
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

def save_chat_history(session_id: str, user_message: str, bot_response: str, intent: str, params: Dict, result_count: int):
    """Lưu lịch sử chat để học"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        sql = """
            INSERT INTO chat_history 
            (session_id, user_message, bot_response, intent, params, result_count)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        
        cur.execute(sql, (
            session_id, user_message, bot_response, 
            intent, json.dumps(params), result_count
        ))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Lỗi save chat history: {e}")

# ========================================
# HELPER - LẤY GIÁ MỚI NHẤT
# ========================================

def get_latest_material_price(material_subprice_json: str) -> float:
    """Lấy giá mới nhất từ JSON lịch sử giá"""
    if not material_subprice_json:
        return 0.0
    
    try:
        price_history = json.loads(material_subprice_json)
        if not price_history or not isinstance(price_history, list):
            return 0.0
        
        sorted_prices = sorted(
            price_history, 
            key=lambda x: x.get('date', '1900-01-01'), 
            reverse=True
        )
        
        return float(sorted_prices[0].get('price', 0))
    except:
        return 0.0

# ========================================
# HELPER - TÍNH TOTAL COST CHO SẢN PHẨM
# ========================================

def calculate_product_total_cost(headcode: str) -> float:
    """Tính tổng chi phí (total_cost) cho một sản phẩm"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    sql = """
        SELECT 
            m.material_subprice,
            pm.quantity
        FROM product_materials pm
        INNER JOIN materials m ON pm.material_id_sap = m.id_sap
        WHERE pm.product_headcode = %s
    """
    
    try:
        cur.execute(sql, (headcode,))
        materials = cur.fetchall()
    except Exception as e:
        print(f"❌ Query error in calculate_product_total_cost for {headcode}: {e}")
        conn.close()
        return 0.0
    
    conn.close()
    
    if not materials:
        return 0.0
    
    material_cost = 0
    for mat in materials:
        quantity = float(mat['quantity']) if mat['quantity'] else 0.0
        latest_price = get_latest_material_price(mat['material_subprice'])
        material_cost += quantity * latest_price  # Sửa lỗi: cộng dồn material_cost
    
    labor_cost = material_cost * 0.20
    overhead_cost = material_cost * 0.15
    profit_margin = material_cost * 0.25
    
    total_cost = material_cost + labor_cost + overhead_cost + profit_margin
    return total_cost

# ========================================
# INTENT DETECTION
# ========================================

def get_intent_and_params(user_message: str, context: Dict) -> Dict:
    """AI Router với khả năng Reasoning & Soft Clarification"""
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    
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
      "intent": "search_product|query_product_materials|calculate_product_cost|search_material|query_material_detail|list_material_groups|greeting|unknown",
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
# PRODUCT FUNCTIONS
# ========================================

def format_search_results(results):
    """Format results thành cấu trúc chuẩn"""
    products = []
    for row in results:
        product = {
            "headcode": row["headcode"],
            "product_name": row["product_name"],
            "category": row.get("category"),
            "sub_category": row.get("sub_category"),
            "material_primary": row.get("material_primary"),
            "project": row.get("project"),
            "project_id": row.get("project_id"),
            "similarity": round(1 - row["distance"], 3) if "distance" in row else None,
            "total_cost": calculate_product_total_cost(row["headcode"]), 
            "image_url": row.get("image_url")
        }
        products.append(product)
    return products

def search_products(params: Dict):
    """Multi-tier: HYBRID -> Vector -> Keyword"""
    
    # TIER 1: Thử Hybrid trước
    try:
        result = search_products_hybrid(params)
        if result.get("products"):
            # Cập nhật total_cost cho các sản phẩm trong hybrid search
            for product in result["products"]:
                product["total_cost"] = calculate_product_total_cost(product["headcode"])
            return result
    except Exception as e:
        print(f"⚠️ TIER 1 failed: {e}")
    
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
        products = []
        for r in results:
            product = dict(r)
            product["total_cost"] = calculate_product_total_cost(product["headcode"])
            products.append(product)
        
        return {
            "products": products,
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
                       f"Có thể:\n"
                       f"• Sản phẩm mới chưa nhập định mức\n"
                       f"• Chưa import file product_materials.csv\n"
                       f"• Mã sản phẩm trong product_materials không khớp\n\n"
                       f"Vui lòng kiểm tra lại hoặc liên hệ bộ phận kỹ thuật."
        }
    
    total = 0
    materials_with_price = []
    
    for mat in materials:
        latest_price = get_latest_material_price(mat['material_subprice'])
        quantity = float(mat['quantity']) if mat['quantity'] else 0.0  # ✅
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
            'unit_price': latest_price,
            'total_cost': total_cost,
            'price_history': mat['material_subprice']
        })
    
    response = f"📊 **ĐỊNH MỨC VẬT LIỆU: {prod['product_name']}**\n"
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

def calculate_product_cost(headcode: str):
    """Tính TỔNG CHI PHÍ sản phẩm"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT product_name, category FROM products WHERE headcode = %s", (headcode,))
    prod = cur.fetchone()
    
    if not prod:
        conn.close()
        return {"response": f"❌ Không tìm thấy sản phẩm với mã **{headcode}**"}
    
    sql = """
        SELECT 
            m.material_subprice,
            pm.quantity
        FROM product_materials pm
        INNER JOIN materials m ON pm.material_id_sap = m.id_sap
        WHERE pm.product_headcode = %s
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
                       f"2. Import lại file qua sidebar: **Import Dữ Liệu → Định Mức**\n"
                       f"3. Liên hệ bộ phận kỹ thuật để cập nhật định mức"
        }
    
    material_cost = 0
    material_count = len(materials)
    
    for mat in materials:
        quantity = float(mat['quantity']) if mat['quantity'] else 0.0  # ✅ Cast sang float
        latest_price = get_latest_material_price(mat['material_subprice'])
        material_cost += quantity * latest_price  # SỬA LỖI: Cộng dồn material_cost

    labor_cost = material_cost * 0.20
    overhead_cost = material_cost * 0.15
    profit_margin = material_cost * 0.25
    
    total_cost = material_cost + labor_cost + overhead_cost + profit_margin
    
    response = f"""
💰 **BÁO GIÁ TỔNG THỂ - SẢN PHẨM**

📦 **Sản phẩm:** {prod['product_name']}
🏷️ **Mã:** `{headcode}`
📂 **Danh mục:** {prod['category'] or 'N/A'}

---

**CHI TIẾT CHI PHÍ:**

1. 🧱 **Nguyên vật liệu:** {material_cost:,.2f} VNĐ
   _(Gồm {material_count} loại vật liệu)_

2. 👷 **Nhân công (20%):** {labor_cost:,.2f} VNĐ
   _(Gia công, lắp ráp, hoàn thiện)_

3. 🏭 **Chi phí chung (15%):** {overhead_cost:,.2f} VNĐ
   _(Điện nước, khấu hao máy móc, quản lý)_

4. 📈 **Lợi nhuận (25%):** {profit_margin:,.2f} VNĐ

---

✅ **Tổng chi phí dự kiến:** **{total_cost:,.2f} VNĐ**

---

**📋 LƯU Ý:**
• Đây là chi phí ước tính dựa trên định mức hiện tại
• Giá thực tế có thể thay đổi tùy:
  - Số lượng đặt hàng (giảm giá theo volume)
  - Yêu cầu kỹ thuật đặc biệt
  - Biến động giá nguyên vật liệu thị trường
  - Thời gian giao hàng

💡 **Muốn xem chi tiết vật liệu?** 
   Hỏi: _"Phân tích vật liệu {headcode}"_ hoặc _"Định mức {headcode}"_
"""
    
    return {
        "response": response,
        "cost_breakdown": {
            "material_cost": material_cost,
            "labor_cost": labor_cost,
            "overhead_cost": overhead_cost,
            "profit_margin": profit_margin,
            "total_cost": total_cost,
            "material_count": material_count
        },
        "total_cost": total_cost  # Thêm total_cost vào response
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
                    mat_dict['price'] = get_latest_material_price(mat['material_subprice'])
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
    
    response = f"""
🧱 **CHI TIẾT NGUYÊN VẬT LIỆU**

📦 **Tên:** {material['material_name']}
🏷️ **Mã SAP:** `{material['id_sap']}`
📂 **Nhóm:** {material['material_group']}"""
    
    if material.get('material_subgroup'):
        response += f" - {material['material_subgroup']}"
    
    response += f"""
💰 **Giá mới nhất:** {latest_price:,.2f} VNĐ/{material['unit']}

---

📊 **THỐNG KÊ SỬ DỤNG:**
• Được sử dụng trong **{stats['product_count']} sản phẩm**
• Xuất hiện ở **{stats['project_count']} dự án**
• Tổng số lượng: **{stats.get('total_quantity', 0) or 0} {material['unit']}**

---
"""
    
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
        "material_detail": dict(material),
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
        elif intent == "search_product":
            search_result = search_products(params)
            products = search_result.get("products", [])
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
                    suggested_prompts = [
                        f"💰 Tính chi phí {products[0]['headcode']}",
                        f"📋 Xem vật liệu {products[0]['headcode']}"
                    ]
                
                # Đảm bảo mỗi sản phẩm có total_cost
                for product in products:
                    if "total_cost" not in product or product["total_cost"] == 0:
                        product["total_cost"] = calculate_product_total_cost(product["headcode"])
                
                result_response = {
                    "response": response_text,
                    "products": products,
                    "suggested_prompts": suggested_prompts
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
        elif intent == "search_material":
            search_result = search_materials(params)
            materials = search_result.get("materials", [])
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
                        f"💡 **Gợi ý:** {follow_up}"
                    )
                else:
                    response_text = f"✅ Đã tìm thấy **{len(materials)} nguyên vật liệu** đúng yêu cầu."
                
                response_text += "\n\n📦 **KẾT QUẢ:**\n"
                for idx, mat in enumerate(materials[:8], 1):
                    response_text += f"\n{idx}. **{mat['material_name']}**"
                    response_text += f"\n   • Mã: `{mat['id_sap']}`"
                    response_text += f"\n   • Nhóm: {mat['material_group']}"
                    response_text += f"\n   • Giá: {mat.get('price', 0):,.2f} VNĐ/{mat.get('unit', '')}"
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
                    "suggested_prompts": suggested_prompts
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
                "response": "Tôi chưa hiểu rõ ý bạn. Hãy thử hỏi về sản phẩm hoặc vật liệu nhé!\n\n"
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
        
        # Lưu chat history
        save_chat_history(
            msg.session_id,
            user_message,
            result_response.get("response", ""),
            intent,
            params,
            result_count
        )
        
        return result_response
    
    except Exception as e:
        print(f"Server Error: {e}")
        import traceback
        traceback.print_exc()
        return {"response": f"⚠️ Lỗi hệ thống: {str(e)}"}

# ========================================
# IMAGE SEARCH
# ========================================

@app.post("/search-image")
async def search_by_image(file: UploadFile = File(...)):
    """Tìm kiếm theo ảnh"""
    file_path = f"temp_{uuid.uuid4()}.jpg"
    try:
        with open(file_path, "wb") as buffer:
            import shutil
            shutil.copyfileobj(file.file, buffer)
        
        img = Image.open(file_path)
        model = genai.GenerativeModel("gemini-2.5-flash-lite")
        
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
        
        if not products:
            return {
                "response": f"📸 **Phân tích ảnh:** Tôi nhận thấy đây là **{ai_result.get('visual_description', 'sản phẩm nội thất')}**.\n\n"
                            f"Tuy nhiên, không tìm thấy sản phẩm tương tự trong kho dữ liệu.\n\n"
                            f"💡 Gợi ý: Thử mô tả bằng từ khóa hoặc upload ảnh rõ hơn.",
                "products": [],
                "ai_interpretation": ai_result.get("visual_description", "")
            }
        
        return {
            "response": f"📸 **Phân tích ảnh:** Tôi nhận thấy đây là **{ai_result.get('visual_description', 'sản phẩm')}**.\n\n"
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

def batch_classify_products(products_batch: List[Dict]) -> List[Dict]:
    """
    Phân loại HÀNG LOẠT sản phẩm - 1 API call cho nhiều sản phẩm
    Input: [{'name': 'BÀN GỖ', 'id_sap': 'SP001'}, ...]
    Output: [{'id_sap': 'SP001', 'category': 'Bàn', ...}, ...]
    """
    if not products_batch:
        return []
    
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    
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
    
    response_text = call_gemini_with_retry(model, prompt, max_retries=3)
    
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
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        
        results = json.loads(clean)
        
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
    
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    
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
    
    response_text = call_gemini_with_retry(model, prompt, max_retries=3)
    
    default_results = [{
        'id_sap': m['id_sap'],
        'material_group': 'Chưa phân loại',
        'material_subgroup': 'Chưa phân loại'
    } for m in materials_batch]

    if not response_text:
        return default_results
    
    try:
        clean = response_text.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        
        results = json.loads(clean)
        
        if len(results) != len(materials_batch):
            print(f"⚠️ Batch materials mismatch: expected {len(materials_batch)}, got {len(results)}")
            return default_results
        
        return results
        
    except Exception as e:
        print(f"❌ Batch materials classification error: {e}")
        return default_results

@app.post("/import/products")
async def import_products(file: UploadFile = File(...)):
    """
    [V4.1] Import products - KHÔNG auto classify ngay
    Chỉ import vào DB, classify sau qua endpoint riêng
    """
    try:
        contents = await file.read()
        df = pd.read_csv(io.BytesIO(contents))
        
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
        auto_created_materials = 0
        errors = []
        
        cur.execute("SELECT headcode FROM products")
        existing_products = {row[0] for row in cur.fetchall()}
        
        cur.execute("SELECT id_sap FROM materials")
        existing_materials = {row[0] for row in cur.fetchall()}

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
                product_headcode = clean_id(row.get('product_headcode'))
                
                if not product_headcode or product_headcode.lower() == 'nan':
                    errors.append(f"Row {idx+2}: Thiếu Product Headcode")
                    continue 

                if product_headcode not in existing_products:
                    raise ValueError(f"Product '{product_headcode}' chưa có trong hệ thống")

                material_id_sap = clean_id(row.get('material_id_sap'))
                
                if not material_id_sap or material_id_sap.lower() == 'nan':
                    skipped += 1
                    cur.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                    continue 

                if material_id_sap not in existing_materials:
                    temp_name = f"Vật liệu mới {material_id_sap}"
                    
                    cur.execute("""
                        INSERT INTO materials (id_sap, material_name, material_group, material_subgroup)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (id_sap) DO NOTHING
                    """, (material_id_sap, temp_name, "Auto-Created", "Chờ cập nhật"))
                    
                    existing_materials.add(material_id_sap)
                    auto_created_materials += 1
                
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
# BATCH CLASSIFICATION ENDPOINTS
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
        
        BATCH_SIZE = 8
        
        for i in range(0, len(pending_products), BATCH_SIZE):
            batch = pending_products[i:i+BATCH_SIZE]
            
            batch_input = [{
                'id_sap': p['id_sap'],
                'name': p['product_name']
            } for p in batch]
            
            print(f"🤖 Classifying batch {i//BATCH_SIZE + 1} ({len(batch)} products)...")
            
            try:
                results = batch_classify_products(batch_input)
                
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
                
                if i + BATCH_SIZE < len(pending_products):
                    time.sleep(4)
                
            except Exception as e:
                print(f"❌ Batch {i//BATCH_SIZE + 1} failed: {e}")
                errors.append(f"Batch {i//BATCH_SIZE + 1}: {str(e)[:100]}")
                continue
        
        conn.close()
        
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
        return {"message": "✅ Tất cả products đã có embeddings"}
    
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
        "message": f"✅ Đã tạo embeddings cho {success}/{len(products)} products",
        "success": success,
        "total": len(products),
        "errors": errors[:5] if errors else []
    }

@app.post("/generate-material-embeddings")
def generate_material_embeddings():
    
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
        return {"message": "✅ Tất cả materials đã có embeddings"}
    
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
        "message": f"✅ Đã tạo embeddings cho {success}/{len(materials)} materials",
        "success": success,
        "total": len(materials),
        "errors": errors[:5] if errors else []
    }

# ========================================
# DEBUG ENDPOINTS
# ========================================

@app.get("/debug/products")
def debug_products():
    
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
# UPDATE ROOT ENDPOINT
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
            "✅ NULL safety 100%",
            "✅ Thêm total_cost vào response sản phẩm"
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)