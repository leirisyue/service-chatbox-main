
import json
from typing import Dict
from config import settings
from fastapi import APIRouter
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
from historiesapi import histories
from feedbackapi.feedback import get_feedback_boost_for_query
from rankingapi.ranking import rerank_with_feedback,get_ranking_summary,apply_feedback_to_search
from historiesapi.histories import router as history_router
from imageapi.media import router as media_router
from .textfunc import format_search_results,calculate_product_total_cost,get_latest_material_price,extract_product_keywords,call_gemini_with_retry, search_products_hybrid, search_products_keyword_only
from .unit import ChatMessage
from .embeddingapi import generate_embedding_qwen
from prettytable import PrettyTable

def get_db():
    return psycopg2.connect(**settings.DB_CONFIG)

genai.configure(api_key=settings.My_GOOGLE_API_KEY)

router = APIRouter()
# ========================================
# FUNCTION DEFINITIONS
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
            -> Tạo `follow_up_question`: Ba câu hỏi ngắn gợi ý user thu hẹp phạm vi
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
        print(f"WARNING: TIER 1 failed: {e}")
    
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

    query_vector = generate_embedding_qwen(query_text)
    
    if not query_vector:
        conn.close()
        return search_products_keyword_only(params)
    
    # TIER 2: Pure Vector
    try:
        sql = """
            SELECT headcode, product_name, category, sub_category, 
                    material_primary, project, project_id,
                    (description_embedding <=> %s::vector) as distance
            FROM products_qwen
            WHERE description_embedding IS NOT NULL
            ORDER BY distance ASC
            LIMIT 10
        """
        
        cur.execute(sql, [query_vector])
        results = cur.fetchall()
        
        if results:
            print(f"SUCCESS: TIER 2: {len(results)} products")
            products = format_search_results(results[:8])
            conn.close()
            return {"products": products, "search_method": "vector_no_filter"}
    except Exception as e:
        print(f"WARNING: TIER 2 failed: {e}")
    
    # TIER 3: Keyword
    conn.close()
    return search_products_keyword_only(params)




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
    
    print(f"INFO: Cross-table search: Products made from '{material_query}'")
    
    # Bước 1: Tìm vật liệu phù hợp
    material_vector = generate_embedding_qwen(material_query)
    
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
            FROM materials_qwen
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
        
        print(f"SUCCESS: Found {len(material_ids)} matching materials: {material_names[:3]}")
        
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
            FROM products_qwen p
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
        
        print(f"SUCCESS: Found {len(products_list)} products using these materials")
        
        return {
            "products": products_list[:10],
            "search_method": "cross_table_material_to_product",
            "matched_materials": material_names,
            "explanation": f"Tìm thấy sản phẩm sử dụng: {', '.join(material_names[:3])}"
        }
        
    except Exception as e:
        print(f"ERROR: Cross-table search failed: {e}")
        conn.close()
        return {"products": [], "search_method": "cross_table_error"}


def get_product_materials(headcode: str):
    """Lấy danh sách vật liệu của SẢN PHẨM"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT product_name FROM products_qwen WHERE headcode = %s", (headcode,))
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
        print(f"INFO: Found {len(materials)} materials for {headcode}")
    except Exception as e:
        print(f"ERROR: Query error: {e}")
        conn.close()
        return {"response": f"Lỗi truy vấn database: {str(e)}"}
    
    conn.close()
    
    if not materials:
        return {
            "response": f"WARNING: Sản phẩm **{prod['product_name']}** ({headcode}) chưa có định mức vật liệu.\n\n"
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
    """Tính CHI PHÍ NGUYÊN VẬT LIỆU sản phẩm (Đơn giản hóa V4.7)"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT product_name, category FROM products_qwen WHERE headcode = %s", (headcode,))
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
            pm.unit as pm_unit,
            m.image_url,
            m.id_sap
        FROM product_materials pm
        INNER JOIN materials m ON pm.material_id_sap = m.id_sap
        WHERE pm.product_headcode = %s
        ORDER BY m.material_name ASC
    """
    try:
        cur.execute(sql, (headcode,))
        materials = cur.fetchall()
        print(f"INFO: Cost calculation for {headcode}: {len(materials)} materials")
    except Exception as e:
        print(f"ERROR: Query error: {e}")
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
            'material_name': mat['material_name'],
            'material_group': mat['material_group'],
            'quantity': quantity,
            'unit': mat['pm_unit'],
            'unit_price': latest_price,
            'total_cost': total_cost,
            'image_url': mat['image_url'],
            'id_sap': mat['id_sap']
        })
    
    # ✅ RESPONSE ĐƠN GIẢN - CHỈ CHI PHÍ VẬT LIỆU
    response = f"**BÁO GIÁ NGUYÊN VẬT LIỆU**\n"
    response += f"📦 **Sản phẩm:** {prod['product_name']}\n"
    response += f"🏷️ **Mã:** `{headcode}`\n"
    response += f"📂 **Danh mục:** {prod['category'] or 'N/A'}\n"
    response += f"---\n"
    response += f"**CHI TIẾT NGUYÊN VẬT LIỆU ({material_count} loại):**\n"
    
    for idx, mat in enumerate(materials_detail[:15], 1):
        response += f"{idx}. **{mat['material_name']}** ({mat['material_group']})\n"
        response += f"   • Số lượng: {mat['quantity']} {mat['unit']}\n"
        response += f"   • Đơn giá: {mat['unit_price']:,.0f} VNĐ\n"
        response += f"   • Thành tiền: **{mat['total_cost']:,.0f} VNĐ**\n\n"
    
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
        "materials": materials_detail
    }


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
    
    query_vector = generate_embedding_qwen(query_text)
    
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
                FROM materials_qwen
                WHERE description_embedding IS NOT NULL AND {filter_clause}
                ORDER BY distance ASC
                LIMIT 10
            """

            cur.execute(sql, [query_vector] + filter_params)
            results = cur.fetchall()
            
            if results:
                print(f"SUCCESS: Vector search: Found {len(results)} materials")
                
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
            print(f"WARNING: Vector search failed: {e}")
    
    print("INFO: Keyword search for materials")
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
        sql = f"SELECT * FROM materials_qwen WHERE {where_clause} LIMIT 15"
    else:
        sql = "SELECT * FROM materials_qwen ORDER BY material_name ASC LIMIT 10"
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
        
        print(f"SUCCESS: Keyword search: Found {len(materials_with_price)} materials")
        return {
            "materials": materials_with_price,
            "search_method": "keyword"
        }
    except Exception as e:
        conn.close()
        print(f"ERROR: Material search failed: {e}")
        return {
            "response": "Lỗi tìm kiếm vật liệu.",
            "materials": []
        }


def get_material_detail(id_sap: str = None, material_name: str = None):
    """Xem chi tiết VẬT LIỆU + lịch sử giá + sản phẩm sử dụng"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    if id_sap:
        cur.execute("SELECT * FROM materials_qwen WHERE id_sap = %s", (id_sap,))
    elif material_name:
        cur.execute("SELECT * FROM materials_qwen WHERE material_name ILIKE %s LIMIT 1", (f"%{material_name}%",))
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
        print(f"INFO: Material {material['id_sap']} used in {len(used_in_products)} products")
    except Exception as e:
        print(f"ERROR: Query error: {e}")
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
        print(f"ERROR: Stats query error: {e}")
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
        FROM materials_qwen
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
# API ENDPOINTS
# ========================================

@router.post("/chat")
def chat(msg: ChatMessage):
    """Main chat logic"""
    try:
        user_message = msg.message
        context = msg.context or {}
        
        intent_data = get_intent_and_params(user_message, context)
        # print(f"\n🤖 Detected intent: {intent_data}")
        
        if intent_data.get("intent") == "error":
            return {"response": "Xin lỗi, hệ thống đang bận. Vui lòng thử lại."}
        
        intent = intent_data["intent"]
        params = intent_data.get("params", {})
        
        result_response = None
        result_count = 0
        
        listProducts = []
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
        
        elif intent == "search_product":
            search_result = search_products(params)
            # print(f"🔍 Search result: {search_result}")
            products = search_result.get("products", [])
            
            # ✅ THÊM: Áp dụng feedback ranking
            products = apply_feedback_to_search(
                products, 
                user_message,
                search_type="product",
                id_key="headcode"
            )
            
            # ✅ THÊM: Lấy ranking summary
            ranking_summary = get_ranking_summary(products)
            
            result_count = len(products)
            
            if not products:
                result_response = {
                    "response": f'🔍 Đã tìm thấy sản phẩm: **"{search_result.get("response", "Không tìm thấy vật liệu phù hợp.")}"**.\n\n'
                                '**Gợi ý cho bạn:**\n'
                                '• Thử tìm kiếm với từ khóa khác (ví dụ: "bàn ăn" thay vì "bàn bếp")\n'
                                '• Mô tả chi tiết hơn về mục đích sử dụng\n'
                                '• Hoặc để tôi gợi ý các danh mục phổ biến',
                    "suggested_prompts": [
                        "Bàn làm việc văn phòng",
                        "Ghế sofa phòng khách",
                        "Tủ bếp hiện đại",
                        "Xem tất cả sản phẩm nổi bật"
                    ]
                }
            else:
                response_text = ""
                suggested_prompts = []
                
                if intent_data.get("is_broad_query"):
                    follow_up = intent_data.get("follow_up_question", "Bạn muốn tìm loại cụ thể nào?")
                    response_text = (
                        f"🎯 **TÌM KIẾM MỞ RỘNG**\n"
                        f"Tôi tìm thấy **{len(products)} sản phẩm** liên quan đến \"{user_message}\".\n\n"
                        f"💡 **{follow_up}**\n\n"
                        f"Dưới đây là một số lựa chọn phổ biến dành cho bạn:"
                    )
                    actions = intent_data.get("suggested_actions", [])
                    suggested_prompts = [f"🔍 {a}" for a in actions] if actions else []
                    suggested_prompts.extend([
                        "💰 Xem báo giá chi tiết",
                        "🎨 Tư vấn phối màu",
                        "📏 Yêu cầu kích thước tùy chỉnh"
                    ])
                else:
                    response_text = (
                        f"✅ **KẾT QUẢ TÌM KIẾM CHUYÊN SÂU**\n"
                        f"Tôi đã chọn lọc **{len(products)}** phù hợp nhất với yêu cầu của bạn.\n\n"
                    )
                    
                    # ✅ THÊM: Hiển thị thông tin ranking nếu có
                    if ranking_summary['ranking_applied']:
                        response_text += f"\n\n⭐ **{ranking_summary['boosted_items']} sản phẩm** được ưu tiên dựa trên lịch sử tìm kiếm."
                    
                    response_text += "\n**Bảng tóm tắt các vật liệu:**\n"
                    table = PrettyTable()
                    table.field_names = [
                        "STT",
                        "Tên vật liệu",
                        "Mã SAP",
                        "Nhóm",
                        "Giá (VNĐ/ĐV)",
                        "Phản hồi"
                    ]

                    table.align = {
                        "Tên vật liệu": "l",
                        "Mã SAP": "l",
                        "Nhóm": "l",
                        "Giá (VNĐ/ĐV)": "r",
                        "Phản hồi": "c"
                    }

                    for idx, mat in enumerate(materials, 1):
                        price = f"{mat.get('price', 0):,.2f} / {mat.get('unit', '')}"
                        material_name = mat["material_name"]
                        feedback = (
                            f"{mat['feedback_count']} lượt"
                            if mat.get("has_feedback")
                            else "-"
                        )
                        table.add_row([
                            idx,
                            material_name,
                            mat["id_sap"],
                            mat["material_group"],
                            price,
                            feedback
                        ])
                    response_text += (
                        "\n📦 **DANH SÁCH VẬT LIỆU ƯU TIÊN**\n"
                        "```\n"
                        f"{table}\n"
                        "```\n"
                    )
                    
                    # Thêm phần link hình ảnh riêng (ngoài bảng)
                    materials_with_images = [m for m in materials[:3] if m.get('image_url')]
                    if materials_with_images:
                        response_text += "\n**📷 XEM ẢNH MẪU:**\n"
                        for mat in materials_with_images:
                            response_text += f"• [{mat['material_name']}]({mat.get('image_url', '#')})\n"
                    
                    
                    response_text += (
                        f"**Các vật :**\n"
                        f"• Các sản phẩm được liệt kê dưới đây đều đáp ứng yêu cầu về sản phẩm\n"
                        f"• Nếu cần thay đổi tiêu chí (màu sắc, kích thước, chất liệu), hãy cho tôi biết\n"
                        f"• Tôi có thể tư vấn thêm về phong cách thiết kế phù hợp\n\n"
                        f"**Bạn muốn:**"
                    )
                    suggested_prompts = [
                        f"💰 Phân tích chi phí {products[0]['headcode']}",
                        f"🧱 Xem cấu tạo vật liệu {products[0]['headcode']}",
                        f"🎯 So sánh với sản phẩm tương tự",
                        "📞 Kết nối với chuyên viên tư vấn"
                    ]
                result_response = {
                    "response": response_text,
                    "products": products,
                    "suggested_prompts": suggested_prompts,
                    "ranking_summary": ranking_summary,  
                    "can_provide_feedback": True 
                }
            
        elif intent == "search_product_by_material":
            material_query = params.get("material_name") or params.get("material_primary") or params.get("keywords_vector")
            
            if not material_query:
                result_response = {
                    "response": "🎯 **TÌM SẢN PHẨM THEO VẬT LIỆU**\n\n"
                                "Để tôi tư vấn sản phẩm phù hợp, vui lòng cho biết:\n"
                                "• Bạn quan tâm đến vật liệu nào? (gỗ, đá, kim loại...)\n"
                                "• Sản phẩm dùng cho không gian nào?\n"
                                "• Ngân sách dự kiến là bao nhiêu?",
                    "suggested_prompts": [
                        "Sản phẩm làm từ gỗ sồi tự nhiên",
                        "Nội thất kim loại cho văn phòng",
                        "Bàn đá marble cao cấp",
                        "Ghế vải bọc chống thấm"
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
                        "response": f"🔍 **KẾT QUẢ TÌM KIẾM**\n\n"
                                    f"Tôi tìm thấy vật liệu **{', '.join(matched_mats)}** trong hệ thống.\n\n"
                                    f"**Tuy nhiên, hiện chưa có sản phẩm nào sử dụng vật liệu này.**\n\n"
                                    f"💡 **Gợi ý cho bạn:**\n"
                                    f"• Tìm sản phẩm với vật liệu tương tự\n"
                                    f"• Liên hệ bộ phận thiết kế để đặt hàng riêng\n"
                                    f"• Xem vật liệu thay thế có tính năng tương đồng",
                        "materials": matched_mats,
                        "suggested_prompts": [
                            "Tìm vật liệu thay thế phù hợp",
                            "Tư vấn sản phẩm custom theo yêu cầu",
                            "Xem danh mục vật liệu có sẵn"
                        ],
                        "materials": []
                    }
                else:
                    explanation = search_result.get("explanation", "")
                    response_text = f"✅ {explanation}\n\n"
                    response_text = (
                        f"✅ **SẢN PHẨM SỬ DỤNG {material_query.upper()}**\n\n"
                        f"{explanation}\n\n"
                        f"📊 **Tìm thấy {len(products)} sản phẩm:**\n"
                        f"Các sản phẩm này đều sử dụng {material_query} - một lựa chọn tuyệt vời về độ bền và thẩm mỹ.\n\n"
                        f"**Ưu điểm nổi bật:**\n"
                        f"• Chất lượng vật liệu được đảm bảo\n"
                        f"• Thiết kế phù hợp với xu hướng hiện đại\n"
                        f"• Dễ dàng bảo trì và vệ sinh\n\n"
                        f"Bạn quan tâm đến mẫu nào nhất?"
                    )
                    response_text += f"📦 Tìm thấy **{len(products)} sản phẩm**:"
                    
                    result_response = {
                        "response": response_text,
                        "products": products,
                        "search_method": "cross_table",
                        "can_provide_feedback": True,
                        "suggested_prompts": [
                            "So sánh 3 mẫu phổ biến nhất",
                            "Xem báo giá chi tiết",
                            "Tư vấn phối màu phù hợp"
                        ]
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
                    "response": f'🔍 Đã tìm thấy sản phẩm: **"{search_result.get("response", "Không tìm thấy vật liệu phù hợp.")}"**.\n\n'
                    "**Đề xuất:**\n"
                                "• Kiểm tra lại tên vật liệu (ví dụ: 'gỗ sồi Mỹ' thay vì 'gỗ sồi')\n"
                                "• Mô tả ứng dụng cụ thể (ví dụ: 'vật liệu chịu nước cho nhà tắm')\n"
                                "• Hoặc xem danh sách nhóm vật liệu phổ biến",
                    "suggested_prompts": [
                        "Vật liệu chịu nhiệt",
                        "Gỗ công nghiệp cao cấp",
                        "Đá tự nhiên trang trí",
                        "Vải bọc chống thấm"
                    ],
                    "materials": []
                }
            else:
                response_text = ""
                
                if intent_data.get("is_broad_query"):
                    follow_up = intent_data.get("follow_up_question", "Bạn cần tìm loại vật liệu cụ thể nào?")
                    response_text = (
                        f"🔎 **TÌM KIẾM VẬT LIỆU**\n"
                        f"Tìm thấy **{len(materials)} nguyên vật liệu** liên quan.\n\n"
                        f"💡 **Để tôi tư vấn chính xác hơn:** {follow_up}\n\n"
                        f"*Dưới đây là các vật liệu đang được sử dụng phổ biến:*"
                    )
                else:
                    # response_text = f"✅ Đã tìm thấy **{len(materials)} nguyên vật liệu** đúng yêu cầu."
                    response_text = (
                        f"✅ **TƯ VẤN VẬT LIỆU CHUYÊN SÂU**\n"
                        f"Dựa trên nhu cầu của bạn, **{len(materials)} vật liệu** dưới đây đang được sử dụng phổ biến và phù hợp nhất.\n\n"
                    )
                    # 🆕 Hiển thị ranking info
                    if ranking_summary['ranking_applied']:
                        response_text += f"\n\n⭐ **{ranking_summary['boosted_items']} vật liệu** được ưu tiên."

                response_text += "\n**Bảng tóm tắt các vật liệu:**\n"
                table = PrettyTable()
                table.field_names = [
                    "STT",
                    "Tên vật liệu",
                    "Mã SAP",
                    "Nhóm",
                    "Giá (VNĐ/ĐV)",
                    "Phản hồi"
                ]

                table.align = {
                    "Tên vật liệu": "l",
                    "Mã SAP": "l",
                    "Nhóm": "l",
                    "Giá (VNĐ/ĐV)": "r",
                    "Phản hồi": "c"
                }

                for idx, mat in enumerate(materials, 1):
                    price = f"{mat.get('price', 0):,.2f} / {mat.get('unit', '')}"
                    material_name = mat["material_name"]
                    feedback = (
                        f"{mat['feedback_count']} lượt"
                        if mat.get("has_feedback")
                        else "-"
                    )
                    table.add_row([
                        idx,
                        material_name,
                        mat["id_sap"],
                        mat["material_group"],
                        price,
                        feedback
                    ])
                response_text += (
                    "\n📦 **DANH SÁCH VẬT LIỆU ƯU TIÊN**\n"
                    "```\n"
                    f"{table}\n"
                    "```\n"
                )
                
                # Thêm phần link hình ảnh riêng (ngoài bảng)
                materials_with_images = [m for m in materials[:3] if m.get('image_url')]
                if materials_with_images:
                    response_text += "\n**📷 XEM ẢNH MẪU:**\n"
                    for mat in materials_with_images:
                        response_text += f"• [{mat['material_name']}]({mat.get('image_url', '#')})\n"
                
                
                response_text += (
                        f"**Nếu các vật liệu trên chưa đúng ý, tôi có thể:**\n"
                        f"• Gợi ý vật liệu thay thế với đặc tính tương tự\n"
                        f"• Tư vấn vật liệu theo ngân sách cụ thể\n"
                        f"• Giới thiệu sản phẩm đã sử dụng các vật liệu này\n\n"
                    )
                response_text += "\n\n**Bạn cần tôi hỗ trợ thêm điều gì?**"
                
                suggested_prompts = []
                if materials:
                    first_mat = materials[0]
                    suggested_prompts = [
                        f"📊 So sánh {first_mat['material_name']} với vật liệu khác",
                        f"🔍 Xem sản phẩm sử dụng {first_mat['material_name']}",
                        "💰 Tư vấn vật liệu theo ngân sách",
                        "📋 Xem bảng giá đầy đủ"
                    ]
                result_response = {
                    "response": response_text,
                    "materials": materials,
                    "suggested_prompts": suggested_prompts,
                    "ranking_summary": ranking_summary,  
                    "can_provide_feedback": True,
                    "show_comparison": True   
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
        
        # Lấy thông tin mở rộng từ kết quả tìm kiếm
        expanded = None
        keywords = []
        
        if intent == "search_product" and result_response.get("data"):
            expanded = result_response["data"].get("expanded_query")
            # Lấy keywords từ params
            if params.get("keywords_vector"):
                keywords = extract_product_keywords(params["keywords_vector"])
                
        print(f"SUCCESS => Final response: {result_response.get('materials', '')}, count: {result_count}")
        listProducts = listProducts or result_response.get("products", []) or result_response.get("materials", [])
        # Save chat history
        histories.save_chat_to_histories(
            email="test@gmail.com",
            session_id=msg.session_id,
            question=user_message,
            messages=listProducts,
            answer=result_response.get("response", "")
        )
        return result_response
    
    except Exception as e:
        print(f"Server Error: {e}")
        import traceback
        traceback.print_exc()
        return {"response": f"⚠️ Lỗi hệ thống: {str(e)}"}
    
