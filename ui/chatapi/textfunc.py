from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict
from psycopg2.extras import RealDictCursor
import google.generativeai as genai
import uuid
import time
import json
from PIL import Image
import os
import re
import pandas as pd
import io
import psycopg2
from config import settings
from .embeddingapi import generate_embedding

def get_db():
    return psycopg2.connect(**settings.DB_CONFIG)

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
        print(f"INFO: Keywords => {keywords}")
    return keywords

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
    
    print(f"INFO: Cross-table search: Materials for '{product_query}'")
    
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
            FROM products_gemi
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
        
        print(f"SUCCESS: Found {len(product_headcodes)} matching products: {product_names[:3]}")
        
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
            FROM materials_gemi m
            INNER JOIN product_materials pm ON m.id_sap = pm.material_id_sap
            INNER JOIN products p ON pm.product_headcode = p.headcode
            WHERE p.headcode = ANY(%s)
            {material_filter}
            GROUP BY m.id_sap, m.material_name, m.material_group, m.material_subgroup, m.material_subprice, m.unit, m.image_url
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
            materials_with_context.append(mat_dict)
        
        print(f"SUCCESS: Found {len(materials_with_context)} materials used in these products")
        
        return {
            "materials": materials_with_context,
            "search_method": "cross_table_product_to_material",
            "matched_products": product_names[:5],
            "explanation": f"Vật liệu thường dùng cho: {', '.join(product_names[:3])}"
        }
        
    except Exception as e:
        print(f"ERROR: Cross-table materials search failed: {e}")
        conn.close()
        return {"materials": [], "search_method": "cross_table_error"}

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
        return 0.90  

def format_search_results(results):
    """Format results thành cấu trúc chuẩn"""
    products = []
    for row in results:
        products.append({
            "headcode": row["headcode"],
            "product_name": row["product_name"],
            "category": row.get("category"),
            "sub_category": row.get("sub_category"),
            "material_primary": row.get("material_primary"),
            "project": row.get("project"),
            "project_id": row.get("project_id"),
            "similarity": round(1 - row["distance"], 3) if "distance" in row else None
        })
    return products

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
                print(f"INFO: Quota exceeded. Đợi {wait_time}s...")
                time.sleep(wait_time)
                continue
            print(f"ERROR Gemini: {e}")
            return None
    return None

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
        print(f"ERROR: Query error in calculate_product_total_cost for {headcode}: {e}")
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
    
    # print(f"\n🔍 Query: {base}")
    
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
            FROM products_gemi
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
            
            print(f"SUCCESS: Found {len(products)} products (Hybrid)")
            conn.close()
            return {
                "products": products,
                "search_method": "hybrid_vector_keyword",
                "expanded_query": expanded
            }
    except Exception as e:
        print(f"ERROR Hybrid failed: {e}")
    
    conn.close()
    return {"products": [], "search_method": "hybrid_failed"}

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
            print(f"Expanded: '{user_query}' -> '{response[:80]}...'")
            return response.strip()
    except:
        pass
    return user_query

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
        sql = f"SELECT * FROM products_gemi WHERE {where_clause} LIMIT 12"
    else:
        sql = "SELECT * FROM products_gemi ORDER BY RANDOM() LIMIT 10"
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
        
        print(f"SUCCESS: TIER 3 => Found {len(results)} products")
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
        print(f"ERROR: TIER 3 failed: {e}")
        return {
            "response": "Lỗi tìm kiếm.",
            "products": []
        }
