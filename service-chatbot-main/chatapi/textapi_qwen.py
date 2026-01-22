
import json
import re  
from datetime import datetime
from typing import Dict, List

import google.generativeai as genai
import psycopg2
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from psycopg2.extras import RealDictCursor

from config import settings
from feedbackapi.feedback import get_feedback_boost_for_query
from historiesapi import histories
from historiesapi.histories import router as history_router
from imageapi.media import router as media_router
from rankingapi.ranking import (apply_feedback_to_search, get_ranking_summary,
                                rerank_with_feedback)

from .embeddingapi import generate_embedding_qwen
from .textfunc import (calculate_product_total_cost, call_gemini_with_retry,
                        extract_product_keywords, format_search_results,
                        format_suggested_prompts, generate_consolidated_report,
                        get_latest_material_price, search_materials_for_product,
                        search_products_hybrid, search_products_keyword_only)
from .unit import (BatchProductRequest, ChatMessage, ConsolidatedBOMRequest,
                    TrackingRequest)

# Custom regex to filter illegal characters
# Filters ASCII control chars that are invalid in Excel files (XML)
# Includes: ASCII 0-8, 11-12, 14-31
ILLEGAL_CHARACTERS_RE = re.compile(r'[\000-\010]|[\013-\014]|[\016-\037]')

So_Cau_Goi_Y = 3  # Default number of suggested prompts


def build_markdown_table(headers: List[str], rows: List[List[str]]) -> str:
    """Create Markdown table from headers + rows for frontend HTML render + CSS styling.

    Each cell is already formatted (e.g., numbers with commas) before passing in.
    """
    if not headers:
        return ""

    # Header row
    header_row = "| " + " | ".join(str(h) for h in headers) + " |"
    # Basic alignment row, frontend can further adjust with CSS
    separator_row = "| " + " | ".join("---" for _ in headers) + " |"

    body_rows = [
        "| " + " | ".join(str(cell) for cell in row) + " |" for row in rows
    ]

    return "\n".join([header_row, separator_row] + body_rows)

def get_db():
    return psycopg2.connect(**settings.DB_CONFIG)

genai.configure(api_key=settings.My_GOOGLE_API_KEY)

router = APIRouter()
# ================================================================================================
# FUNCTION DEFINITIONS
# ================================================================================================

def generate_suggested_prompts(context_type: str, context_data: Dict = None, count: int = 4) -> List[str]:
    
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    prompt = f"""
        Bạn là chuyên viên tư vấn nội thất cao cấp của AA Corporation.
        Nhiệm vụ: Tạo {count} câu gợi ý TỰ NHIÊN, CHUYÊN NGHIỆP, PHÙ HỢP với ngữ cảnh, dạng câu HỎI, 
        Mỗi câu hỏi đều có PHÂN TÍCH, VÍ DỤ GỢI Ý để ĐỊNH HƯỚNG câu trả lời cho user RÕ RÀNG.
        
        NGỮ CẢNH: {context_type}.
        cách xưng hô: tôi và bạn.
        
        """

    if context_type == "greeting":
        prompt += """
        User vừa mới vào chat. Tạo 4 câu gợi ý giúp user bắt đầu:
        - Tìm sản phẩm phổ biến
        - Tư vấn vật liệu
        - Hỏi về giá
        - Hỗ trợ khác
        YÊU CẦU:
        - Ngắn gọn, rõ ràng (8-12 từ)
        - Không dùng emoji
        - Tự nhiên như lời nói
        - Đa dạng chủ đề
        """
    
    elif context_type == "search_product_found":
        products_info = context_data.get("products", [])
        query = context_data.get("query", "")
        prompt += f"""
        User vừa tìm: "{query}"
        Tìm thấy {len(products_info)} sản phẩm.
        Sản phẩm đầu tiên: {products_info[0].get('product_name', '')} ({products_info[0].get('headcode', '')})
        Tạo {So_Cau_Goi_Y} gợi ý trong những HÀNH ĐỘNG TIẾP THEO:
        - Xem chi tiết/giá sản phẩm cụ thể
        - So sánh hoặc tìm tương tự
        - Hỏi về vật liệu/cấu tạo
        - Tư vấn thêm
        YÊU CẦU:
        - Cụ thể, dựa trên kết quả tìm kiếm
        - Có tên sản phẩm/mã nếu cần
        - Tự nhiên, không máy móc
        - Không dùng emoji
        """
    
    elif context_type == "search_product_broad":
        query = context_data.get("query", "")
        prompt += f"""
        User tìm quá rộng: "{query}"
        Cần thu hẹp phạm vi.
        Tạo {So_Cau_Goi_Y} gợi ý trong những câu hỏi GỢI Ý giúp user CỤ THỂ HÓA:
        - Về mục đích sử dụng
        - Về phong cách/chất liệu
        - Về kích thước/không gian
        - Về ngân sách
        YÊU CẦU:
        - Dạng câu hỏi tự nhiên
        - Liên quan trực tiếp đến "{query}"
        - Giúp thu hẹp tìm kiếm
        - Không dùng emoji
        """
    
    elif context_type == "search_product_not_found":
        query = context_data.get("query", "")
        prompt += f"""
        User tìm: "{query}" - KHÔNG TÌM THẤY
        Tạo {So_Cau_Goi_Y} gợi ý trong những GIẢI PHÁP:
        - Tìm từ khóa tương tự
        - Xem danh mục liên quan
        - Tư vấn sản phẩm thay thế
        - Liên hệ tư vấn
        YÊU CẦU:
        - Tích cực, giúp đỡ
        - Cụ thể, có hướng giải quyết
        - Không dùng emoji
        """

    elif context_type == "search_material_found":
        materials_info = context_data.get("materials", [])
        query = context_data.get("query", "")
        prompt += f"""
        User tìm vật liệu: "{query}"
        Tìm thấy {len(materials_info)} vật liệu.
        Vật liệu đầu: {materials_info[0].get('material_name', '')}
        Tạo {So_Cau_Goi_Y} gợi ý trong những HÀNH ĐỘNG:
        - Xem chi tiết vật liệu
        - So sánh giá/tính năng
        - Xem sản phẩm dùng vật liệu này
        - Tư vấn vật liệu thay thế
        YÊU CẦU:
        - Có tên vật liệu cụ thể
        - Hành động rõ ràng
        - Không dùng emoji
        """

    elif context_type == "product_materials":
        product_name = context_data.get("product_name", "")
        headcode = context_data.get("headcode", "")
        prompt += f"""
        User đang xem định mức vật liệu của:
        {product_name} ({headcode})
        Tạo {So_Cau_Goi_Y} gợi ý trong những việc TIẾP THEO:
        - Xem giá/chi phí
        - So sánh với sản phẩm khác
        - Tìm vật liệu thay thế
        - Xuất báo cáo
        YÊU CẦU:
        - Dùng mã {headcode} nếu cần
        - Hành động cụ thể
        - Không dùng emoji
        """
    
    elif context_type == "product_cost":
        product_name = context_data.get("product_name", "")
        headcode = context_data.get("headcode", "")
        prompt += f"""
        User đang xem chi phí của:
        {product_name} ({headcode})
        Tạo {So_Cau_Goi_Y} gợi ý trong những việc sau:
        - Xem chi tiết vật liệu
        - So sánh giá với sản phẩm khác
        - Tối ưu chi phí
        - Xuất báo cáo
        YÊU CẦU:
        - Liên quan đến chi phí/giá
        - Không dùng emoji
        """
    
    elif context_type == "get_product_materials":
        product_name = context_data.get("product_name", "")
        headcode = context_data.get("headcode", "")
        prompt += f"""
        User đang xem chi phí của:
        {product_name} ({headcode})
        Tạo {So_Cau_Goi_Y} gợi ý trong những việc sau:
        - tên gọi của những sản phẩm tương tự
        - vật liệu phổ biến dùng cho sản phẩm này
        - tìm sản phẩm thay thế
        YÊU CẦU:
        - Liên quan đến chi phí/giá
        - Không dùng emoji
        """

    elif context_type == "calculate_product_cost":
        product_name = context_data.get("product_name", "")
        headcode = context_data.get("headcode", "")
        prompt += f"""
        User đang xem chi phí của:
        {product_name} ({headcode})
        Tạo {So_Cau_Goi_Y} gợi ý trong những việc sau:
        - tên gọi của những sản phẩm tương tự
        - vật liệu phổ biến dùng cho sản phẩm này
        - tìm sản phẩm thay thế
        YÊU CẦU:
        - Liên quan đến chi phí/giá
        - Không dùng emoji
        """

    elif context_type == "batch_materials":
        product_count = context_data.get("product_count", 0)
        first_product = context_data.get("first_product", "")
        prompt += f"""
        User vừa xem định mức {product_count} sản phẩm.
        Sản phẩm đầu: {first_product}
        Tạo {So_Cau_Goi_Y} gợi ý trong những việc sau:
        - Xem báo cáo chi phí
        - Xuất Excel
        - Phân tích chi tiết
        - So sánh giá vật liệu
        YÊU CẦU:
        - Phù hợp với batch operation
        - Không dùng emoji
        """
    
    elif context_type == "batch_cost":
        product_count = context_data.get("product_count", 0)
        first_headcode = context_data.get("first_headcode", "")
        prompt += f"""
        User vừa xem chi phí {product_count} sản phẩm.
        Tạo {So_Cau_Goi_Y} gợi ý trong những việc sau:
        - Xem định mức chi tiết
        - Xuất báo cáo Excel
        - Phân tích vật liệu
        - Tìm vật liệu giá tốt hơn
        YÊU CẦU:
        - Liên quan đến tối ưu chi phí
        - Không dùng emoji
        """
    
    else:
        prompt += """
        Tạo 4 gợi ý chung:
        - Tìm sản phẩm
        - Tìm vật liệu  
        - Xem giá
        - Trợ giúp
        """
            
    prompt += """
    OUTPUT FORMAT (JSON array only):
    [
        "Gợi ý 1 - tự nhiên, không emoji",
        "Gợi ý 2 - tự nhiên, không emoji",
        "Gợi ý 3 - tự nhiên, không emoji"
    ]
    """
    try:
        response_text = call_gemini_with_retry(model, prompt)
        # print(f"Suggested prompts response: {response_text}")
        
        if not response_text:
            return _get_fallback_prompts(context_type)
        
        clean_text = response_text.strip()
        if "```json" in clean_text:
            clean_text = clean_text.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_text:
            clean_text = clean_text.split("```")[1].split("```")[0].strip()
        
        prompts = json.loads(clean_text)
        return prompts[:count]
        
    except Exception as e:
        print(f"WARNING: Prompt generation failed: {e}")
        return _get_fallback_prompts(context_type)

def _get_fallback_prompts(context_type: str) -> List[str]:
    """Fallback prompts if genai fails"""
    fallbacks = {
        "greeting": [
            "Tìm bàn làm việc hiện đại",
            "Xem các loại gỗ cao cấp",
            "Tư vấn báo giá sản phẩm",
            "Danh sách vật liệu phổ biến"
        ],
        "search_product_found": [
            "Xem chi tiết sản phẩm đầu tiên",
            "So sánh với mẫu tương tự",
            "Phân tích vật liệu sử dụng",
            "Tư vấn thêm về sản phẩm"
        ],
        "search_material_found": [
            "Xem chi tiết vật liệu đầu tiên",
            "So sánh giá các loại vật liệu",
            "Xem sản phẩm dùng vật liệu này",
            "Tư vấn vật liệu thay thế"
        ]
    }
    return fallbacks.get(context_type, [
        "Tìm sản phẩm mới",
        "Tìm nguyên vật liệu",
        "Xem bảng giá",
        "Trợ giúp khác"
    ])

def get_intent_and_params(user_message: str, context: Dict) -> Dict:
    """AI Router with Reasoning & Soft Clarification capability"""
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

       **LISTING FLOW:**
       - **list_products_by_category**: Liệt kê danh sách sản phẩm theo các danh mục khác nhau (VD: "Danh sách sản phẩm", "Xem tất cả sản phẩm", "Liệt kê sản phẩm theo danh mục")

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
        "intent": "search_product|search_product_by_material|search_material_for_product|query_product_materials|calculate_product_cost|search_material|query_material_detail|list_material_groups|list_products_by_category|greeting|unknown",
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
    
    response_text = call_gemini_with_retry(model, prompt, timeout=15)
    if not response_text:
        return {
            "intent": "error",
            "raw": "No response from AI - timeout or API error",
            "success": False,
            "error_message": "Hệ thống đang quá tải. Vui lòng thử lại sau ít phút."
        }
    
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
        return {
            "intent": "error", 
            "raw": response_text,
            "success": False
        }
        
    except Exception as e:
        print(f"Parse Error: {e}")
        return {
            "intent": "error", "raw": response_text,
            "success": False
        }

def _generate_broader_search_params(original_params: Dict) -> Dict:
    """Generate broader search parameters for fallback search"""
    broader_params = original_params.copy()
    
    # Strategy 1: If keywords_vector is too specific, use only category
    if original_params.get("keywords_vector"):
        keywords = original_params["keywords_vector"]
        # Get only the first 1-2 words (most general terms)
        words = keywords.split()[:2]
        broader_params["keywords_vector"] = " ".join(words)
        print(f"INFO: Broadened keywords from '{keywords}' to '{broader_params['keywords_vector']}'")
    
    # Strategy 2: If category and subcategory exist, remove subcategory
    if original_params.get("sub_category"):
        broader_params.pop("sub_category", None)
        print(f"INFO: Removed sub_category filter for broader search")
    
    # Strategy 3: If material_primary is specified, remove it for broader results
    if original_params.get("material_primary"):
        broader_params.pop("material_primary", None)
        print(f"INFO: Removed material_primary filter for broader search")
    
    # Strategy 4: If only category remains and keywords, use just category
    if broader_params.get("category") and not broader_params.get("keywords_vector"):
        broader_params["keywords_vector"] = broader_params["category"]
        print(f"INFO: Using category as keywords: '{broader_params['keywords_vector']}'")
    
    return broader_params

def search_products(params: Dict, session_id: str = None, disable_fallback: bool = False):
    print(f"params: search_products + search_products_hybrid {params}")
    
    # Check if this is a parallel search request (has both main_keywords and secondary_keywords)
    has_dual_keywords = params.get("main_keywords") and params.get("secondary_keywords")
    
    # TIER 1: Try Hybrid first
    try:
        result = search_products_hybrid(params)
        print(f"INFO: Hybrid search results - Found {len(result.get('products', []))} products")
        print(f"INFO: Hybrid search results - Found {len(result.get('products_second', []))} products_second")
        # Check if there's a timeout error or search method indicates no results
        if result.get("search_method") == "timeout":
            print("TIMER: Search timeout - returning empty products list")
            return {
                "products": [],
                "products_second": [] if has_dual_keywords else None,
                "search_method": "timeout",
                "response": "No matching products found",
                "success": False
            }
        
        if result.get("products") or result.get("products_second"):
            # Update total_cost for products in hybrid search
            products = result.get("products", [])
            products_second = result.get("products_second", [])
            
            for product in products:
                product["total_cost"] = calculate_product_total_cost(product["headcode"])
            
            for product in products_second:
                product["total_cost"] = calculate_product_total_cost(product["headcode"])
                
            products = result["products"]
            
            # ========== STEP 1: BASE SCORES ==========
            for product in products:
                product['base_score'] = float(product.get('similarity', 0.5))
            
            # ========== STEP 1.5: QUERY MATCHING BOOST ==========
            # Boost base_score if query appears in product fields
            query_keywords = params.get("keywords_vector", "").lower().split()
            
            for product in products:
                boost = 0.0
                
                # Fields to check
                product_name = (product.get('product_name') or '').lower()
                category = (product.get('category') or '').lower()
                sub_category = (product.get('sub_category') or '').lower()
                material_primary = (product.get('material_primary') or '').lower()
                headcode = (product.get('headcode') or '').lower()
                
                # Count keyword matches
                match_count = 0
                for keyword in query_keywords:
                    
                    # Boost if keyword appears in product name (most important)
                    if keyword in product_name:
                        boost += 0.15
                        match_count += 1
                    
                    # Boost if appears in category
                    if keyword in category:
                        boost += 0.08
                        match_count += 1
                    
                    # Boost if appears in subcategory
                    if keyword in sub_category:
                        boost += 0.06
                        match_count += 1
                    
                    # Boost if appears in primary material
                    if keyword in material_primary:
                        boost += 0.05
                        match_count += 1
                    
                    # Boost if appears in product code
                    if keyword in headcode:
                        boost += 0.04
                        match_count += 1
                
                # Update base_score (max limit 1.0)
                if boost > 0:
                    product['base_score'] = min(1.0, product['base_score'] + boost)
                    product['query_match_count'] = match_count
                    product['query_boost'] = boost
                    print(f"  INFO: Boosted {product['headcode']}: +{boost:.3f} (matches: {match_count})")
            
            products_main = [p for p in products if p.get('final_score', 0) >= 0.75]
            products_low_confidence = [p for p in products if p.get('base_score', 0) < 0.6]
            
            print(f"INFO: Main products: {len(products_main)}, Low confidence: {len(products_low_confidence)}")
            result["search_method"] = result.get("search_method", "hybrid")
            return result
            
    except TimeoutError as e:
        print(f"TIMER: TIER 1 timeout: {e}")
        # Return empty result instead of fallback to TIER 2
        return {
            "products": [],
            "search_method": "timeout",
            "response": "No matching products found",
            "success": False
        }
    except Exception as e:
        error_str = str(e).lower()
        print(f"WARNING: TIER 1 failed: {e}")
        # Check if error is related to timeout
        if "timeout" in error_str or "timed out" in error_str or "canceled" in error_str:
            return {
                "products": [],
                "search_method": "timeout",
                "response": "No matching products found",
                "success": False
            }

    print("WARNING: TIER 1 returned no products, returning empty instead of fallback")
    return {
        "products": [],
        "search_method": "no_results",
        "response": "No matching products found",
        "success": False
    }

def search_products_by_material(material_query: str, params: Dict):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    print(f"INFO: Cross-table search: Products made from '{material_query}'")
    
    # Step 1: Find matching materials
    material_vector = generate_embedding_qwen(material_query)
    
    if not material_vector:
        conn.close()
        return {
            "products": [], 
            "search_method": "failed",
            "success": False
        }
    
    try:
        print("Find top matching materials")
        cur.execute(f"""
            SELECT 
                id_sap, 
                material_name,
                material_group,
                (description_embedding <=> %s::vector) as distance
            FROM {settings.MATERIALS_TABLE}
            WHERE description_embedding IS NOT NULL
            ORDER BY distance ASC
            LIMIT 5
        """, [material_vector])
        
        matched_materials = cur.fetchall()
        
        if not matched_materials:
            conn.close()
            return {
                "products": [], 
                "search_method": "no_materials_found",
                "success": False
            }
        
        material_ids = [m['id_sap'] for m in matched_materials]
        material_names = [m['material_name'] for m in matched_materials]
        
        print(f"SUCCESS: Found {len(material_ids)} matching materials: {material_names[:3]}")
        
        # Step 2: Find products using these materials
        # Combine category filter if available
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
                "matched_materials": material_names,
                "success": False
            }
        
        # Group products (because 1 product can use multiple materials)
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
        
        # Add base_score for consistency and apply query matching boost
        query_keywords = material_query.lower().split()
        
        print("INFO: Applied query matching boost to products")
        # print("INFO: products_list", products_list)
        
        for product in products_list:
            # Set initial base_score based on relevance_score
            product['base_score'] = min(1.0, 0.5 + (product['relevance_score'] * 0.1))
            
            # Apply query matching boost
            boost = 0.0
            product_name = (product.get('product_name') or '').lower()
            category = (product.get('category') or '').lower()
            sub_category = (product.get('sub_category') or '').lower()
            material_primary = (product.get('material_primary') or '').lower()
            
            match_count = 0
            for keyword in query_keywords:
                if len(keyword) < 2:
                    continue
                
                if keyword in product_name:
                    boost += 0.15
                    match_count += 1
                if keyword in category:
                    boost += 0.08
                    match_count += 1
                if keyword in sub_category:
                    boost += 0.06
                    match_count += 1
                if keyword in material_primary:
                    boost += 0.05
                    match_count += 1
            
            if boost > 0:
                product['base_score'] = min(1.0, product['base_score'] + boost)
                product['query_match_count'] = match_count
                product['query_boost'] = boost
                

        
        # Split products based on base_score
        products_high = [p for p in products_list if p.get('base_score', 0) >= 0.7][:10]
        products_bonus = [p for p in products_list if 0.65 < p.get('base_score', 0) < 0.7]
        
        return {
            "products": products_high,
            "products_second": products_bonus,
            "search_method": "cross_table_material_to_product",
            "matched_materials": material_names,
            "explanation": f"Tìm thấy sản phẩm sử dụng: {', '.join(material_names[:3])}",
            "success": True
        }
        
    except Exception as e:
        print(f"ERROR: Cross-table search failed: {e}")
        conn.close()
        return {
            "products": [], 
            "search_method": "cross_table_error",
            "success": False
        }

def get_product_materials(headcode: str):
    """Lấy danh sách vật liệu của SẢN PHẨM"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT product_name FROM products_qwen WHERE headcode = %s", (headcode,))
    prod = cur.fetchone()
    
    if not prod:
        conn.close()
        return {
            "response": f"ERROR: Không tìm thấy sản phẩm với mã **{headcode}**",
            "success": False
        }
    
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
        return {"response": f"Lỗi truy vấn database: {str(e)}",
            "response": f"Lỗi truy vấn database: {str(e)}",
            "success": False
        }           
    
    conn.close()
    
    # Get price history (if needed) from first material with data
    price_history = []
    try:
        first_with_price = next(
            (m for m in materials if m.get('material_subprice')),
            None
        )
        if first_with_price and first_with_price['material_subprice']:
            price_history = json.loads(first_with_price['material_subprice'])
    except Exception:
        pass
    
    if not materials:
        return {
            "response": f"WARNING: Sản phẩm **{prod['product_name']}** ({headcode}) chưa có định mức vật liệu.\n\n"
                        f"Có thể:\n"
                        f"• Sản phẩm mới chưa nhập định mức\n"
                        f"• Chưa import file product_materials.csv\n"
                        f"• Mã sản phẩm trong product_materials không khớp\n\n"
                        f"Vui lòng kiểm tra lại hoặc liên hệ bộ phận kỹ thuật.",
            "success": False
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
            'price': latest_price,
            'unit_price': latest_price,
            'unit': mat['material_unit'],
            'total_cost': total_cost,
            'price_history': mat['material_subprice']
        })
    
    response = f" 🎉 **ĐỊNH MỨC VẬT LIỆU: {prod['product_name']}**\n"
    response += f"🏷️ Mã: `{headcode}`\n"
    response += f"📦 Total materials: **{len(materials_with_price)}**\n\n"

    # Markdown table summary for materials (max 10 rows)
    headers = [
        "No.",
        "Material name",
        "SAP code",
        "Group",
        "Quantity",
        "Latest unit price (VND)",
        "Total (VND)"
    ]
    rows = []

    for idx, mat in enumerate(materials_with_price[:15], 1):
        group_full = mat["material_group"] or ""
        if mat.get("material_subgroup"):
            group_full += f" - {mat['material_subgroup']}"
        rows.append([
            idx,
            mat["material_name"],
            mat["id_sap"],
            group_full,
            f"{mat['quantity']:,.2f} {mat['pm_unit']}",
            f"{mat['unit_price']:,.2f}",
            f"{mat['total_cost']:,.2f}",
        ])

    
    response += f"\n---\n\n💰 **TOTAL MATERIAL COST: {total:,.2f} VND**"
    # response += f"\n\n⚠️ **Note:** Prices calculated from latest purchase history. Actual prices may vary."
    
    # Add image link (if at least one material has image_url)
    first_image_url = next(
        (m['image_url'] for m in materials_with_price if m.get('image_url')),
        None
    )
    if first_image_url:
        response += "\n\n"
        response += f"🖼️ **View material images:** [Google Drive Link]({first_image_url}) _ "
        response += f"_(Click to view detailed images)_"
    
    latest_price_summary = materials_with_price[0]['price'] if materials_with_price else 0

    # Generate suggested follow-up questions
    suggested_prompts = generate_suggested_prompts(
        "get_product_materials",
        {
            "product_name": prod['product_name'],
            "headcode": headcode,
        },
    )
    suggested_prompts_mess = format_suggested_prompts(suggested_prompts)
    return {
        "response": response,
        "materials": materials_with_price,
        "total_cost": total,
        "product_name": prod['product_name'],
        "latest_price": latest_price_summary,
        "price_history": price_history,
        "suggested_prompts_mess":suggested_prompts_mess,
        "success": True
    }

def calculate_product_cost(headcode: str):
    """Calculate MATERIAL COST for product (Simplified V4.7)"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT product_name, category FROM products_qwen WHERE headcode = %s", (headcode,))
    prod = cur.fetchone()
    
    if not prod:
        conn.close()
        return {
            "response": f"ERROR: Không tìm thấy sản phẩm với mã **{headcode}**",
            "success": False
        }
    
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
        return {
            "response": f"Lỗi truy vấn database: {str(e)}",
            "success": False
        }
    
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
                        f"2. Import lại file qua sidebar: **Import Dữ Liệu → Định Mức**",
            "success": False
        }
    
    # ✅ Calculate TOTAL MATERIAL COST
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

    # ✅ SIMPLE RESPONSE - MATERIAL COST ONLY
    response = f"""💰 **BÁO GIÁ NGUYÊN VẬT LIỆU**\n\n"""
    response += f"""📦 **Sản phẩm:** {prod['product_name']}\n\n"""
    response += f"""🏷️ **Mã:** `{headcode}`\n\n"""
    response += f"""📂 **Danh mục:** {prod['category'] or 'N/A'}\n\n"""
    response += f"\n\n---\n\n"
    response += f"**CHI TIẾT NGUYÊN VẬT LIỆU ({material_count} loại):**\n"

    # Markdown table for first 15 materials max
    headers = [
        "STT",
        "Tên vật liệu",
        "Nhóm",
        "Số lượng",
        "Đơn giá (VNĐ)",
        "Thành tiền (VNĐ)"
    ]
    rows = []

    for idx, mat in enumerate(materials_detail[:15], 1):
        rows.append([
            idx,
            mat["material_name"],
            mat["material_group"],
            f"{mat['quantity']:,.2f} {mat['unit']}",
            f"{mat['unit_price']:,.0f}",
            f"{mat['total_cost']:,.0f}",
        ])
    
    if len(materials_detail) > 15:
        response += f"*...và {len(materials_detail)-15} vật liệu khác*\n\n"

    response += f"---\n\n"
    response += f"✅ **TỔNG CHI PHÍ NGUYÊN VẬT LIỆU: {material_cost:,.0f} VNĐ**\n\n"
    response += f"📋 **Lưu ý:** Giá được tính từ lịch sử mua hàng gần nhất.\n"
    
    suggested_prompts = generate_suggested_prompts(
        "calculate_product_cost",
        {
            "product_name": prod['product_name'],
            "headcode": headcode,
        },
    )
    suggested_prompts_mess = format_suggested_prompts(suggested_prompts)
    
    return {
        "response": response,
        "material_cost": material_cost,
        "material_count": material_count,
        "materials": materials_detail,
        "suggested_prompts_mess":suggested_prompts_mess,
        "suggested_prompts":[
            "Phân tích vật liệu {headcode}"
        ],
        "success": True
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
    print(f"SEARCH: Searching materials for: {query_text}")
    
    # ✅ EXTRACT MAIN KEYWORD - similar to product search
    # Extract main keyword from material_name to filter results
    main_keyword = None
    if params.get("material_name"):
        name = params['material_name']
        # Get main keyword (after '-' if present)
        # Example: "GỖ-BEECH" → main_keyword = "BEECH" (for exact filtering)
        if '-' in name:
            parts = name.upper().split('-')
            if len(parts) >= 2:
                main_keyword = parts[-1].strip()  # Get part after '-'
    
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
                FROM {settings.MATERIALS_TABLE}
                WHERE description_embedding IS NOT NULL AND {filter_clause}
                ORDER BY distance ASC
                LIMIT 30
            """

            cur.execute(sql, [query_vector] + filter_params)
            results = cur.fetchall()
            
            if results:
                # ✅ POST-FILTER: If main_keyword exists, only keep materials containing that keyword
                if main_keyword:
                    filtered_results = []
                    for mat in results:
                        mat_name_upper = mat['material_name'].upper()
                        if main_keyword in mat_name_upper:
                            filtered_results.append(mat)
                    
                    print(f"POST-FILTER (Vector): Filtered from {len(results)} to {len(filtered_results)} materials with keyword '{main_keyword}'")
                    results = filtered_results[:10]
                    
                    if not results:
                        print(f"No materials found with keyword '{main_keyword}' after vector search")
                        # Continue to keyword search below
                        pass
                    else:
                        print(f"SUCCESS: Vector search: Found {len(results)} materials")
                        
                        materials_with_price = []
                        for mat in results:
                            mat_dict = dict(mat)
                            mat_dict['price'] = get_latest_material_price(mat_dict['material_subprice'])
                            materials_with_price.append(mat_dict)
                        
                        conn.close()
                        return {
                            "materials": materials_with_price,
                            "search_method": "vector",
                            "success": True
                        }
                else:
                    print(f"SUCCESS: Vector search: Found {len(results)} materials")
                    
                    materials_with_price = []
                    for mat in results[:10]:
                        mat_dict = dict(mat)
                        mat_dict['price'] = get_latest_material_price(mat_dict['material_subprice'])
                        materials_with_price.append(mat_dict)
                    
                    conn.close()
                    return {
                        "materials": materials_with_price,
                        "search_method": "vector",
                        "success": True
                    }
        except Exception as e:
            print(f"WARNING: Vector search failed: {e}")
    
    print("INFO: Keyword search for materials")
    conditions = []
    values = []
    
    # ✅ EXTRACT MAIN KEYWORD - similar to product search
    # Extract main keyword from material_name for checking later
    main_keyword = None
    if params.get("material_name"):
        name = params['material_name']
        # Get main keyword (after '-' if present)
        # Example: "GỖ-BEECH" → main_keyword = "BEECH" (for exact filtering)
        if '-' in name:
            parts = name.upper().split('-')
            if len(parts) >= 2:
                main_keyword = parts[-1].strip()  # Get part after '-'
        
        conditions.append("(material_name ILIKE %s OR material_group ILIKE %s)")
        values.extend([f"%{name}%", f"%{name}%"])
    
    if params.get("material_group"):
        group = params['material_group']
        conditions.append("material_group ILIKE %s")
        values.append(f"%{group}%")
    
    if conditions:
        where_clause = " OR ".join(conditions)
        sql = f"SELECT * FROM {settings.MATERIALS_TABLE} WHERE {where_clause} LIMIT 50"
    else:
        sql = f"SELECT * FROM {settings.MATERIALS_TABLE} ORDER BY material_name ASC LIMIT 10"
        values = []
    
    try:
        cur.execute(sql, values)
        results = cur.fetchall()
        conn.close()
        
        if not results:
            return {
                "response": "Không tìm thấy vật liệu phù hợp.",
                "materials": [],
                "success": False
            }
        
        # ✅ POST-FILTER: If main_keyword exists, only keep materials containing that keyword
        # Example: Search "GỖ-BEECH" → Only keep materials with "BEECH" in name, remove "GỖ-WHITE"
        if main_keyword:
            filtered_results = []
            for mat in results:
                mat_name_upper = mat['material_name'].upper()
                # Check if main_keyword is in material_name
                if main_keyword in mat_name_upper:
                    filtered_results.append(mat)
            
            print(f"POST-FILTER: Filtered from {len(results)} to {len(filtered_results)} materials with keyword '{main_keyword}'")
            results = filtered_results[:15]  # Limit to 15 results
            
            if not results:
                return {
                    "response": f"Không tìm thấy vật liệu chứa '{params.get('material_name')}'.",
                    "materials": [],
                    "success": False
                }
        
        materials_with_price = []
        for mat in results[:15]:  # Limit to 15 results
            mat_dict = dict(mat)
            mat_dict['price'] = get_latest_material_price(mat.get('material_subprice'))
            materials_with_price.append(mat_dict)
        
        print(f"SUCCESS: Keyword search: Found {len(materials_with_price)} materials")
        return {
            "materials": materials_with_price,
            "search_method": "keyword",
            "success": True
        }
    except Exception as e:
        conn.close()
        print(f"ERROR: Material search failed: {e}")
        return {
            "response": "Lỗi tìm kiếm vật liệu.",
            "materials": [],
            "success": False
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
        return {
            "response": "WARNING: Cần cung cấp mã SAP hoặc tên vật liệu.",
            "success": False
    }
    
    material = cur.fetchone()
    
    if not material:
        conn.close()
        return {
            "response": f"ERROR: Không tìm thấy vật liệu **{id_sap or material_name}**",
            "success": False
        }
    
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
    
    response = f"🧱 **CHI TIẾT NGUYÊN VẬT LIỆU**\n\n"
    response += f"📦 **Tên:** {material['material_name']}\n"
    response += f"🏷️ **Mã SAP:** `{material['id_sap']}`\n"
    response += f"📂 **Nhóm:** {material['material_group']}\n"
                    
    if material.get('material_subgroup'):
        response += f" - {material['material_subgroup']}\n"
    response += f"💰 **Giá mới nhất:** {latest_price:,.2f} VNĐ/{material['unit']}\n"
    response += f"📊 **THỐNG KÊ SỬ DỤNG:**\n"
    response += f"• Được sử dụng trong **{stats['product_count']} sản phẩm**\n"
    response += f"• Xuất hiện ở **{stats['project_count']} dự án**\n"
    response += f"• Tổng số lượng: **{stats.get('total_quantity', 0) or 0} {material['unit']}**\n"  
    response += "\n---\n\n"
    
    if price_history and len(price_history) > 0:
        response += "📈 **LỊCH SỬ GIÁ:**\n\n"
        for idx, ph in enumerate(sorted(price_history, key=lambda x: x['date'], reverse=True)[:5], 1):
            response += f"{idx}. **{ph['date']}**: {ph['price']:,.2f} VNĐ\n"
        response += "\n---\n\n"
    
    if used_in_products and len(used_in_products) > 0:
        response += f"INFO: **CÁC SẢN PHẨM SỬ DỤNG VẬT LIỆU NÀY:**\n\n"
        
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
        response += f"(Click để xem ảnh chi tiết)"
    
    return {
        "response": response,
        # "material_detail": dict(material),
        "materials": [{  # ✅ Change to list like search_materials
            **dict(material),
            'price': latest_price  # ✅ Add 'price' key
        }],
        "latest_price": latest_price,
        "price_history": price_history,
        "used_in_products": [dict(p) for p in used_in_products],
        "stats": dict(stats) if stats else {},
        "has_image": bool(material.get('image_url')),
        "success": True
    }

def list_material_groups():
    """Liệt kê các nhóm vật liệu với giá tính từ material_subprice"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    sql = f"""
        SELECT 
            material_group,
            COUNT(*) as count,
            array_agg(DISTINCT material_subprice) as all_prices
        FROM {settings.MATERIALS_TABLE}
        WHERE material_group IS NOT NULL
        GROUP BY material_group
        ORDER BY count DESC
    """
    cur.execute(sql)
    groups = cur.fetchall()
    conn.close()
    
    if not groups:
        return {
            "response": "Chưa có dữ liệu nhóm vật liệu.",
            "success": False
        }
    
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
        "material_groups": groups_with_stats,
        "success": True
    }

def list_products_by_category():
    """Liệt kê danh sách sản phẩm theo các danh mục khác nhau"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get list of products by category, limit 5 products per category
    sql = """
        WITH ranked_products AS (
            SELECT 
                headcode,
                product_name,
                category,
                sub_category,
                material_primary,
                ROW_NUMBER() OVER (PARTITION BY category ORDER BY product_name) as rn
            FROM products_qwen
            WHERE category IS NOT NULL
        )
        SELECT 
            headcode,
            product_name,
            category,
            sub_category,
            material_primary
        FROM ranked_products
        WHERE rn <= 1
        ORDER BY category, product_name
    """
    
    cur.execute(sql)
    products = cur.fetchall()
    conn.close()
    
    if not products:
        return {
            "response": "Chưa có dữ liệu sản phẩm.",
            "success": False
        }
    
    # Group products by category
    categories = {}
    for prod in products:
        cat = prod['category']
        if cat not in categories:
            categories[cat] = []
        
        # Add total_cost for each product
        prod_dict = dict(prod)
        prod_dict['total_cost'] = calculate_product_total_cost(prod['headcode'])
        categories[cat].append(prod_dict)
    
    response = f"️🎉 **DANH SÁCH SẢN PHẨM THEO DANH MỤC ({len(categories)} danh mục):**\n\n"
    
    all_products = []
    for idx, (cat_name, prods) in enumerate(sorted(categories.items()), 1):
    #     response += f"### {idx}. {cat_name} ({len(prods)} sản phẩm)\n\n"
        
    #     for prod_idx, prod in enumerate(prods, 1):
    #         response += f"   {prod_idx}. **{prod['product_name']}** (`{prod['headcode']}`)\n"
    #         if prod.get('sub_category'):
    #             response += f"      • Danh mục phụ: {prod['sub_category']}\n"
    #         if prod.get('material_primary'):
    #             response += f"      • Vật liệu chính: {prod['material_primary']}\n"
        
    #     response += "\n"
        all_products.extend(prods)
    
    response += "\n⭐ **Ghi chú:** Chọn một sản phẩm để xem chi tiết hoặc tính chi phí.\n"
    
    return {
        "response": response,
        "products": all_products,
        "categories": list(categories.keys()),
        "success": True
    }

# ================================================================================================
# API ENDPOINTS
# ================================================================================================

@router.post("/chat", tags=["Chat qwen"])
def chat(msg: ChatMessage):
    """Main chat logic"""
    try:
        user_message = msg.message
        context = msg.context or {}
        
        intent_data = get_intent_and_params(user_message, context)
        
        if intent_data.get("intent") == "error":
            error_msg = intent_data.get("error_message", "Xin lỗi, hệ thống đang bận. Vui lòng thử lại.")
            return {
                "response": error_msg,
                "success": False,
                "suggested_prompts": [
                    "🔍 Tìm sản phẩm",
                    "🧱 Tìm vật liệu",
                    "💬 Trò chuyện với chuyên viên"
                ]
            }
        
        intent = intent_data["intent"]
        params = intent_data.get("params", {})
        
        result_response = None
        result_count = 0
        
        listProducts = []
        # GREETING
        if intent == "greeting":
            tmp = generate_suggested_prompts("greeting")
            suggested_prompts_mess = format_suggested_prompts(tmp)
            result_response = {
                "response": "👋 Xin chào! Tôi là trợ lý AI của AA Corporation.\n\n"
                        "Tôi có thể giúp bạn:\n"
                        f"{suggested_prompts_mess}"
                        "Bạn cần tìm gì hôm nay?",
                "suggested_prompts": suggested_prompts
            }
        
        elif intent == "search_product":
            search_result = search_products(params, session_id=msg.session_id)
            products = search_result.get("products", [])

            ranking_summary = search_result.get("ranking_summary", {})
            result_count = len(products)
            print(f"INFO: search_result",search_result)
            
            if search_result.get("no_results") == "no_results":
                print(f"⏱️ Search timeout or failed for query: {user_message}")
                result_response = {
                    "response": " 💔 Thành thật xin lỗi, tôi không tìm thấy kết quả phù hợp trong cơ sở dữ liêu.\n\n Bạn có thể mô tả nhiều hơn về sản phẫm mong muốn không?\n\n Hoặc bạn có thể chọn xem Danh sách sản phẩm ở **Gợi ý nhanh** để tìm sản phẩm ưng ý.",
                    "products": [],
                    "materials": [],
                    "success": False,
                }
                return result_response
            
            # Check if search timed out or errored
            if search_result.get("search_method") == "timeout":
                print(f"⏱️ Search timeout or failed for query: {user_message}")
                result_response = {
                    "response": " 💔 Thành thật xin lỗi, hệ thống tìm kiếm hiện đang quá tải và không thể trả về kết quả ngay lúc này.\n\n",
                    "products": [],
                    "materials": [],
                    "success": False,
                }
                return result_response
            elif not products:
                try:
                    tmp = generate_suggested_prompts(
                        "search_product_not_found",
                        {"query": user_message}
                    )
                    suggested_prompts_mess = format_suggested_prompts(tmp)
                except Exception as e:
                    print(f"WARNING: Could not generate suggestions: {e}")
                    suggested_prompts_mess = "• Thử với từ khóa khác\n• Tìm theo danh mục sản phẩm\n• Liên hệ tư vấn viên"
                response_msg = " 🔍 **KẾT QUẢ TÌM KIẾM**\n\n"
                response_msg += f" 💔 Thật xin lỗi tôi không tìm thấy sản phẩm phù hợp với yêu cầu của bạn trong cơ sở dữ liệu.\n"
                
                result_response = {
                    "response": response_msg,
                    "suggested_prompts": [
                        "Xem danh mục sản phẩm phổ biến",
                        "Tìm theo vật liệu",
                        "Liên hệ chuyên viên tư vấn"
                    ],
                    "success": True,
                    "suggested_prompts_mess": suggested_prompts_mess
                }
                return result_response
            else:
                response_text = ""
                suggested_prompts = []
                tmp = generate_suggested_prompts(
                        "search_product_broad",
                        {"query": user_message, "products": products}
                )
                suggested_prompts_mess = format_suggested_prompts(tmp)
                if intent_data.get("is_broad_query"):
                    follow_up = intent_data.get("follow_up_question", "Bạn muốn tìm loại cụ thể nào?")
                    response_text = (
                        f" 🔍 **KẾT QUẢ TÌM KIẾM**\n"
                        f" ✅ Tôi tìm thấy **{len(products)} sản phẩm** liên quan đến \"{user_message}\".\n"
                        f" ⭐ **Ghi chú:** {follow_up}\n"
                    )
                else:
                    response_text = (
                        f" ✅ **KẾT QUẢ TÌM KIẾM CHUYÊN SÂU**\n"
                        f"Tôi đã chọn lọc **{len(products)}** phù hợp nhất với yêu cầu của bạn.\n\n"
                    )
                    # ✅ NEW: Display ranking info if available
                    if ranking_summary['ranking_applied']:
                        response_text += f"\n\n ⭐ **{ranking_summary['boosted_items']} sản phẩm** được ưu tiên dựa trên lịch sử tìm kiếm."
                    
                    response_text += "\n**Bảng tóm tắt các sản phẩm:**\n"
                    headers = [
                        "STT",
                        "Tên sản phẩm",
                        "Mã sản phẩm",
                        "Danh mục",
                        "Danh mục phụ",
                        "Vật liệu chính",
                    ]
                    rows = []
                    for idx, prod_item in enumerate(products, 1):
                        rows.append([
                            idx,
                            prod_item.get("product_name", ""),
                            prod_item.get("headcode", ""),
                            prod_item.get("category", ""),
                            prod_item.get("sub_category", ""),
                            prod_item.get("material_primary", ""),
                        ])
                    suggested_prompts = [
                        f"💰 Phân tích chi phí {products[0]['headcode']}",
                        f"🧱 Xem cấu tạo vật liệu {products[0]['headcode']}",
                        f"🎯 So sánh với sản phẩm tương tự",
                        f"📞 Kết nối với chuyên viên tư vấn"
                    ]
                    tmp = generate_suggested_prompts(
                        "search_product_found",
                        {"query": user_message, "products": products}
                    )
                    suggested_prompts_mess = format_suggested_prompts(tmp)
                result_response = {
                    "response": response_text,
                    "products": products,
                    "suggested_prompts": suggested_prompts,
                    "ranking_summary": ranking_summary,  
                    "can_provide_feedback": True ,
                    "suggested_prompts_mess": suggested_prompts_mess,
                    "success": True
                }
        elif intent == "search_product_by_material":
            material_query = params.get("material_name") or params.get("material_primary") or params.get("keywords_vector")
            
            if not material_query:
                result_response = {
                    "response": "⚠️ Hiện tại tôi chưa nhận được thông tin về vật liệu bạn muốn tìm kiếm sản phẩm. ",
                    "suggested_prompts": [
                        "Sản phẩm làm từ gỗ sồi tự nhiên",
                        "Nội thất kim loại cho văn phòng",
                        "Bàn đá marble cao cấp",
                        "Ghế vải bọc chống thấm"
                    ],
                    "suggested_prompts_mess":suggested_prompts_mess
                }
            else:
                search_result = search_products_by_material(material_query, params)
                products = search_result.get("products", [])
                
                feedback_scores = get_feedback_boost_for_query(user_message, "product")
                if feedback_scores:
                    products = rerank_with_feedback(products, feedback_scores, "headcode")
                
                result_count = len(products)

                tmp = generate_suggested_prompts(
                        "search_product_not_found",
                        {"query": user_message}
                    )

                suggested_prompts_mess = format_suggested_prompts(tmp)    
                
                if not products:
                    matched_mats = search_result.get("matched_materials", [])
                    response_msg = " 🔍 **KẾT QUẢ TÌM KIẾM**\n\n"
                    response_msg += f" 💔  Thật xin lỗi tôi không tìm thấy sản phẩm phù hợp với yêu cầu của bạn trong cơ sở dữ liệu.\n"
                    response_msg += f" ⭐ **Ghi chú**: Tôi tìm được những vật liệu sau trong hệ thống: **{', '.join(matched_mats)}**, bạn có thể tham khảo!"

                    result_response = {
                        "response": response_msg,
                        "materials": matched_mats,
                        "suggested_prompts": [
                            "Tìm vật liệu thay thế phù hợp",
                            "Tư vấn sản phẩm custom theo yêu cầu",
                            "Xem danh mục vật liệu có sẵn"
                        ],
                        "materials": [],
                        "success": True,
                        "suggested_prompts_mess":suggested_prompts_mess
                    }
                    return result_response
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
                        f"• Dễ dàng bảo trì và vệ sinh"
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
                        ],
                        "suggested_prompts_mess":suggested_prompts_mess,
                        "success": True
                    }
        elif intent == "search_material_for_product":
            # 1. Get query from params or context
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
                # 2. Call search function
                search_result = search_materials_for_product(product_query, params)
                materials = search_result.get("materials", [])
                
                # 3. [NEW] Apply Feedback Ranking (Same as Intent 3)
                # Use user's original query to find similar feedback
                feedback_scores = get_feedback_boost_for_query(user_message, "material")
                if feedback_scores:
                    materials = rerank_with_feedback(materials, feedback_scores, "id_sap")
                
                # 4. [NEW] Get Ranking Summary for UI display
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
                    
                    # Display notification if Ranking available
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
                        "search_method": "cross_table_product_to_material", 
                        "ranking_summary": ranking_summary,
                        "can_provide_feedback": True,
                        "success": True
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
            
            # 🆕 APPLY FEEDBACK RANKING
            materials = apply_feedback_to_search(
                materials,
                user_message,
                search_type="material",
                id_key="id_sap"
            )
            
            # 🆕 Get ranking summary
            ranking_summary = get_ranking_summary(materials)
                        
            if not materials:
                try:
                    tmp = generate_suggested_prompts(
                        "search_material_not_found",
                        {"query": user_message}
                    )
                    suggested_prompts_mess = format_suggested_prompts(tmp)
                except Exception as e:
                    print(f"WARNING: Could not generate suggestions: {e}")
                    suggested_prompts_mess = "• Thử với từ khóa khác\n• Xem danh mục vật liệu\n• Liên hệ tư vấn viên"
                
                result_response = {
                    "response": (
                        f"🔍 **KHÔNG TÌM THẤY VẬT LIỆU PHÙ HỢP**\n\n"
                        f"Rất tiếc, tôi không tìm thấy vật liệu nào khớp với \"{user_message}\".\n\n"
                    ),
                    "suggested_prompts": [
                        "Vật liệu chịu nhiệt",
                        "Gỗ công nghiệp cao cấp",
                        "Đá tự nhiên trang trí",
                        "Vải bọc chống thấm"
                    ],
                    "materials": [],
                    "suggested_prompts_mess":suggested_prompts_mess,
                    "success": True
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
                # else:
                #     response_text = (
                #         f"✅ **TƯ VẤN VẬT LIỆU CHUYÊN SÂU**\n"
                #         f"Dựa trên nhu cầu của bạn, **{len(materials)} vật liệu** dưới đây đang được sử dụng phổ biến và phù hợp nhất.\n\n"
                #     )
                #     # 🆕 Hiển thị ranking info
                #     if ranking_summary['ranking_applied']:
                #         response_text += f"\n\n⭐ **{ranking_summary['boosted_items']} vật liệu** được ưu tiên."

                # for idx, mat in enumerate(materials, 1):
                #     price = f"{mat.get('price', 0):,.2f} / {mat.get('unit', '')}"
                #     material_name = mat["material_name"]
                #     feedback = (
                #         f"{mat['feedback_count']} lượt"
                #         if mat.get("has_feedback")
                #         else "-"
                #     )
                #     rows.append([
                #         idx,
                #         material_name,
                #         mat["id_sap"],
                #         mat["material_group"],
                #         price,
                #         feedback
                #     ])

                # Thêm phần link hình ảnh riêng (ngoài bảng)
                materials_with_images = [m for m in materials[:3] if m.get('image_url')]
                if materials_with_images:
                    response_text += "\n**📷 XEM ẢNH MẪU:**\n"
                    for mat in materials_with_images:
                        response_text += f"• [{mat['material_name']}]({mat.get('image_url', '#')})\n"
                
                tmp = generate_suggested_prompts(
                    "search_material_found",
                    {"query": user_message, "materials": materials}
                )
                suggested_prompts_mess = format_suggested_prompts(tmp)
                
                result_response = {
                    "response": response_text,
                    "materials": materials,
                    "suggested_prompts": [
                        "Vật liệu chịu nhiệt",
                        "Gỗ công nghiệp cao cấp",
                        "Đá tự nhiên trang trí",
                        "Vải bọc chống thấm"
                    ],
                    "ranking_summary": ranking_summary,  
                    "can_provide_feedback": True,
                    "show_comparison": True,
                    "suggested_prompts_mess":(
                        f"**Nếu các vật liệu trên chưa đúng ý, tôi có thể:**\n"
                        f"{suggested_prompts_mess}"
                    ),
                    "success": True
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
        
        elif intent == "list_products_by_category":
            result_response = list_products_by_category()
            if result_response.get("success"):
                products = result_response.get("products", [])
                try:
                    tmp = generate_suggested_prompts(
                        "list_products_by_category",
                        {"product_count": len(products), "categories": result_response.get("categories", [])}
                    )
                    suggested_prompts_mess = format_suggested_prompts(tmp)
                    result_response["suggested_prompts_mess"] = suggested_prompts_mess
                except Exception as e:
                    print(f"WARNING: Could not generate suggestions: {e}")
                    result_response["suggested_prompts"] = [
                        "Tìm sản phẩm cụ thể",
                        "Xem bảng giá",
                        "Tư vấn thiết kế"
                    ]
        
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
        
        listProducts = listProducts or result_response.get("products", []) or result_response.get("materials", [])
        # Save chat history
        histories.save_chat_to_histories(
            email="test@gmail.com",
            session_id=msg.session_id,
            question=user_message,
            messages=listProducts,
            answer=result_response.get("response", "")
        )
        
        if result_response:
            result_response["query"] = user_message 
            
        return result_response
    
    except TimeoutError as e:
        print(f"Timeout Error: {e}")
        return {
            "response": (
                "⏱️ **YÊU CẦU MẤT QUÁ LÂU**\n\n"
                "Xin lỗi, hệ thống không thể xử lý yêu cầu của bạn trong thời gian cho phép.\n\n"
                "**💡 Vui lòng thử:**\n"
                "• Đơn giản hóa yêu cầu tìm kiếm\n"
                "• Thử lại sau ít phút\n"
                "• Liên hệ trực tiếp với chuyên viên tư vấn"
            ),
            "success": False,
            "suggested_prompts": [
                "🔍 Tìm sản phẩm đơn giản",
                "🧱 Xem danh mục vật liệu",
                "💬 Liên hệ tư vấn viên"
            ]
        }
    except Exception as e:
        print(f"Server Error: {e}")
        import traceback
        traceback.print_exc()
        
        # Check if it's a timeout-related error
        error_str = str(e).lower()
        print(f"Error string: {error_str}")
        if "timeout" in error_str or "timed out" in error_str:
            return {
                "response": (
                    "⏱️ **KHÔNG TÌM THẤY KẾT QUẢ PHÙ HỢP**\n\n"
                    "Hệ thống không tìm thấy danh sách phù hợp với yêu cầu của bạn.\n\n"
                    "**💖 Ghi chú:**\n"
                    "• Thử từ khóa tìm kiếm khác\n"
                    "• Xem các danh mục sản phẩm có sẵn\n"
                    "• Liên hệ chuyên viên để được tư vấn chi tiết"
                ),
                "success": False,
                "suggested_prompts": [
                    "Xem danh mục sản phẩm",
                    "Tìm theo vật liệu",
                    "Liên hệ tư vấn viên"
                ]
            }
        
        return {
            "response": (
                "⚠️ **LỖI HỆ THỐNG**\n\n"
                "Xin lỗi, đã có lỗi xảy ra khi xử lý yêu cầu của bạn.\n\n"
                "Vui lòng thử lại sau ít phút hoặc liên hệ với bộ phận hỗ trợ."
            ),
            "success": False,
            "suggested_prompts": [
                # "Thử lại",
                "Xem danh mục",
                "Liên hệ hỗ trợ"
            ]
        }

@router.post("/batch/products", tags=["Chat qwen"])
def batch_product_operations(request: BatchProductRequest):
    """
    🔥 Xử lý batch operations cho nhiều sản phẩm
    Operations: detail, materials, cost
    """
    try:
        if not request.product_headcodes:
            return {
                "response": "⚠️ Vui lòng chọn ít nhất 1 sản phẩm",
                "success": False
            }
        
        headcodes = request.product_headcodes
        operation = request.operation
        
        print(f"INFO: Batch {operation}: {len(headcodes)} products")
        
        # ========== OPERATION: CHI TIẾT SẢN PHẨM ==========
        if operation == "detail":
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            cur.execute("""
                SELECT headcode, product_name, category, sub_category, material_primary, project, unit
                FROM products_qwen
                WHERE headcode = ANY(%s)
                ORDER BY product_name
            """, (headcodes,))
            
            products = cur.fetchall()
            conn.close()
            
            if not products:
                return {
                    "response": "ERROR: Không tìm thấy sản phẩm",
                    "success": False
                }
            
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
                "products": [dict(p) for p in products],
                "success": True
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
                INNER JOIN products_qwen p ON pm.product_headcode = p.headcode
                INNER JOIN materials m ON pm.material_id_sap = m.id_sap
                WHERE p.headcode = ANY(%s)
                ORDER BY p.product_name, m.material_name
            """, (headcodes,))
            
            records = cur.fetchall()
            conn.close()
            
            if not records:
                return {
                    "response": "WARNING: Các sản phẩm này chưa có định mức vật liệu",
                    "success": False
                }
            
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
            response = f" 🎉 **ĐỊNH MỨC VẬT LIỆU - {len(products_dict)} SẢN PHẨM:**\n\n"
            
            for prod_data in products_dict.values():
                response += f"### 📦 {prod_data['product_name']} (`{prod_data['headcode']}`)\n\n"
                
                total_cost = sum(m['total'] for m in prod_data['materials'])
                # Tạo bảng Markdown cho vật liệu
                headers = [
                    "STT",
                    "Tên vật liệu",
                    "Nhóm",
                    "Số lượng",
                    "Đơn giá (VNĐ)",
                    "Thành tiền (VNĐ)"
                ]
                rows = []

                for idx, mat in enumerate(prod_data['materials'][:15], 1):
                    rows.append([
                        idx,
                        mat['name'],
                        mat['group'],
                        f"{mat['quantity']} {mat['unit']}",
                        f"{mat['price']:,.0f}",
                        f"{mat['total']:,.0f}"
                    ])

                # response += build_markdown_table(headers, rows) + "\n\n"
                
                if len(prod_data['materials']) > 15:
                    response += f"*...và {len(prod_data['materials'])-15} vật liệu khác*\n\n"
                
                response += f"💰 **Tổng NVL ({prod_data['headcode']}): {total_cost:,.0f} VNĐ**\n\n"
                response += "---\n\n"
            
            # Tạo materials list để UI có thể render cards
            all_materials = []
            for prod_data in products_dict.values():
                all_materials.extend(prod_data['materials'])
            
            # Tạo suggested prompts
            first_product_name = ""
            if len(products_dict) > 0:
                first_product_name = list(products_dict.values())[0]['product_name']

            suggested_prompts = generate_suggested_prompts(
                "batch_materials",
                {
                    "product_count": len(products_dict),
                    "first_product": first_product_name,
                },
            )
            suggested_prompts_mess = format_suggested_prompts(suggested_prompts)
            response += suggested_prompts_mess

            return {
                "response": response,
                "products_materials": products_dict,
                "materials": all_materials,
                "suggested_prompts": suggested_prompts,
                "success": True
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
                INNER JOIN products_qwen p ON pm.product_headcode = p.headcode
                INNER JOIN materials m ON pm.material_id_sap = m.id_sap
                WHERE p.headcode = ANY(%s)
                ORDER BY p.product_name
            """, (headcodes,))
            
            records = cur.fetchall()
            conn.close()
            
            if not records:
                return {
                    "response": "WARNING: Không có dữ liệu định mức",
                    "success": False
                }
            
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
                response += f"   • {len(prod_data['materials_detail'])} loại vật liệu"
                response += "\n\n---\n\n"
                
                grand_total += prod_data['material_cost']
            
            response += f"## 💵 TỔNG CHI PHÍ NVL: {grand_total:,.0f} VNĐ\n\n"
            response += "📋 *Chi phí được tính từ giá nguyên vật liệu gần nhất*"
            
            # Tạo suggested prompts
            first_headcode = ""
            if len(products_cost) > 0:
                first_headcode = list(products_cost.values())[0]['headcode']

            suggested_prompts = generate_suggested_prompts(
                "batch_cost",
                {
                    "product_count": len(products_cost),
                    "first_headcode": first_headcode,
                },
            )
            suggested_prompts_mess = format_suggested_prompts(suggested_prompts)
            response += suggested_prompts_mess

            return {
                "response": response,
                "products_cost": products_cost,
                "grand_total": grand_total,
                "suggested_prompts": suggested_prompts,
                "success": True
            }
        
        else:
            return {
                "response": "ERROR: Operation không hợp lệ",
                "success": False
            }
    
    except Exception as e:
        print(f"ERROR: Batch operation error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "response": f"ERROR: {str(e)}",
            "success": False
        }

# ================================================================================================
# MODULE 1: CONSOLIDATED BOM REPORT
# ================================================================================================

@router.post("/report/consolidated", tags=["Chat qwen"])
def create_consolidated_report(request: ConsolidatedBOMRequest):

    try:
        if not request.product_headcodes or len(request.product_headcodes) == 0:
            return {
                "message": "WARNING: Vui lòng chọn ít nhất 1 sản phẩm",
                "success": False
            }
        
        print(f"INFO: Generating report for {len(request.product_headcodes)} products...")
        
        # Tạo file Excel
        excel_buffer = generate_consolidated_report(request.product_headcodes)
        
        # Lưu lịch sử (Optional)
        # if request.session_id:
            # save_chat_history(
            #     session_id=request.session_id,
            #     user_message=f"[REPORT] Tổng hợp {len(request.product_headcodes)} sản phẩm",
            #     bot_response="Đã tạo báo cáo Excel",
            #     intent="generate_report",
            #     params={"products": request.product_headcodes},
            #     result_count=len(request.product_headcodes),
            #     search_type="report"
            # )

        filename = f"BOM_Consolidated_{len(request.product_headcodes)}SP_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return StreamingResponse(
            excel_buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
        
    except ValueError as e:
        return {
            "message": f"ERROR: {str(e)}",
            "success": False
        }
    except Exception as e:
        print(f"ERROR: Report generation error: {e}")
        import traceback
        traceback.print_exc()
        return {
            "message": f"ERROR: {str(e)}", 
            "success": False
        }

@router.post("/track/view", tags=["Chat qwen"])
def track_product_view(request: TrackingRequest):

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Lấy embedding của sản phẩm
        cur.execute("""
            SELECT description_embedding 
            FROM products_qwen 
            WHERE headcode = %s AND description_embedding IS NOT NULL
        """, (request.product_headcode,))
        
        result = cur.fetchone()
        
        if not result:
            conn.close()
            return {
                "message": "Product not found or no embedding",
                "success": False
            }
        
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
        
        print(f"SUCCESS: Tracked VIEW: {request.product_headcode} by {request.session_id[:8]}")
        
        return {
            "message": "SUCCESS: Tracked successfully", "type": "view", 
            "success": True
        }
        
    except Exception as e:
        print(f"ERROR: Tracking error: {e}")
        return {
            "message": f"ERROR: {str(e)}",
            "success": False
        }

@router.post("/track/reject", tags=["Chat qwen"])
def track_product_reject(request: TrackingRequest):
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT description_embedding 
            FROM products_qwen 
            WHERE headcode = %s AND description_embedding IS NOT NULL
        """, (request.product_headcode,))
        
        result = cur.fetchone()
        
        if not result:
            conn.close()
            return {
                "message": "Product not found",
                "success": False
            }
        
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
        
        print(f"ERROR: Tracked REJECT: {request.product_headcode} by {request.session_id[:8]}")
        
        return {
            "message": "SUCCESS: Tracked rejection", 
            "type": "reject",
            "success": True
        }
        
    except Exception as e:
        print(f"ERROR: Tracking error: {e}")
        return {
            "message": f"ERROR: {str(e)}",
            "success": False
        }
