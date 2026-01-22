
# import json
# import re  
# from datetime import datetime
# from typing import Dict, List

# import google.generativeai as genai
# import psycopg2
# from fastapi import APIRouter
# from fastapi.responses import StreamingResponse
# from psycopg2.extras import RealDictCursor

# from config import settings
# from feedbackapi.feedback import get_feedback_boost_for_query
# from historiesapi import histories
# from historiesapi.histories import router as history_router
# from imageapi.media import router as media_router
# from rankingapi.ranking import (apply_feedback_to_search, get_ranking_summary,
#                                 rerank_with_feedback)

# from .embeddingapi import generate_embedding_qwen
# from .textfunc import (calculate_product_total_cost, call_gemini_with_retry,
#                         extract_product_keywords, format_search_results,
#                         format_suggested_prompts, generate_consolidated_report,
#                         get_latest_material_price, search_materials_for_product,
#                         search_products_hybrid, search_products_keyword_only)
# from .unit import (BatchProductRequest, ChatMessage, ConsolidatedBOMRequest,
#                     TrackingRequest)

# # --- TỰ ĐỊNH NGHĨA REGEX ĐỂ LỌC KÝ TỰ LỖI ---
# # Regex này lọc các ký tự ASCII điều khiển (Control chars) không hợp lệ trong file Excel (XML)
# # Bao gồm: ASCII 0-8, 11-12, 14-31
# ILLEGAL_CHARACTERS_RE = re.compile(r'[\000-\010]|[\013-\014]|[\016-\037]')

# So_Cau_Goi_Y = 3  # Số câu gợi ý mặc định

# # ✅ SESSION CACHE để lưu suggested_prompts
# session_suggested_prompts_cache = {}

# def build_markdown_table(headers: List[str], rows: List[List[str]]) -> str:
#     """Tạo bảng Markdown từ header + rows để frontend HTML render + CSS đẹp.

#     Mỗi ô đã được format sẵn (ví dụ: số có dấu phẩy) trước khi truyền vào.
#     """
#     if not headers:
#         return ""

#     # Dòng header
#     header_row = "| " + " | ".join(str(h) for h in headers) + " |"
#     # Dòng căn lề cơ bản, frontend có thể dùng CSS để chỉnh tiếp
#     separator_row = "| " + " | ".join("---" for _ in headers) + " |"

#     body_rows = [
#         "| " + " | ".join(str(cell) for cell in row) + " |" for row in rows
#     ]

#     return "\n".join([header_row, separator_row] + body_rows)

# def get_db():
#     return psycopg2.connect(**settings.DB_CONFIG)

# genai.configure(api_key=settings.My_GOOGLE_API_KEY)

# router = APIRouter()
# # ================================================================================================
# # FUNCTION DEFINITIONS
# # ================================================================================================

# def generate_suggested_prompts(context_type: str, context_data: Dict = None, count: int = 4) -> List[str]:
    
#     model = genai.GenerativeModel("gemini-2.5-flash")
    
#     prompt = f"""
#         Bạn là chuyên viên tư vấn nội thất cao cấp của AA Corporation.
#         Nhiệm vụ: Tạo {count} câu gợi ý TỰ NHIÊN, CHUYÊN NGHIỆP, PHÙ HỢP với ngữ cảnh, dạng câu HỎI.

#         NGỮ CẢNH: {context_type}.
#         cách xưng hô: tôi và bạn.
#         """

#     if context_type == "greeting":
#         prompt += """
#         User vừa mới vào chat. Tạo 4 câu gợi ý giúp user bắt đầu:
#         - Tìm sản phẩm phổ biến
#         - Tư vấn vật liệu
#         - Hỏi về giá
#         - Hỗ trợ khác
#         YÊU CẦU:
#         - Ngắn gọn, rõ ràng (8-12 từ)
#         - Không dùng emoji
#         - Tự nhiên như lời nói
#         - Đa dạng chủ đề
#         """
    
#     elif context_type == "search_product_found":
#         products_info = context_data.get("products", [])
#         query = context_data.get("query", "")
#         prompt += f"""
#         User vừa tìm: "{query}"
#         Tìm thấy {len(products_info)} sản phẩm.
#         Sản phẩm đầu tiên: {products_info[0].get('product_name', '')} ({products_info[0].get('headcode', '')})
#         Tạo {So_Cau_Goi_Y} gợi ý trong những HÀNH ĐỘNG TIẾP THEO:
#         - Xem chi tiết/giá sản phẩm cụ thể
#         - So sánh hoặc tìm tương tự
#         - Hỏi về vật liệu/cấu tạo
#         - Tư vấn thêm
#         YÊU CẦU:
#         - Cụ thể, dựa trên kết quả tìm kiếm
#         - Có tên sản phẩm/mã nếu cần
#         - Tự nhiên, không máy móc
#         - Không dùng emoji
#         """
    
#     elif context_type == "search_product_broad":
#         query = context_data.get("query", "")
#         prompt += f"""
#         User tìm quá rộng: "{query}"
#         Cần thu hẹp phạm vi.
#         Tạo {So_Cau_Goi_Y} gợi ý trong những câu hỏi GỢI Ý giúp user CỤ THỂ HÓA:
#         - Về mục đích sử dụng
#         - Về phong cách/chất liệu
#         - Về kích thước/không gian
#         - Về ngân sách
#         YÊU CẦU:
#         - Dạng câu hỏi tự nhiên
#         - Liên quan trực tiếp đến "{query}"
#         - Giúp thu hẹp tìm kiếm
#         - Không dùng emoji
#         """
    
#     elif context_type == "search_product_not_found":
#         query = context_data.get("query", "")
#         prompt += f"""
#         User tìm: "{query}" - KHÔNG TÌM THẤY
#         Tạo {So_Cau_Goi_Y} gợi ý trong những GIẢI PHÁP:
#         - Tìm từ khóa tương tự
#         - Xem danh mục liên quan
#         - Tư vấn sản phẩm thay thế
#         - Liên hệ tư vấn
#         YÊU CẦU:
#         - Tích cực, giúp đỡ
#         - Cụ thể, có hướng giải quyết
#         - Không dùng emoji
#         """

#     elif context_type == "search_material_found":
#         materials_info = context_data.get("materials", [])
#         query = context_data.get("query", "")
#         prompt += f"""
#         User tìm vật liệu: "{query}"
#         Tìm thấy {len(materials_info)} vật liệu.
#         Vật liệu đầu: {materials_info[0].get('material_name', '')}
#         Tạo {So_Cau_Goi_Y} gợi ý trong những HÀNH ĐỘNG:
#         - Xem chi tiết vật liệu
#         - So sánh giá/tính năng
#         - Xem sản phẩm dùng vật liệu này
#         - Tư vấn vật liệu thay thế
#         YÊU CẦU:
#         - Có tên vật liệu cụ thể
#         - Hành động rõ ràng
#         - Không dùng emoji
#         """

#     elif context_type == "product_materials":
#         product_name = context_data.get("product_name", "")
#         headcode = context_data.get("headcode", "")
#         prompt += f"""
#         User đang xem định mức vật liệu của:
#         {product_name} ({headcode})
#         Tạo {So_Cau_Goi_Y} gợi ý trong những việc TIẾP THEO:
#         - Xem giá/chi phí
#         - So sánh với sản phẩm khác
#         - Tìm vật liệu thay thế
#         - Xuất báo cáo
#         YÊU CẦU:
#         - Dùng mã {headcode} nếu cần
#         - Hành động cụ thể
#         - Không dùng emoji
#         """
    
#     elif context_type == "product_cost":
#         product_name = context_data.get("product_name", "")
#         headcode = context_data.get("headcode", "")
#         prompt += f"""
#         User đang xem chi phí của:
#         {product_name} ({headcode})
#         Tạo {So_Cau_Goi_Y} gợi ý trong những việc sau:
#         - Xem chi tiết vật liệu
#         - So sánh giá với SP khác
#         - Tối ưu chi phí
#         - Xuất báo cáo
#         YÊU CẦU:
#         - Liên quan đến chi phí/giá
#         - Không dùng emoji
#         """
    
#     elif context_type == "get_product_materials":
#         product_name = context_data.get("product_name", "")
#         headcode = context_data.get("headcode", "")
#         prompt += f"""
#         User đang xem chi phí của:
#         {product_name} ({headcode})
#         Tạo {So_Cau_Goi_Y} gợi ý trong những việc sau:
#         - tên gọi của những sản phẩm tương tự
#         - vật liệu phổ biến dùng cho sản phẩm này
#         - tìm sản phẩm thay thế
#         YÊU CẦU:
#         - Liên quan đến chi phí/giá
#         - Không dùng emoji
#         """

#     elif context_type == "calculate_product_cost":
#         product_name = context_data.get("product_name", "")
#         headcode = context_data.get("headcode", "")
#         prompt += f"""
#         User đang xem chi phí của:
#         {product_name} ({headcode})
#         Tạo {So_Cau_Goi_Y} gợi ý trong những việc sau:
#         - tên gọi của những sản phẩm tương tự
#         - vật liệu phổ biến dùng cho sản phẩm này
#         - tìm sản phẩm thay thế
#         YÊU CẦU:
#         - Liên quan đến chi phí/giá
#         - Không dùng emoji
#         """

#     elif context_type == "batch_materials":
#         product_count = context_data.get("product_count", 0)
#         first_product = context_data.get("first_product", "")
#         prompt += f"""
#         User vừa xem định mức {product_count} sản phẩm.
#         Sản phẩm đầu: {first_product}
#         Tạo {So_Cau_Goi_Y} gợi ý trong những việc sau:
#         - Xem báo cáo chi phí
#         - Xuất Excel
#         - Phân tích chi tiết
#         - So sánh giá vật liệu
#         YÊU CẦU:
#         - Phù hợp với batch operation
#         - Không dùng emoji
#         """
    
#     elif context_type == "batch_cost":
#         product_count = context_data.get("product_count", 0)
#         first_headcode = context_data.get("first_headcode", "")
#         prompt += f"""
#         User vừa xem chi phí {product_count} sản phẩm.
#         Tạo {So_Cau_Goi_Y} gợi ý trong những việc sau:
#         - Xem định mức chi tiết
#         - Xuất báo cáo Excel
#         - Phân tích vật liệu
#         - Tìm vật liệu giá tốt hơn
#         YÊU CẦU:
#         - Liên quan đến tối ưu chi phí
#         - Không dùng emoji
#         """
    
#     else:
#         prompt += """
#         Tạo 4 gợi ý chung:
#         - Tìm sản phẩm
#         - Tìm vật liệu  
#         - Xem giá
#         - Trợ giúp
#         """
            
#     prompt += """
#     OUTPUT FORMAT (JSON array only):
#     [
#         "Gợi ý 1 - tự nhiên, không emoji",
#         "Gợi ý 2 - tự nhiên, không emoji",
#         "Gợi ý 3 - tự nhiên, không emoji",
#         "**Trên đây là các gợi ý phù hợp với bạn, Bạn có thể hỏi tôi bất cứ điều gì khác!**"
#     ]
#     """
#     try:
#         response_text = call_gemini_with_retry(model, prompt)
#         if not response_text:
#             return _get_fallback_prompts(context_type)
        
#         clean_text = response_text.strip()
#         if "```json" in clean_text:
#             clean_text = clean_text.split("```json")[1].split("```")[0].strip()
#         elif "```" in clean_text:
#             clean_text = clean_text.split("```")[1].split("```")[0].strip()
        
#         prompts = json.loads(clean_text)
#         return prompts[:count]
        
#     except Exception as e:
#         print(f"WARNING: Prompt generation failed: {e}")
#         return _get_fallback_prompts(context_type)

# def _get_fallback_prompts(context_type: str) -> List[str]:
#     """Fallback prompts nếu genai thất bại"""
#     fallbacks = {
#         "greeting": [
#             "Tìm bàn làm việc hiện đại",
#             "Xem các loại gỗ cao cấp",
#             "Tư vấn báo giá sản phẩm",
#             "Danh sách vật liệu phổ biến"
#         ],
#         "search_product_found": [
#             "Xem chi tiết sản phẩm đầu tiên",
#             "So sánh với mẫu tương tự",
#             "Phân tích vật liệu sử dụng",
#             "Tư vấn thêm về sản phẩm"
#         ],
#         "search_material_found": [
#             "Xem chi tiết vật liệu đầu tiên",
#             "So sánh giá các loại vật liệu",
#             "Xem sản phẩm dùng vật liệu này",
#             "Tư vấn vật liệu thay thế"
#         ]
#     }
#     return fallbacks.get(context_type, [
#         "Tìm sản phẩm mới",
#         "Tìm nguyên vật liệu",
#         "Xem bảng giá",
#         "Trợ giúp khác"
#     ])

# def get_intent_and_params(user_message: str, context: Dict) -> Dict:
#     """AI Router với khả năng Reasoning & Soft Clarification"""
#     model = genai.GenerativeModel("gemini-2.5-flash")
    
#     context_info = ""
#     if context.get("current_products"):
#         products = context["current_products"]
#         context_info = f"\nCONTEXT (User vừa xem): {len(products)} sản phẩm. SP đầu tiên: {products[0]['headcode']} - {products[0]['product_name']}"
#     elif context.get("current_materials"):
#         materials = context["current_materials"]
#         context_info = f"\nCONTEXT (User vừa xem): {len(materials)} vật liệu. VL đầu tiên: {materials[0]['material_name']}"
    
#     prompt = f"""
#     Bạn là AI Assistant thông minh của AA Corporation (Nội thất cao cấp).
    
#     INPUT: "{user_message}"
#     {context_info}

#     NHIỆM VỤ: Phân tích Intent và Parameters.
    
#     QUY TẮC SUY LUẬN (LOGIC):
#     1. **Intent Detection**: Xác định user muốn:
#        - **search_product**: Tìm kiếm sản phẩm (VD: "Tìm bàn", "Có bàn nào", "Cho tôi xem ghế")
#        - **query_product_materials**: Xem vật liệu của SẢN PHẨM (VD: "Vật liệu của bàn B001", "Phân tích vật liệu SP này")
#        - **calculate_product_cost**: Tính giá/báo giá SẢN PHẨM (VD: "Giá bàn B001", "Tính giá sản phẩm", "Báo giá")

#        **MATERIAL FLOW:**
#        - **search_material**: Tìm kiếm NGUYÊN VẬT LIỆU (VD: "Tìm gỗ sồi", "Có loại da nào", "Đá marble", "Vật liệu làm bàn")
#        - **query_material_detail**: Xem chi tiết VẬT LIỆU + sản phẩm sử dụng (VD: "Chi tiết gỗ sồi", "Xem vật liệu này dùng ở đâu")
#        - **list_material_groups**: Liệt kê nhóm vật liệu (VD: "Các loại gỗ", "Danh sách đá")

#         ----------------------------------------------------------------
#        **[NEW] CROSS-TABLE INTENTS (BỔ SUNG – KHÔNG THAY ĐỔI LOGIC CŨ):**
#         - **search_product_by_material**: Tìm sản phẩm LÀM TỪ vật liệu cụ thể
#         Ví dụ: "Tìm bàn làm từ đá marble", "Tủ gỗ teak", "Ghế da thật"

#         - **search_material_for_product**: Tìm vật liệu ĐỂ LÀM sản phẩm cụ thể
#         Ví dụ: "Vật liệu làm bàn tròn", "Nguyên liệu ghế sofa", "Đá làm bàn"

#        **PHÂN BIỆT RÕ (ƯU TIÊN TUÂN THỦ):**
#         - "Tìm bàn gỗ" → search_product
#         - "Tìm bàn LÀM TỪ gỗ teak" → search_product_by_material
#         - "Tìm gỗ" → search_material
#         - "Tìm vật liệu ĐỂ LÀM bàn" → search_material_for_product
#         ----------------------------------------------------------------

#         - **greeting**: Chào hỏi (VD: "Xin chào", "Hello", "Hi")
#         - **unknown**: Không rõ ý định
    
#     2. **Entity Type Detection**: 
#         - Phân biệt: User đang nói về SẢN PHẨM hay VẬT LIỆU?
#         - Keyword: "sản phẩm", "bàn", "ghế", "sofa" → PRODUCT
#         - Keyword: "vật liệu", "nguyên liệu", "gỗ", "da", "đá", "vải" → MATERIAL
#         - "giá" + context sản phẩm → calculate_product_cost
#         - "giá" + context vật liệu → query_material_detail
    
#     3. **Broad Query Detection**: 
#         - Nếu User chỉ nói danh mục lớn (VD: "Tìm bàn", "Ghế", "Đèn", "Tìm gỗ") mà KHÔNG có tính chất cụ thể:
#             -> Set `is_broad_query`: true
#             -> Tạo `follow_up_question`: Ba câu hỏi ngắn gợi ý user thu hẹp phạm vi
#         - Nếu User đã cụ thể (VD: "Bàn ăn tròn", "Ghế gỗ sồi", "Đá marble trắng"):
#             -> Set `is_broad_query`: false
#             -> `follow_up_question`: null
    
#     4. **Parameter Extraction**:
#        **For PRODUCTS:**
#         - `category`: Danh mục sản phẩm
#         - `sub_category`: Danh mục phụ
#         - `material_primary`: Vật liệu chính
#         - `keywords_vector`: Mô tả đầy đủ để search vector
#         - `headcode`: Mã sản phẩm (nếu có trong INPUT hoặc Context)

#        **For MATERIALS:**
#         - `material_name`: Tên vật liệu (VD: "gỗ sồi", "da thật")
#         - `material_group`: Nhóm vật liệu (VD: "Gỗ", "Da", "Đá", "Vải")
#         - `material_subgroup`: Nhóm con
#         - `keywords_vector`: Mô tả đặc tính để search (VD: "gỗ làm bàn ăn cao cấp màu nâu")
#         - `id_sap`: Mã vật liệu SAP (nếu có)
#         - `usage_context`: Ngữ cảnh sử dụng (VD: "làm bàn", "bọc ghế")
    
#     5. **Context Awareness**:
#         - Nếu User dùng từ đại từ ("cái này", "nó", "sản phẩm đó", "vật liệu này"), hãy lấy từ Context
#         - Nếu User hỏi về giá/vật liệu mà không nói rõ, ưu tiên lấy item đầu tiên trong Context

#     OUTPUT FORMAT (JSON ONLY - no markdown backticks):
#     {{
#         "intent": "search_product|search_product_by_material|search_material_for_product|query_product_materials|calculate_product_cost|search_material|query_material_detail|list_material_groups|greeting|unknown",
#         "entity_type": "product|material|unknown",
#         "params": {{
#             "category": "String hoặc null",
#             "sub_category": "String hoặc null",
#             "material_primary": "String hoặc null",
#             "material_name": "String hoặc null",
#             "material_group": "String hoặc null",
#             "material_subgroup": "String hoặc null",
#             "keywords_vector": "Từ khóa mô tả đầy đủ",
#             "headcode": "String hoặc null",
#             "id_sap": "String hoặc null",
#             "usage_context": "String hoặc null"
#         }},
#         "is_broad_query": boolean,
#         "follow_up_question": "String hoặc null",
#         "suggested_actions": ["String 1", "String 2"]
#     }}
#     """
    
#     response_text = call_gemini_with_retry(model, prompt)
#     if not response_text:
#         return {
#             "intent": "error",
#             "raw": "No response from AI",
#             "success": False
#         }
    
#     try:
#         clean_text = response_text.strip()
        
#         if "```json" in clean_text:
#             clean_text = clean_text.split("```json")[1].split("```")[0].strip()
#         elif "```" in clean_text:
#             clean_text = clean_text.split("```")[1].split("```")[0].strip()
        
#         result = json.loads(clean_text)
        
#         if result["intent"] in ["calculate_product_cost", "query_product_materials"]:
#             if not result["params"].get("headcode"):
#                 match = re.search(r'\b([A-Z0-9]+-?[A-Z0-9]+)\b', user_message.upper())
#                 if match:
#                     result["params"]["headcode"] = match.group(1)
#         return result
        
#     except json.JSONDecodeError as e:
#         print(f"JSON Parse Error: {e} - Raw: {response_text}")
#         return {
#             "intent": "error", 
#             "raw": response_text,
#             "success": False
#         }
        
#     except Exception as e:
#         print(f"Parse Error: {e}")
#         return {
#             "intent": "error", "raw": response_text,
#             "success": False
#         }

# def search_products(params: Dict, session_id: str = None):
#     """Multi-tier: HYBRID -> Vector -> Keyword"""
    
#     # TIER 1: Thử Hybrid trước
#     try:
#         result = search_products_hybrid(params)
#         if result.get("products"):
#             # Cập nhật total_cost cho các sản phẩm trong hybrid search
#             for product in result["products"]:
#                 product["total_cost"] = calculate_product_total_cost(product["headcode"])
                
#             products = result["products"]
            
#             # ========== STEP 1: BASE SCORES ==========
#             for product in products:
#                 product['base_score'] = float(product.get('similarity', 0.5))
            
#             # ========== STEP 2: PERSONALIZATION ==========
#             # ✅ CHỈ áp dụng nếu có session_id VÀ user có history
#             has_personalization = False
            
#             if session_id:
#                 print(f"\n🎯 Personalization for {session_id[:8]}...")
                
#             if not has_personalization:
#                 for product in products:
#                     product['personal_score'] = 0.5
            
#             print(f"✅ Personalization done\n")
            
#             # ========== STEP 3: FEEDBACK SCORES ==========
#             print(f"MAIN: Feedback Scoring...")
            
#             feedback_dict = get_feedback_boost_for_query(
#                 params.get("keywords_vector", ""),
#                 search_type="product",
#                 similarity_threshold=0.85
#             )
            
#             max_feedback = max(feedback_dict.values()) if feedback_dict else 1.0
            
#             for product in products:
#                 headcode = product.get('headcode')
#                 raw_feedback = feedback_dict.get(headcode, 0)
                
#                 product['feedback_score'] = float(raw_feedback / max_feedback) if max_feedback > 0 else 0.0
#                 product['feedback_count'] = float(raw_feedback)
            
#             print(f"SUCCESS: Feedback Scoring done\n")
            
#             # ========== STEP 4: WEIGHTED SUM ==========
#             # print(f"MAIN: Final Ranking (Weighted Sum)...")
            
#             # ✅ ADAPTIVE WEIGHTS
#             if has_personalization:
#                 # User có history → ưu tiên personalization
#                 W_BASE = 0.3
#                 W_PERSONAL = 0.5
#                 W_FEEDBACK = 0.2
#             else:
#                 # User mới → ưu tiên base + social proof
#                 W_BASE = 0.6
#                 W_PERSONAL = 0.0  
#                 W_FEEDBACK = 0.4
            
#             for idx, product in enumerate(products):
#                 base = product.get('base_score', 0.5)
#                 personal = product.get('personal_score', 0.5)
#                 feedback = product.get('feedback_score', 0.0)
                
#                 # ✅ Chỉ tính personal nếu has_personalization
#                 if has_personalization:
#                     final_score = (W_BASE * base) + (W_PERSONAL * personal) + (W_FEEDBACK * feedback)
#                 else:
#                     final_score = (W_BASE * base) + (W_FEEDBACK * feedback)
                
#                 product['final_score'] = float(final_score)
#                 product['original_rank'] = idx + 1
                
#                 # print(f"  {product['headcode']}: "
#                 #         f"base={base:.3f} | pers={personal:.3f} | fb={feedback:.3f} "
#                 #         f"→ final={final_score:.3f}")
            
#             # ========== STEP 5: SORT FINAL ==========
#             products.sort(key=lambda x: x.get('final_score', 0), reverse=True)
            
#             for idx, product in enumerate(products):
#                 product['final_rank'] = idx + 1
                
#                 if product.get('feedback_count', 0) > 0:
#                     product['has_feedback'] = True
            
#             print(f"✅ Final Ranking complete\n")
            
#             result["products"] = products
#             result["ranking_summary"] = get_ranking_summary(products)
#             result["can_provide_feedback"] = True
            
#             return result
#     except Exception as e:
#         print(f"WARNING: TIER 1 failed: {e}")
    
#     # TIER 2 & 3: GIỮ NGUYÊN CODE CŨ (Fallback)
#     conn = get_db()
#     cur = conn.cursor(cursor_factory=RealDictCursor)
    
#     if params.get("keywords_vector"):
#         query_text = params["keywords_vector"]
#     else:
#         query_parts = []
#         if params.get("category"): query_parts.append(params["category"])
#         if params.get("sub_category"): query_parts.append(params["sub_category"])
#         if params.get("material_primary"): query_parts.append(params["material_primary"])
#         query_text = " ".join(query_parts) if query_parts else "nội thất"

#     query_vector = generate_embedding_qwen(query_text)
    
#     if not query_vector:
#         conn.close()
#         return search_products_keyword_only(params)
    
#     # TIER 2: Pure Vector
#     try:
#         sql = """
#             SELECT headcode, product_name, category, sub_category, 
#                     material_primary, project, project_id,
#                     (description_embedding <=> %s::vector) as distance
#             FROM products_qwen
#             WHERE description_embedding IS NOT NULL
#             ORDER BY distance ASC
#             LIMIT 10
#         """
#         cur.execute(sql, [query_vector])
#         results = cur.fetchall()
        
#         if results:
#             print(f"SUCCESS: TIER 2: {len(results)} products")
#             products = format_search_results(results[:8])
#             conn.close()
#             return {
#                 "products": products, 
#                 "search_method": "vector_no_filter",
#                 "success": True
#             }
#     except Exception as e:
#         print(f"WARNING: TIER 2 failed: {e}")
    
#     # TIER 3: Keyword
#     conn.close()
#     return search_products_keyword_only(params)

# def search_products_by_material(material_query: str, params: Dict):
#     """
#     🔍 TÌM SẢN PHẨM ĐƯỢC LÀM TỪ VẬT LIỆU CỤ THỂ
#     Ví dụ: "Tìm bàn làm từ đá marble", "Tủ gỗ teak"
    
#     Logic: 
#     1. Tìm materials phù hợp với query (vector search)
#     2. JOIN product_materials để lấy products sử dụng material đó
#     3. Rank products theo độ phù hợp
#     """
#     conn = get_db()
#     cur = conn.cursor(cursor_factory=RealDictCursor)
    
#     print(f"INFO: Cross-table search: Products made from '{material_query}'")
    
#     # Bước 1: Tìm vật liệu phù hợp
#     material_vector = generate_embedding_qwen(material_query)
    
#     if not material_vector:
#         conn.close()
#         return {
#             "products": [], 
#             "search_method": "failed",
#             "success": False
#         }
    
#     try:
#         # Tìm top materials phù hợp
#         cur.execute("""
#             SELECT 
#                 id_sap, 
#                 material_name,
#                 material_group,
#                 (description_embedding <=> %s::vector) as distance
#             FROM materials_qwen
#             WHERE description_embedding IS NOT NULL
#             ORDER BY distance ASC
#             LIMIT 5
#         """, [material_vector])
        
#         matched_materials = cur.fetchall()
        
#         if not matched_materials:
#             conn.close()
#             return {
#                 "products": [], 
#                 "search_method": "no_materials_found",
#                 "success": False
#             }
        
#         material_ids = [m['id_sap'] for m in matched_materials]
#         material_names = [m['material_name'] for m in matched_materials]
        
#         print(f"SUCCESS: Found {len(material_ids)} matching materials: {material_names[:3]}")
        
#         # Bước 2: Tìm products sử dụng materials này
#         # Kết hợp filter category nếu có
#         category_filter = ""
#         filter_params = []
        
#         if params.get("category"):
#             category_filter = "AND p.category ILIKE %s"
#             filter_params.append(f"%{params['category']}%")
        
#         sql = f"""
#             SELECT 
#                 p.headcode,
#                 p.product_name,
#                 p.category,
#                 p.sub_category,
#                 p.material_primary,
#                 p.project,
#                 p.project_id,
#                 m.material_name,
#                 m.id_sap as material_id,
#                 pm.quantity,
#                 COUNT(*) OVER (PARTITION BY p.headcode) as material_match_count
#             FROM products_qwen p
#             INNER JOIN product_materials pm ON p.headcode = pm.product_headcode
#             INNER JOIN materials m ON pm.material_id_sap = m.id_sap
#             WHERE m.id_sap = ANY(%s)
#             {category_filter}
#             ORDER BY material_match_count DESC, p.product_name ASC
#             LIMIT 20
#         """
#         cur.execute(sql, [material_ids] + filter_params)
#         results = cur.fetchall()
        
#         conn.close()
        
#         if not results:
#             return {
#                 "products": [],
#                 "search_method": "cross_table_no_products",
#                 "matched_materials": material_names,
#                 "success": False
#             }
        
#         # Group products (vì 1 product có thể dùng nhiều materials)
#         products_dict = {}
#         for row in results:
#             headcode = row['headcode']
#             if headcode not in products_dict:
#                 products_dict[headcode] = {
#                     "headcode": headcode,
#                     "product_name": row['product_name'],
#                     "category": row['category'],
#                     "sub_category": row['sub_category'],
#                     "material_primary": row['material_primary'],
#                     "project": row['project'],
#                     "project_id": row['project_id'],
#                     "matched_materials": [],
#                     "relevance_score": 0
#                 }
#             products_dict[headcode]["matched_materials"].append({
#                 "name": row['material_name'],
#                 "id": row['material_id'],
#                 "quantity": row['quantity']
#             })
#             products_dict[headcode]["relevance_score"] += 1
            
#         products_list = sorted(
#             products_dict.values(),
#             key=lambda x: x['relevance_score'],
#             reverse=True
#         )
        
#         print(f"SUCCESS: Found {len(products_list)} products using these materials")
        
#         return {
#             "products": products_list[:10],
#             "search_method": "cross_table_material_to_product",
#             "matched_materials": material_names,
#             "explanation": f"Tìm thấy sản phẩm sử dụng: {', '.join(material_names[:3])}",
#             "success": True
#         }
        
#     except Exception as e:
#         print(f"ERROR: Cross-table search failed: {e}")
#         conn.close()
#         return {
#             "products": [], 
#             "search_method": "cross_table_error",
#             "success": False
#         }

# def get_product_materials(headcode: str):
#     """Lấy danh sách vật liệu của SẢN PHẨM"""
#     conn = get_db()
#     cur = conn.cursor(cursor_factory=RealDictCursor)
    
#     cur.execute("SELECT product_name FROM products_qwen WHERE headcode = %s", (headcode,))
#     prod = cur.fetchone()
    
#     if not prod:
#         conn.close()
#         return {
#             "response": f"ERROR: Không tìm thấy sản phẩm với mã **{headcode}**",
#             "success": False
#         }
    
#     sql = """
#         SELECT 
#             m.id_sap,
#             m.material_name, 
#             m.material_group,
#             m.material_subgroup,
#             m.material_subprice,
#             m.unit as material_unit,
#             m.image_url,
#             pm.quantity, 
#             pm.unit as pm_unit
#         FROM product_materials pm
#         INNER JOIN materials m ON pm.material_id_sap = m.id_sap
#         WHERE pm.product_headcode = %s
#         ORDER BY m.material_name ASC
#     """
    
#     try:
#         cur.execute(sql, (headcode,))
#         materials = cur.fetchall()
#         print(f"INFO: Found {len(materials)} materials for {headcode}")
#     except Exception as e:
#         print(f"ERROR: Query error: {e}")
#         conn.close()
#         return {"response": f"Lỗi truy vấn database: {str(e)}",
#             "response": f"Lỗi truy vấn database: {str(e)}",
#             "success": False
#         }           
    
#     conn.close()
    
#     # Lấy lịch sử giá (nếu cần) từ vật liệu đầu tiên có dữ liệu
#     price_history = []
#     try:
#         first_with_price = next(
#             (m for m in materials if m.get('material_subprice')),
#             None
#         )
#         if first_with_price and first_with_price['material_subprice']:
#             price_history = json.loads(first_with_price['material_subprice'])
#     except Exception:
#         pass
    
#     if not materials:
#         return {
#             "response": f"WARNING: Sản phẩm **{prod['product_name']}** ({headcode}) chưa có định mức vật liệu.\n\n"
#                         f"Có thể:\n"
#                         f"• Sản phẩm mới chưa nhập định mức\n"
#                         f"• Chưa import file product_materials.csv\n"
#                         f"• Mã sản phẩm trong product_materials không khớp\n\n"
#                         f"Vui lòng kiểm tra lại hoặc liên hệ bộ phận kỹ thuật.",
#             "success": False
#         }
    
#     total = 0
#     materials_with_price = []
    
#     for mat in materials:
#         latest_price = get_latest_material_price(mat['material_subprice'])
#         quantity = float(mat['quantity']) if mat['quantity'] else 0.0  # ✅
#         total_cost = quantity * latest_price
#         total += total_cost
        
#         materials_with_price.append({
#             'id_sap': mat['id_sap'],
#             'material_name': mat['material_name'],
#             'material_group': mat['material_group'],
#             'material_subgroup': mat['material_subgroup'],
#             'material_unit': mat['material_unit'],
#             'image_url': mat['image_url'],
#             'quantity': quantity,
#             'pm_unit': mat['pm_unit'],
#             'price': latest_price,
#             'unit_price': latest_price,
#             'unit': mat['material_unit'],
#             'total_cost': total_cost,
#             'price_history': mat['material_subprice']
#         })
    
#     response = f"📊 **ĐỊNH MỨC VẬT LIỆU: {prod['product_name']}**\n"
#     response += f"🏷️ Mã: `{headcode}`\n"
#     response += f"📦 Tổng số loại vật liệu: **{len(materials_with_price)}**\n\n"
#     # response += "---\n\n"

#     # Bảng Markdown tóm tắt vật liệu (tối đa 10 dòng)
#     headers = [
#         "STT",
#         "Tên vật liệu",
#         "Mã SAP",
#         "Nhóm",
#         "Số lượng",
#         "Đơn giá mới nhất (VNĐ)",
#         "Thành tiền (VNĐ)"
#     ]
#     rows = []

#     for idx, mat in enumerate(materials_with_price[:15], 1):
#         group_full = mat["material_group"] or ""
#         if mat.get("material_subgroup"):
#             group_full += f" - {mat['material_subgroup']}"
#         rows.append([
#             idx,
#             mat["material_name"],
#             mat["id_sap"],
#             group_full,
#             f"{mat['quantity']:,.2f} {mat['pm_unit']}",
#             f"{mat['unit_price']:,.2f}",
#             f"{mat['total_cost']:,.2f}",
#         ])

#     # response += build_markdown_table(headers, rows) + "\n\n"
    
#     if len(materials_with_price) > 15:
#         response += f"\n*...và {len(materials_with_price)-15} vật liệu khác.*\n"
    
#     response += f"\n---\n\n💰 **TỔNG CHI PHÍ NGUYÊN VẬT LIỆU: {total:,.2f} VNĐ**"
#     response += f"\n\n⚠️ **Lưu ý:** Giá được tính từ lịch sử mua hàng gần nhất. Giá thực tế có thể thay đổi."
    
#     # Thêm link ảnh (nếu có ít nhất một vật liệu có image_url)
#     first_image_url = next(
#         (m['image_url'] for m in materials_with_price if m.get('image_url')),
#         None
#     )
#     if first_image_url:
#         response += "\n\n"
#         response += f"🖼️ **Xem ảnh vật liệu:** [Google Drive Link]({first_image_url}) _ "
#         response += f"_(Click để xem ảnh chi tiết)_"
    
#     latest_price_summary = materials_with_price[0]['price'] if materials_with_price else 0

#     # Gợi ý câu hỏi tiếp theo
#     suggested_prompts = generate_suggested_prompts(
#         "get_product_materials",
#         {
#             "product_name": prod['product_name'],
#             "headcode": headcode,
#         },
#     )
#     suggested_prompts_mess = format_suggested_prompts(suggested_prompts)
#     # response += "\n\n" + "---" + "\n\n"
#     # response += suggested_prompts_mess
#     return {
#         "response": response,
#         "materials": materials_with_price,
#         "total_cost": total,
#         "product_name": prod['product_name'],
#         "latest_price": latest_price_summary,
#         "price_history": price_history,
#         "suggested_prompts_mess":suggested_prompts_mess,
#         "success": True
#     }

# def calculate_product_cost(headcode: str):
#     """Tính CHI PHÍ NGUYÊN VẬT LIỆU sản phẩm (Đơn giản hóa V4.7)"""
#     conn = get_db()
#     cur = conn.cursor(cursor_factory=RealDictCursor)
    
#     cur.execute("SELECT product_name, category FROM products_qwen WHERE headcode = %s", (headcode,))
#     prod = cur.fetchone()
    
#     if not prod:
#         conn.close()
#         return {
#             "response": f"ERROR: Không tìm thấy sản phẩm với mã **{headcode}**",
#             "success": False
#         }
    
#     sql = """
#         SELECT 
#             m.material_name,
#             m.material_group,
#             m.material_subprice,
#             m.unit as material_unit,
#             pm.quantity,
#             pm.unit as pm_unit,
#             m.image_url,
#             m.id_sap
#         FROM product_materials pm
#         INNER JOIN materials m ON pm.material_id_sap = m.id_sap
#         WHERE pm.product_headcode = %s
#         ORDER BY m.material_name ASC
#     """
#     try:
#         cur.execute(sql, (headcode,))
#         materials = cur.fetchall()
#         print(f"INFO: Cost calculation for {headcode}: {len(materials)} materials")
#     except Exception as e:
#         print(f"ERROR: Query error: {e}")
#         conn.close()
#         return {
#             "response": f"Lỗi truy vấn database: {str(e)}",
#             "success": False
#         }
    
#     conn.close()
    
#     if not materials:
#         return {
#             "response": f"⚠️ Sản phẩm **{prod['product_name']}** ({headcode}) chưa có định mức vật liệu.\n\n"
#                         f"**Nguyên nhân có thể:**\n"
#                         f"• Sản phẩm mới chưa nhập định mức\n"
#                         f"• Chưa import file `product_materials.csv`\n"
#                         f"• Mã sản phẩm trong file CSV không khớp với `{headcode}`\n\n"
#                         f"**Giải pháp:**\n"
#                         f"1. Kiểm tra file CSV có dòng nào với `product_headcode = {headcode}`\n"
#                         f"2. Import lại file qua sidebar: **Import Dữ Liệu → Định Mức**",
#             "success": False
#         }
    
#     # ✅ Tính TỔNG CHI PHÍ VẬT LIỆU
#     material_cost = 0.0
#     material_count = len(materials)
#     materials_detail = []
    
#     for mat in materials:
#         quantity = float(mat['quantity']) if mat['quantity'] else 0.0
#         latest_price = get_latest_material_price(mat['material_subprice'])
#         total_cost = quantity * latest_price
#         material_cost += total_cost
        
#         materials_detail.append({
#             'material_name': mat['material_name'],
#             'material_group': mat['material_group'],
#             'quantity': quantity,
#             'unit': mat['pm_unit'],
#             'unit_price': latest_price,
#             'total_cost': total_cost,
#             'image_url': mat['image_url'],
#             'id_sap': mat['id_sap']
#         })

#     # ✅ RESPONSE ĐƠN GIẢN - CHỈ CHI PHÍ VẬT LIỆU
#     response = f"""💰 **BÁO GIÁ NGUYÊN VẬT LIỆU**\n\n"""
#     response += f"""📦 **Sản phẩm:** {prod['product_name']}\n\n"""
#     response += f"""🏷️ **Mã:** `{headcode}`\n\n"""
#     response += f"""📂 **Danh mục:** {prod['category'] or 'N/A'}\n\n"""
#     response += f"\n\n---\n\n"
#     response += f"**CHI TIẾT NGUYÊN VẬT LIỆU ({material_count} loại):**\n"

#     # Bảng Markdown cho tối đa 15 vật liệu đầu tiên
#     headers = [
#         "STT",
#         "Tên vật liệu",
#         "Nhóm",
#         "Số lượng",
#         "Đơn giá (VNĐ)",
#         "Thành tiền (VNĐ)"
#     ]
#     rows = []

#     for idx, mat in enumerate(materials_detail[:15], 1):
#         rows.append([
#             idx,
#             mat["material_name"],
#             mat["material_group"],
#             f"{mat['quantity']:,.2f} {mat['unit']}",
#             f"{mat['unit_price']:,.0f}",
#             f"{mat['total_cost']:,.0f}",
#         ])
#     # response += build_markdown_table(headers, rows) + "\n\n"
    
#     if len(materials_detail) > 15:
#         response += f"*...và {len(materials_detail)-15} vật liệu khác*\n\n"

#     response += f"---\n\n"
#     response += f"✅ **TỔNG CHI PHÍ NGUYÊN VẬT LIỆU: {material_cost:,.0f} VNĐ**\n\n"
#     response += f"📋 **Lưu ý:** Giá được tính từ lịch sử mua hàng gần nhất.\n"
#     # response += f"💡 Phân tích vật liệu {headcode}\"_"
    
#         # Gợi ý câu hỏi tiếp theo
#     suggested_prompts = generate_suggested_prompts(
#         "calculate_product_cost",
#         {
#             "product_name": prod['product_name'],
#             "headcode": headcode,
#         },
#     )
#     suggested_prompts_mess = format_suggested_prompts(suggested_prompts)
#     # response += "\n\n" + "---" + "\n\n"
#     # response += suggested_prompts_mess
    
#     return {
#         "response": response,
#         "material_cost": material_cost,
#         "material_count": material_count,
#         "materials": materials_detail,
#         "suggested_prompts_mess":suggested_prompts_mess,
#         "suggested_prompts":[
#             "Phân tích vật liệu {headcode}"
#         ],
#         "success": True
#     }

# def search_materials(params: Dict):
#     """Tìm kiếm NGUYÊN VẬT LIỆU với giá từ material_subprice"""
#     conn = get_db()
#     cur = conn.cursor(cursor_factory=RealDictCursor)
    
#     query_parts = []
#     if params.get("material_name"): 
#         query_parts.append(params["material_name"])
#     if params.get("material_group"): 
#         query_parts.append(params["material_group"])
#     if params.get("usage_context"): 
#         query_parts.append(params["usage_context"])
#     if params.get("keywords_vector"): 
#         query_parts.append(params["keywords_vector"])
    
#     query_text = " ".join(query_parts) if query_parts else "vật liệu nội thất"
#     print(f"SEARCH: Searching materials for: {query_text}")
    
#     query_vector = generate_embedding_qwen(query_text)
    
#     if query_vector:
#         try:
#             filter_clause = "1=1"
#             filter_params = []
            
#             if params.get("material_group"):
#                 filter_clause = "material_group ILIKE %s"
#                 filter_params = [f"%{params['material_group']}%"]
            
#             sql = f"""
#                 SELECT 
#                     id_sap, material_name, material_group, material_subgroup,
#                     material_subprice, unit, image_url,
#                     (description_embedding <=> %s::vector) as distance
#                 FROM materials_qwen
#                 WHERE description_embedding IS NOT NULL AND {filter_clause}
#                 ORDER BY distance ASC
#                 LIMIT 10
#             """

#             cur.execute(sql, [query_vector] + filter_params)
#             results = cur.fetchall()
            
#             if results:
#                 print(f"SUCCESS: Vector search: Found {len(results)} materials")
                
#                 materials_with_price = []
#                 for mat in results:
#                     mat_dict = dict(mat)
#                     mat_dict['price'] = get_latest_material_price(mat_dict['material_subprice'])
#                     materials_with_price.append(mat_dict)
                
#                 conn.close()
#                 return {
#                     "materials": materials_with_price,
#                     "search_method": "vector",
#                     "success": True
#                 }
#         except Exception as e:
#             print(f"WARNING: Vector search failed: {e}")
    
#     print("INFO: Keyword search for materials")
#     conditions = []
#     values = []
    
#     if params.get("material_name"):
#         name = params['material_name']
#         conditions.append("(material_name ILIKE %s OR material_group ILIKE %s)")
#         values.extend([f"%{name}%", f"%{name}%"])
    
#     if params.get("material_group"):
#         group = params['material_group']
#         conditions.append("material_group ILIKE %s")
#         values.append(f"%{group}%")
    
#     if conditions:
#         where_clause = " OR ".join(conditions)
#         sql = f"SELECT * FROM materials_qwen WHERE {where_clause} LIMIT 15"
#     else:
#         sql = "SELECT * FROM materials_qwen ORDER BY material_name ASC LIMIT 10"
#         values = []
    
#     try:
#         cur.execute(sql, values)
#         results = cur.fetchall()
#         conn.close()
        
#         if not results:
#             return {
#                 "response": "Không tìm thấy vật liệu phù hợp.",
#                 "materials": [],
#                 "success": False
#             }
        
#         materials_with_price = []
#         for mat in results:
#             mat_dict = dict(mat)
#             mat_dict['price'] = get_latest_material_price(mat.get('material_subprice'))
#             materials_with_price.append(mat_dict)
        
#         print(f"SUCCESS: Keyword search: Found {len(materials_with_price)} materials")
#         return {
#             "materials": materials_with_price,
#             "search_method": "keyword",
#             "success": True
#         }
#     except Exception as e:
#         conn.close()
#         print(f"ERROR: Material search failed: {e}")
#         return {
#             "response": "Lỗi tìm kiếm vật liệu.",
#             "materials": [],
#             "success": False
#         }

# def get_material_detail(id_sap: str = None, material_name: str = None):
#     """Xem chi tiết VẬT LIỆU + lịch sử giá + sản phẩm sử dụng"""
#     conn = get_db()
#     cur = conn.cursor(cursor_factory=RealDictCursor)
    
#     if id_sap:
#         cur.execute("SELECT * FROM materials WHERE id_sap = %s", (id_sap,))
#     elif material_name:
#         cur.execute("SELECT * FROM materials WHERE material_name ILIKE %s LIMIT 1", (f"%{material_name}%",))
#     else:
#         conn.close()
#         return {
#             "response": "WARNING: Cần cung cấp mã SAP hoặc tên vật liệu.",
#             "success": False
#     }
    
#     material = cur.fetchone()
    
#     if not material:
#         conn.close()
#         return {
#             "response": f"ERROR: Không tìm thấy vật liệu **{id_sap or material_name}**",
#             "success": False
#         }
    
#     latest_price = get_latest_material_price(material['material_subprice'])

#     sql = """
#         SELECT 
#             p.headcode,
#             p.product_name,
#             p.category,
#             p.sub_category,
#             p.project,
#             pm.quantity,
#             pm.unit
#         FROM product_materials pm
#         INNER JOIN products p ON pm.product_headcode = p.headcode
#         WHERE pm.material_id_sap = %s
#         ORDER BY p.product_name ASC
#         LIMIT 20
#     """
    
#     try:
#         cur.execute(sql, (material['id_sap'],))
#         used_in_products = cur.fetchall()
#         print(f"INFO: Material {material['id_sap']} used in {len(used_in_products)} products")
#     except Exception as e:
#         print(f"ERROR: Query error: {e}")
#         used_in_products = []
    
#     try:
#         cur.execute("""
#             SELECT 
#                 COUNT(DISTINCT pm.product_headcode) as product_count,
#                 COUNT(DISTINCT p.project) as project_count,
#                 SUM(pm.quantity) as total_quantity
#             FROM product_materials pm
#             LEFT JOIN products p ON pm.product_headcode = p.headcode
#             WHERE pm.material_id_sap = %s
#         """, (material['id_sap'],))
#         stats = cur.fetchone()
#     except Exception as e:
#         print(f"ERROR: Stats query error: {e}")
#         stats = {
#             'product_count': 0,
#             'project_count': 0,
#             'total_quantity': 0
#         }
    
#     conn.close()
    
#     price_history = []
#     try:
#         if material['material_subprice']:
#             price_history = json.loads(material['material_subprice'])
#     except:
#         pass
    
#     response = f"🧱 **CHI TIẾT NGUYÊN VẬT LIỆU**\n\n"
#     response += f"📦 **Tên:** {material['material_name']}\n"
#     response += f"🏷️ **Mã SAP:** `{material['id_sap']}`\n"
#     response += f"📂 **Nhóm:** {material['material_group']}\n"
                    
#     if material.get('material_subgroup'):
#         response += f" - {material['material_subgroup']}\n"
#     response += f"💰 **Giá mới nhất:** {latest_price:,.2f} VNĐ/{material['unit']}\n"
#     response += f"📊 **THỐNG KÊ SỬ DỤNG:**\n"
#     response += f"• Được sử dụng trong **{stats['product_count']} sản phẩm**\n"
#     response += f"• Xuất hiện ở **{stats['project_count']} dự án**\n"
#     response += f"• Tổng số lượng: **{stats.get('total_quantity', 0) or 0} {material['unit']}**\n"
#     response += "\n---\n\n"
    
#     if price_history and len(price_history) > 0:
#         response += "📈 **LỊCH SỬ GIÁ:**\n\n"
#         for idx, ph in enumerate(sorted(price_history, key=lambda x: x['date'], reverse=True)[:5], 1):
#             response += f"{idx}. **{ph['date']}**: {ph['price']:,.2f} VNĐ\n"
#         response += "\n---\n\n"
    
#     if used_in_products and len(used_in_products) > 0:
#         response += f"INFO: **CÁC SẢN PHẨM SỬ DỤNG VẬT LIỆU NÀY:**\n\n"
        
#         for idx, prod in enumerate(used_in_products[:10], 1):
#             response += f"{idx}. **{prod['product_name']}** (`{prod['headcode']}`)\n"
#             response += f"   • Danh mục: {prod.get('category', 'N/A')}"
#             if prod.get('sub_category'):
#                 response += f" - {prod['sub_category']}"
#             response += "\n"
            
#             if prod.get('project'):
#                 response += f"   • Dự án: {prod['project']}\n"
            
#             response += f"   • Sử dụng: **{prod['quantity']} {prod['unit']}**\n\n"
        
#         if len(used_in_products) > 10:
#             response += f"*...và {len(used_in_products)-10} sản phẩm khác*\n\n"
#     else:
#         response += "🔗 **CHƯA CÓ SẢN PHẨM SỬ DỤNG**\n\n"
#         response += "_Vật liệu này chưa được gắn vào sản phẩm nào trong hệ thống._\n\n"
    
#     if material.get('image_url'):
#         response += f"---\n\n🖼️ **Xem ảnh vật liệu:** [Google Drive Link]({material['image_url']})\n"
#         response += f"(Click để xem ảnh chi tiết)"
    
#     return {
#         "response": response,
#         # "material_detail": dict(material),
#         "materials": [{  # ✅ Đổi thành list giống search_materials
#             **dict(material),
#             'price': latest_price  # ✅ Thêm key 'price'
#         }],
#         "latest_price": latest_price,
#         "price_history": price_history,
#         "used_in_products": [dict(p) for p in used_in_products],
#         "stats": dict(stats) if stats else {},
#         "has_image": bool(material.get('image_url')),
#         "success": True
#     }

# def list_material_groups():
#     """Liệt kê các nhóm vật liệu với giá tính từ material_subprice"""
#     conn = get_db()
#     cur = conn.cursor(cursor_factory=RealDictCursor)
    
#     sql = """
#         SELECT 
#             material_group,
#             COUNT(*) as count,
#             array_agg(DISTINCT material_subprice) as all_prices
#         FROM materials_qwen
#         WHERE material_group IS NOT NULL
#         GROUP BY material_group
#         ORDER BY count DESC
#     """
#     cur.execute(sql)
#     groups = cur.fetchall()
#     conn.close()
    
#     if not groups:
#         return {
#             "response": "Chưa có dữ liệu nhóm vật liệu.",
#             "success": False
#         }
    
#     response = f"📋 **DANH SÁCH NHÓM VẬT LIỆU ({len(groups)} nhóm):**\n\n"
    
#     groups_with_stats = []
#     for g in groups:
#         prices = []
#         for price_json in g['all_prices']:
#             if price_json:
#                 latest = get_latest_material_price(price_json)
#                 if latest > 0:
#                     prices.append(latest)
        
#         avg_price = sum(prices) / len(prices) if prices else 0
#         min_price = min(prices) if prices else 0
#         max_price = max(prices) if prices else 0
        
#         groups_with_stats.append({
#             'material_group': g['material_group'],
#             'count': g['count'],
#             'avg_price': avg_price,
#             'min_price': min_price,
#             'max_price': max_price
#         })
    
#     for idx, g in enumerate(groups_with_stats, 1):
#         response += f"{idx}. **{g['material_group']}** ({g['count']} loại)\n"
#         if g['avg_price'] > 0:
#             response += f"   • Giá TB: {g['avg_price']:,.2f} VNĐ\n"
#             response += f"   • Khoảng giá: {g['min_price']:,.2f} - {g['max_price']:,.2f} VNĐ\n"
#         response += "\n"
    
#     return {
#         "response": response,
#         "material_groups": groups_with_stats,
#         "success": True
#     }

# # ================================================================================================
# # API ENDPOINTS
# # ================================================================================================

# @router.post("/chat", tags=["Chat qwen"])
# def chat(msg: ChatMessage):
#     """Main chat logic"""
#     try:
#         user_message = msg.message
#         context = msg.context or {}
#         session_id = msg.session_id
        
#         print(f"DEBUG: Received request - session_id: {session_id}, message: {user_message}")
#         print(f"DEBUG: Current cache keys: {list(session_suggested_prompts_cache.keys())}")
        
#         # ✅ XỬ LÝ CHỌN SỐ GỢI Ý (1, 2, 3 hoặc kết hợp 1 và 3, 1,3)
#         # Kiểm tra xem có phải input dạng số không
#         pattern = r'^[\d\s,và]+$'
#         if re.match(pattern, user_message.strip()):
#             # Extract các số
#             numbers = re.findall(r'\d+', user_message)
            
#             # Lấy suggested_prompts từ context HOẶC cache
#             suggested_prompts = context.get("suggested_prompts") or session_suggested_prompts_cache.get(session_id, [])
            
#             print(f"DEBUG: Checking suggested_prompts for session {session_id}")
#             print(f"DEBUG: From context: {context.get('suggested_prompts')}")
#             print(f"DEBUG: From cache: {session_suggested_prompts_cache.get(session_id, [])}")
#             print(f"DEBUG: Final suggested_prompts: {suggested_prompts}")
            
#             if suggested_prompts and numbers:
#                 selected_prompts = []
                
#                 for num in numbers:
#                     idx = int(num) - 1  # Convert to 0-based index
#                     if 0 <= idx < len(suggested_prompts):
#                         selected_prompts.append(suggested_prompts[idx])
                
#                 if selected_prompts:
#                     # Nếu chọn nhiều câu, kết hợp chúng
#                     if len(selected_prompts) == 1:
#                         user_message = selected_prompts[0]
#                     else:
#                         # Kết hợp các câu gợi ý thành 1 câu hỏi
#                         user_message = " và ".join(selected_prompts)
                    
#                     print(f"INFO: User selected prompt(s) #{numbers}: {user_message}")
#                     # Xóa suggested_prompts cũ để tránh loop
#                     context.pop("suggested_prompts", None)
#                     if session_id in session_suggested_prompts_cache:
#                         del session_suggested_prompts_cache[session_id]
#                 else:
#                     print(f"WARNING: Invalid prompt number(s): {numbers}")
#                     # Return thông báo lỗi nếu số không hợp lệ
#                     return {
#                         "response": f"⚠️ Số bạn chọn không hợp lệ. Vui lòng chọn từ 1 đến {len(suggested_prompts)}.",
#                         "success": False
#                     }
#             else:
#                 print(f"DEBUG: No suggested_prompts found for session {session_id}")
#                 # Return thông báo lỗi nếu không có suggested_prompts
#                 return {
#                     "response": "⚠️ Không tìm thấy danh sách câu hỏi gợi ý. Vui lòng đặt câu hỏi trực tiếp.",
#                     "success": False
#                 }
        
#         intent_data = get_intent_and_params(user_message, context)
#         # print(f"\n🤖 Detected intent: {intent_data}")
        
#         if intent_data.get("intent") == "error":
#             return {
#                 "response": "Xin lỗi, hệ thống đang bận. Vui lòng thử lại.",
#                 "success": False
#             }
        
#         intent = intent_data["intent"]
#         params = intent_data.get("params", {})
        
#         result_response = None
#         result_count = 0
        
#         listProducts = []
#         # GREETING
#         if intent == "greeting":
#             tmp = generate_suggested_prompts("greeting")
#             suggested_prompts_mess = format_suggested_prompts(tmp)
#             result_response = {
#                 "response": "👋 Xin chào! Tôi là trợ lý AI của AA Corporation.\n\n"
#                         "Tôi có thể giúp bạn:\n"
#                         #    "• 🔍 **Tìm sản phẩm** (bàn, ghế, sofa...)\n"
#                         #    "• 🧱 **Tìm nguyên vật liệu** (gỗ, da, đá, vải...)\n"
#                         #    "• 💰 **Tính chi phí** sản phẩm\n"
#                         #    "• 📋 **Xem định mức** nguyên vật liệu\n\n"
#                         f"{suggested_prompts_mess}"
#                         "Bạn cần tìm gì hôm nay?",
#                 "suggested_prompts": tmp
#             }
        
#         elif intent == "search_product":
#             search_result = search_products(params, session_id=msg.session_id)
#             products = search_result.get("products", [])
            
#             # ✅ search_products đã xử lý HẾT ranking rồi, không cần gọi gì thêm
            
#             ranking_summary = search_result.get("ranking_summary", {})
#             result_count = len(products)
            
#             if not products:
#                 tmp = generate_suggested_prompts(
#                     "search_product_not_found",
#                     {"query": user_message}
#                 )
#                 suggested_prompts_mess = format_suggested_prompts(tmp)
#                 result_response = {
#                     "response": (
#                         f'🔍 Đã tìm thấy sản phẩm: **"{search_result.get("response", "Không tìm thấy vật liệu phù hợp.")}"**.\n\n'
#                         # '**Gợi ý cho bạn:**\n'
#                         # f"{suggested_prompts_mess}"
#                     ),
#                     # "suggested_prompts": tmp,
#                     "suggested_prompts_mess":suggested_prompts_mess,
#                 }
#             else:
#                 response_text = ""
#                 suggested_prompts = []
#                 tmp = generate_suggested_prompts(
#                         "search_product_broad",
#                         {"query": user_message, "products": products}
#                 )
#                 suggested_prompts_mess = format_suggested_prompts(tmp)
#                 if intent_data.get("is_broad_query"):
#                     follow_up = intent_data.get("follow_up_question", "Bạn muốn tìm loại cụ thể nào?")
#                     response_text = (
#                         f"🎯 **KẾT QUẢ TÌM KIẾM**\n"
#                         f"Tôi tìm thấy **{len(products)} sản phẩm** liên quan đến \"{user_message}\".\n"
#                         f"💡 **{follow_up}**\n"
#                         # f"Dưới đây là một số lựa chọn phổ biến dành cho bạn:\n"
#                         # f"{suggested_prompts_mess}"
#                     )
#                 else:
#                     response_text = (
#                         f"✅ **KẾT QUẢ TÌM KIẾM CHUYÊN SÂU**\n"
#                         f"Tôi đã chọn lọc **{len(products)}** phù hợp nhất với yêu cầu của bạn.\n\n"
#                     )
#                     # ✅ THÊM: Hiển thị thông tin ranking nếu có
#                     if ranking_summary['ranking_applied']:
#                         response_text += f"\n\n⭐ **{ranking_summary['boosted_items']} sản phẩm** được ưu tiên dựa trên lịch sử tìm kiếm."
                    
#                     response_text += "\n**Bảng tóm tắt các sản phẩm:**\n"
#                     headers = [
#                         "STT",
#                         "Tên sản phẩm",
#                         "Mã sản phẩm",
#                         "Danh mục",
#                         "Danh mục phụ",
#                         "Vật liệu chính",
#                     ]
#                     rows = []
#                     for idx, prod_item in enumerate(products, 1):
#                         rows.append([
#                             idx,
#                             prod_item.get("product_name", ""),
#                             prod_item.get("headcode", ""),
#                             prod_item.get("category", ""),
#                             prod_item.get("sub_category", ""),
#                             prod_item.get("material_primary", ""),
#                         ])
#                     # response_text += (
#                     #     "\n📦 **DANH SÁCH SẢN PHẨM ĐỀ XUẤT**\n" +
#                     #     build_markdown_table(headers, rows) +
#                     #     "\n"
#                     # )
                    
#                     suggested_prompts = [
#                         f"💰 Phân tích chi phí {products[0]['headcode']}",
#                         f"🧱 Xem cấu tạo vật liệu {products[0]['headcode']}",
#                         f"🎯 So sánh với sản phẩm tương tự",
#                         "📞 Kết nối với chuyên viên tư vấn"
#                     ]
                    
#                     tmp = generate_suggested_prompts(
#                         "search_product_found",
#                         {"query": user_message, "products": products}
#                     )
#                     suggested_prompts_mess = format_suggested_prompts(tmp)
#                     # response_text += (
#                     #     f"**Các vật :**\n"
#                     #     # f"• Các sản phẩm được liệt kê dưới đây đều đáp ứng yêu cầu về sản phẩm\n"
#                     #     # f"• Nếu cần thay đổi tiêu chí (màu sắc, kích thước, chất liệu), hãy cho tôi biết\n"
#                     #     # f"• Tôi có thể tư vấn thêm về phong cách thiết kế phù hợp"
#                     #     f"{suggested_prompts_mess}"
#                     # )
#                     # response_text += "\n\n---\n\n"
#                     # response_text += suggested_prompts_mess
#                 result_response = {
#                     "response": response_text,
#                     "products": products,
#                     "suggested_prompts": suggested_prompts,
#                     "ranking_summary": ranking_summary,  
#                     "can_provide_feedback": True ,
#                     "suggested_prompts_mess":suggested_prompts_mess,
#                     "success": True
#                 }
#         elif intent == "search_product_by_material":
#             material_query = params.get("material_name") or params.get("material_primary") or params.get("keywords_vector")
            
#             if not material_query:
#                 tmp = generate_suggested_prompts(
#                     "search_product_by_material",
#                     {"query": user_message}
#                 )
#                 suggested_prompts_mess = format_suggested_prompts(tmp)
#                 result_response = {
#                     "response": "🎯 **TÌM SẢN PHẨM THEO VẬT LIỆU**\n\n"
#                                 # "Để tôi tư vấn sản phẩm phù hợp, vui lòng cho biết:\n"
#                                 # "• Bạn quan tâm đến vật liệu nào? (gỗ, đá, kim loại...)\n"
#                                 # "• Sản phẩm dùng cho không gian nào?\n"
#                                 # "• Ngân sách dự kiến là bao nhiêu?",
#                                 f"{suggested_prompts_mess}",
#                     "suggested_prompts": tmp
#                 }
#             else:
#                 search_result = search_products_by_material(material_query, params)
#                 products = search_result.get("products", [])
                
#                 feedback_scores = get_feedback_boost_for_query(user_message, "product")
#                 if feedback_scores:
#                     products = rerank_with_feedback(products, feedback_scores, "headcode")
                
#                 result_count = len(products)
                
#                 if not products:
#                     matched_mats = search_result.get("matched_materials", [])
#                     tmp = generate_suggested_prompts(
#                         "search_product_by_material_not_found",
#                         {"query": user_message, "matched_materials": matched_mats}
#                     )
#                     suggested_prompts_mess = format_suggested_prompts(tmp)
#                     result_response = {
#                         "response": f"🔍 **KẾT QUẢ TÌM KIẾM**\n\n"
#                                     f"Tôi tìm thấy vật liệu **{', '.join(matched_mats)}** trong hệ thống.\n\n"
#                                     f"**Tuy nhiên, hiện chưa có sản phẩm nào sử dụng vật liệu này.**\n\n",
#                                     # f"💡 **Gợi ý cho bạn:**\n"
#                                     # f"• Tìm sản phẩm với vật liệu tương tự\n"
#                                     # f"• Liên hệ bộ phận thiết kế để đặt hàng riêng\n"
#                                     # f"• Xem vật liệu thay thế có tính năng tương đồng",
#                                     # f"{suggested_prompts_mess}",
#                         "materials": matched_mats,
#                         "suggested_prompts": tmp,
#                         "materials": [],
#                         "suggested_prompts_mess":suggested_prompts_mess
#                     }
#                 else:
#                     explanation = search_result.get("explanation", "")
#                     response_text = f"✅ {explanation}\n\n"
#                     response_text = (
#                         f"✅ **SẢN PHẨM SỬ DỤNG {material_query.upper()}**\n\n"
#                         f"{explanation}\n\n"
#                         f"📊 **Tìm thấy {len(products)} sản phẩm:**\n"
#                         f"Các sản phẩm này đều sử dụng {material_query} - một lựa chọn tuyệt vời về độ bền và thẩm mỹ.\n\n"
#                         f"**Ưu điểm nổi bật:**\n"
#                         f"• Chất lượng vật liệu được đảm bảo\n"
#                         f"• Thiết kế phù hợp với xu hướng hiện đại\n"
#                         f"• Dễ dàng bảo trì và vệ sinh"
#                     )
#                     response_text += f"📦 Tìm thấy **{len(products)} sản phẩm**:"
                    
#                     tmp = generate_suggested_prompts(
#                         "search_product_by_material_found",
#                         {"query": user_message, "products": products}
#                     )
#                     suggested_prompts_mess = format_suggested_prompts(tmp)
#                     result_response = {
#                         "response": response_text,
#                         "products": products,
#                         "search_method": "cross_table",
#                         "can_provide_feedback": True,
#                         "suggested_prompts": tmp,
#                         "suggested_prompts_mess":suggested_prompts_mess,
#                         "success": True
#                     }
#         elif intent == "search_material_for_product":
#             # 1. Lấy query từ params hoặc context
#             product_query = params.get("category") or params.get("usage_context") or params.get("keywords_vector")
            
#             if not product_query:
#                 tmp = generate_suggested_prompts(
#                     "search_material_for_product",
#                     {"query": user_message}
#                 )
#                 suggested_prompts_mess = format_suggested_prompts(tmp)
#                 result_response = {
#                     "response": "⚠️ Bạn muốn tìm vật liệu để làm sản phẩm gì?",
#                     "suggested_prompts": tmp
#                 }
#             else:
#                 # 2. Gọi hàm tìm kiếm
#                 search_result = search_materials_for_product(product_query, params)
#                 materials = search_result.get("materials", [])
                
#                 # 3. [MỚI] Áp dụng Feedback Ranking (Giống Intent 3)
#                 # Dùng query gốc của user để tìm feedback tương tự
#                 feedback_scores = get_feedback_boost_for_query(user_message, "material")
#                 if feedback_scores:
#                     materials = rerank_with_feedback(materials, feedback_scores, "id_sap")
                
#                 # 4. [MỚI] Lấy thông tin Ranking Summary để hiển thị UI
#                 ranking_summary = get_ranking_summary(materials)
                
#                 result_count = len(materials)
                
#                 if not materials:
#                     result_response = {
#                         "response": "Không tìm thấy vật liệu phù hợp.",
#                         "materials": []
#                     }
#                 else:
#                     explanation = search_result.get("explanation", "")
                    
#                     response_text = f"✅ {explanation}\n\n"
                    
#                     # Hiển thị thông báo nếu có Ranking
#                     if ranking_summary['ranking_applied']:
#                          response_text += f"⭐ **{ranking_summary['boosted_items']} vật liệu** được ưu tiên dựa trên lịch sử.\n\n"
#                     response_text += f"🧱 Tìm thấy **{len(materials)} vật liệu** thường dùng:\n\n"
                    
#                     for idx, mat in enumerate(materials[:5], 1):
#                         response_text += f"{idx}. **{mat['material_name']}**\n"
#                         response_text += f"   • Nhóm: {mat['material_group']}\n"
#                         response_text += f"   • Giá: {mat.get('price', 0):,.0f} VNĐ/{mat.get('unit', '')}\n"
#                         response_text += f"   • Dùng trong {mat.get('usage_count', 0)} sản phẩm\n\n"
                    
#                     result_response = {
#                         "response": response_text,
#                         "materials": materials,
#                         "search_method": "cross_table_product_to_material", # Đánh dấu để UI nhận biết
#                         "ranking_summary": ranking_summary,   # Truyền xuống UI
#                         "can_provide_feedback": True,          # Bật nút Feedback
#                         "success": True
#                     }
                    
#         elif intent == "query_product_materials":
#             headcode = params.get("headcode")
            
#             if not headcode and context.get("last_search_results"):
#                 headcode = context["last_search_results"][0]
                
#             if not headcode:
#                 tmp = generate_suggested_prompts(
#                     "query_product_materials",
#                     {"query": user_message}
#                 )
#                 result_response = {
#                     "response": "⚠️ Bạn muốn xem vật liệu của sản phẩm nào? Vui lòng cung cấp mã hoặc tìm kiếm sản phẩm trước.",
#                     "suggested_prompts": tmp
#                 }
#             else:
#                 result_response = get_product_materials(headcode)
                
#         elif intent == "calculate_product_cost":
#             headcode = params.get("headcode")
            
#             if not headcode and context.get("last_search_results"):
#                 headcode = context["last_search_results"][0]
            
#             if not headcode:
#                 tmp = generate_suggested_prompts(
#                     "calculate_product_cost",
#                     {"query": user_message}
#                 )
#                 result_response = {
#                     "response": "⚠️ Bạn muốn xem chi phí sản phẩm nào? Vui lòng cung cấp mã hoặc tìm kiếm sản phẩm trước.",
#                     "suggested_prompts": tmp
#                 }
#             else:
#                 result_response = calculate_product_cost(headcode)
        
#         elif intent == "search_material":
#             search_result = search_materials(params)
#             materials = search_result.get("materials", [])
            
#             # 🆕 ÁP DỤNG FEEDBACK RANKING
#             materials = apply_feedback_to_search(
#                 materials,
#                 user_message,
#                 search_type="material",
#                 id_key="id_sap"
#             )
            
#             # 🆕 Lấy ranking summary
#             ranking_summary = get_ranking_summary(materials)
                        
#             if not materials:
#                 tmp = generate_suggested_prompts(
#                     "search_material_not_found",
#                     {"query": user_message}
#                 )
#                 suggested_prompts_mess = format_suggested_prompts(tmp)
#                 result_response = {
#                     "response": f'🔍 Đã tìm thấy sản phẩm: **"{search_result.get("response", "Không tìm thấy vật liệu phù hợp.")}"**.\n\n'
#                     "**Đề xuất:**\n"
#                             f"{suggested_prompts_mess}",
#                     "suggested_prompts": tmp,
#                     "materials": []
#                 }
#             else:
#                 response_text = ""
                
#                 if intent_data.get("is_broad_query"):
#                     follow_up = intent_data.get("follow_up_question", "Bạn cần tìm loại vật liệu cụ thể nào?")
#                     response_text = (
#                         f"🔎 **TÌM KIẾM VẬT LIỆU**\n"
#                         f"Tìm thấy **{len(materials)} nguyên vật liệu** liên quan.\n\n"
#                         f"💡 **Để tôi tư vấn chính xác hơn:** {follow_up}\n\n"
#                         f"*Dưới đây là các vật liệu đang được sử dụng phổ biến:*"
#                     )
#                 else:
#                     # response_text = f"✅ Đã tìm thấy **{len(materials)} nguyên vật liệu** đúng yêu cầu."
#                     response_text = (
#                         f"✅ **TƯ VẤN VẬT LIỆU CHUYÊN SÂU**\n"
#                         f"Dựa trên nhu cầu của bạn, **{len(materials)} vật liệu** dưới đây đang được sử dụng phổ biến và phù hợp nhất.\n\n"
#                     )
#                     # 🆕 Hiển thị ranking info
#                     if ranking_summary['ranking_applied']:
#                         response_text += f"\n\n⭐ **{ranking_summary['boosted_items']} vật liệu** được ưu tiên."

#                 response_text += "\n**Bảng tóm tắt các vật liệu:**\n"
#                 headers = [
#                     "STT",
#                     "Tên vật liệu",
#                     "Mã SAP",
#                     "Nhóm",
#                     "Giá (VNĐ/ĐV)",
#                     "Phản hồi"
#                 ]
#                 rows = []

#                 for idx, mat in enumerate(materials, 1):
#                     price = f"{mat.get('price', 0):,.2f} / {mat.get('unit', '')}"
#                     material_name = mat["material_name"]
#                     feedback = (
#                         f"{mat['feedback_count']} lượt"
#                         if mat.get("has_feedback")
#                         else "-"
#                     )
#                     rows.append([
#                         idx,
#                         material_name,
#                         mat["id_sap"],
#                         mat["material_group"],
#                         price,
#                         feedback
#                     ])

#                 # response_text += (
#                 #     "\n📦 **DANH SÁCH VẬT LIỆU ƯU TIÊN**\n" +
#                 #     build_markdown_table(headers, rows) +
#                 #     "\n"
#                 # )
                
#                 # Thêm phần link hình ảnh riêng (ngoài bảng)
#                 materials_with_images = [m for m in materials[:3] if m.get('image_url')]
#                 if materials_with_images:
#                     response_text += "\n**📷 XEM ẢNH MẪU:**\n"
#                     for mat in materials_with_images:
#                         response_text += f"• [{mat['material_name']}]({mat.get('image_url', '#')})\n"
                
#                 tmp = generate_suggested_prompts(
#                     "search_material_found",
#                     {"query": user_message, "materials": materials}
#                 )
#                 suggested_prompts_mess = format_suggested_prompts(tmp)
#                 # response_text += (
#                 #         f"**Nếu các vật liệu trên chưa đúng ý, tôi có thể:**\n"
#                 #         f"{suggested_prompts_mess}"
#                 #     )
                
#                 tmp_final = generate_suggested_prompts(
#                     "search_material_found",
#                     {"query": user_message, "materials": materials}
#                 )
#                 result_response = {
#                     "response": response_text,
#                     "materials": materials,
#                     "suggested_prompts": tmp_final,
#                     "ranking_summary": ranking_summary,  
#                     "can_provide_feedback": True,
#                     "show_comparison": True,
#                     "suggested_prompts_mess":(
#                         f"**Nếu các vật liệu trên chưa đúng ý, tôi có thể:**\n"
#                         f"{suggested_prompts_mess}"
#                     ),
#                     "success": True
#                 }      
        
#         elif intent == "query_material_detail":
#             id_sap = params.get("id_sap")
#             material_name = params.get("material_name")
            
#             if not id_sap and not material_name and context.get("current_materials"):
#                 first_mat = context["current_materials"][0]
#                 id_sap = first_mat.get("id_sap")
            
#             if not id_sap and not material_name:
#                 tmp = generate_suggested_prompts(
#                     "query_material_detail",
#                     {"query": user_message}
#                 )
#                 result_response = {
#                     "response": "⚠️ Bạn muốn xem chi tiết vật liệu nào? Vui lòng cung cấp mã SAP hoặc tên vật liệu.",
#                     "suggested_prompts": tmp
#                 }
#             else:
#                 result_response = get_material_detail(id_sap=id_sap, material_name=material_name)
#                 result_count = len(result_response.get("used_in_products", []))
        
#         elif intent == "list_material_groups":
#             result_response = list_material_groups()
        
#         # UNKNOWN
#         else:
#             tmp = generate_suggested_prompts(
#                 "unknown",
#                 {"query": user_message}
#             )
#             suggested_prompts_mess = format_suggested_prompts(tmp)
#             result_response = {
#                 "response": "Tôi chưa hiểu rõ ý bạn. Hãy thử hỏi về sản phẩm hoặc vật liệu nhé!\n\n"
#                         "**Ví dụ:**\n"
#                         "• \"Tìm bàn ăn tròn\"\n"
#                         "• \"Tìm gỗ sồi\"\n"
#                         "• \"Tính chi phí sản phẩm B001\"\n"
#                         "• \"Xem vật liệu của ghế G002\"\n\n"
#                         f"{suggested_prompts_mess}",
#                 "suggested_prompts": tmp
#             }
        
#         # Lấy thông tin mở rộng từ kết quả tìm kiếm
#         expanded = None
#         keywords = []
        
#         if intent == "search_product" and result_response.get("data"):
#             expanded = result_response["data"].get("expanded_query")
#             # Lấy keywords từ params
#             if params.get("keywords_vector"):
#                 keywords = extract_product_keywords(params["keywords_vector"])
                
#         # print(f"SUCCESS => Final response: {result_response.get('materials', '')}, count: {result_count}")
#         listProducts = listProducts or result_response.get("products", []) or result_response.get("materials", [])
        
#         # ✅ LƯU SUGGESTED_PROMPTS VÀO CACHE
#         if result_response and result_response.get("suggested_prompts"):
#             session_suggested_prompts_cache[msg.session_id] = result_response["suggested_prompts"]
#             print(f"INFO: Cached {len(result_response['suggested_prompts'])} prompts for session {msg.session_id}")
        
#         # Save chat history
#         histories.save_chat_to_histories(
#             email="test@gmail.com",
#             session_id=msg.session_id,
#             question=user_message,
#             messages=listProducts,
#             answer=result_response.get("response", "")
#         )
        
#         if result_response:
#             result_response["query"] = user_message 
            
#         return result_response
    
#     except Exception as e:
#         print(f"Server Error: {e}")
#         import traceback
#         traceback.print_exc()
#         return {
#             "response": f"WARNING: Lỗi hệ thống: {str(e)}",
#             "success": False
#         }
    
# @router.post("/batch/products", tags=["Chat qwen"])
# def batch_product_operations(request: BatchProductRequest):
#     """
#     🔥 Xử lý batch operations cho nhiều sản phẩm
#     Operations: detail, materials, cost
#     """
#     try:
#         if not request.product_headcodes:
#             return {
#                 "response": "⚠️ Vui lòng chọn ít nhất 1 sản phẩm",
#                 "success": False
#             }
        
#         headcodes = request.product_headcodes
#         operation = request.operation
        
#         print(f"INFO: Batch {operation}: {len(headcodes)} products")
        
#         # ========== OPERATION: CHI TIẾT SẢN PHẨM ==========
#         if operation == "detail":
#             conn = get_db()
#             cur = conn.cursor(cursor_factory=RealDictCursor)
            
#             cur.execute("""
#                 SELECT headcode, product_name, category, sub_category, material_primary, project, unit
#                 FROM products_qwen
#                 WHERE headcode = ANY(%s)
#                 ORDER BY product_name
#             """, (headcodes,))
            
#             products = cur.fetchall()
#             conn.close()
            
#             if not products:
#                 return {
#                     "response": "ERROR: Không tìm thấy sản phẩm",
#                     "success": False
#                 }
            
#             response = f"📋 **CHI TIẾT {len(products)} SẢN PHẨM:**\n\n"
            
#             for idx, prod in enumerate(products, 1):
#                 response += f"**{idx}. {prod['product_name']}**\n"
#                 response += f"   • Mã: `{prod['headcode']}`\n"
#                 response += f"   • Danh mục: {prod.get('category', 'N/A')}"
                
#                 if prod.get('sub_category'):
#                     response += f" - {prod['sub_category']}"
                
#                 response += f"\n   • Vật liệu chính: {prod.get('material_primary', 'N/A')}\n"
                
#                 if prod.get('project'):
#                     response += f"   • Dự án: {prod['project']}\n"
                
#                 response += "\n"
            
#             return {
#                 "response": response,
#                 "products": [dict(p) for p in products],
#                 "success": True
#             }
        
#         # ========== OPERATION: ĐỊNH MỨC VẬT LIỆU ==========
#         elif operation == "materials":
#             conn = get_db()
#             cur = conn.cursor(cursor_factory=RealDictCursor)
            
#             # Lấy tất cả vật liệu của các sản phẩm
#             cur.execute("""
#                 SELECT 
#                     p.headcode,
#                     p.product_name,
#                     m.id_sap,
#                     m.material_name,
#                     m.material_group,
#                     m.material_subprice,
#                     m.unit,
#                     pm.quantity,
#                     pm.unit as pm_unit
#                 FROM product_materials pm
#                 INNER JOIN products_qwen p ON pm.product_headcode = p.headcode
#                 INNER JOIN materials m ON pm.material_id_sap = m.id_sap
#                 WHERE p.headcode = ANY(%s)
#                 ORDER BY p.product_name, m.material_name
#             """, (headcodes,))
            
#             records = cur.fetchall()
#             conn.close()
            
#             if not records:
#                 return {
#                     "response": "WARNING: Các sản phẩm này chưa có định mức vật liệu",
#                     "success": False
#                 }
            
#             # Group by product
#             products_dict = {}
#             for rec in records:
#                 hc = rec['headcode']
#                 if hc not in products_dict:
#                     products_dict[hc] = {
#                         'headcode': hc,
#                         'product_name': rec['product_name'],
#                         'materials': []
#                     }
                
#                 price = get_latest_material_price(rec['material_subprice'])
#                 qty = float(rec['quantity']) if rec['quantity'] else 0.0
                
#                 products_dict[hc]['materials'].append({
#                     'id_sap': rec['id_sap'],
#                     'name': rec['material_name'],
#                     'group': rec['material_group'],
#                     'quantity': qty,
#                     'unit': rec['pm_unit'],
#                     'price': price,
#                     'total': qty * price
#                 })
            
#             # Tạo response
#             response = f"🧱 **ĐỊNH MỨC VẬT LIỆU - {len(products_dict)} SẢN PHẨM:**\n\n"
            
#             for prod_data in products_dict.values():
#                 response += f"### 📦 {prod_data['product_name']} (`{prod_data['headcode']}`)\n\n"
                
#                 total_cost = sum(m['total'] for m in prod_data['materials'])

#                 # Tạo bảng Markdown cho vật liệu
#                 headers = [
#                     "STT",
#                     "Tên vật liệu",
#                     "Nhóm",
#                     "Số lượng",
#                     "Đơn giá (VNĐ)",
#                     "Thành tiền (VNĐ)"
#                 ]
#                 rows = []

#                 for idx, mat in enumerate(prod_data['materials'][:15], 1):
#                     rows.append([
#                         idx,
#                         mat['name'],
#                         mat['group'],
#                         f"{mat['quantity']} {mat['unit']}",
#                         f"{mat['price']:,.0f}",
#                         f"{mat['total']:,.0f}"
#                     ])

#                 # response += build_markdown_table(headers, rows) + "\n\n"
                
#                 if len(prod_data['materials']) > 15:
#                     response += f"*...và {len(prod_data['materials'])-15} vật liệu khác*\n\n"
                
#                 response += f"💰 **Tổng NVL ({prod_data['headcode']}): {total_cost:,.0f} VNĐ**\n\n"
#                 response += "---\n\n"
            
#             # Tạo materials list để UI có thể render cards
#             all_materials = []
#             for prod_data in products_dict.values():
#                 all_materials.extend(prod_data['materials'])
            
#             # Tạo suggested prompts
#             first_product_name = ""
#             if len(products_dict) > 0:
#                 first_product_name = list(products_dict.values())[0]['product_name']

#             suggested_prompts = generate_suggested_prompts(
#                 "batch_materials",
#                 {
#                     "product_count": len(products_dict),
#                     "first_product": first_product_name,
#                 },
#             )
#             suggested_prompts_mess = format_suggested_prompts(suggested_prompts)
#             response += suggested_prompts_mess

#             return {
#                 "response": response,
#                 "products_materials": products_dict,
#                 "materials": all_materials,
#                 "suggested_prompts": suggested_prompts,
#                 "success": True
#             }
        
#         # ========== OPERATION: CHI PHÍ ==========
#         elif operation == "cost":
#             conn = get_db()
#             cur = conn.cursor(cursor_factory=RealDictCursor)
            
#             cur.execute("""
#                 SELECT 
#                     p.headcode,
#                     p.product_name,
#                     p.category,
#                     m.material_name,
#                     m.material_group,
#                     m.material_subprice,
#                     pm.quantity,
#                     pm.unit
#                 FROM product_materials pm
#                 INNER JOIN products_qwen p ON pm.product_headcode = p.headcode
#                 INNER JOIN materials m ON pm.material_id_sap = m.id_sap
#                 WHERE p.headcode = ANY(%s)
#                 ORDER BY p.product_name
#             """, (headcodes,))
            
#             records = cur.fetchall()
#             conn.close()
            
#             if not records:
#                 return {
#                     "response": "WARNING: Không có dữ liệu định mức",
#                     "success": False
#                 }
            
#             # Tính chi phí từng sản phẩm
#             products_cost = {}
#             for rec in records:
#                 hc = rec['headcode']
#                 if hc not in products_cost:
#                     products_cost[hc] = {
#                         'headcode': hc,
#                         'name': rec['product_name'],
#                         'category': rec['category'],
#                         'material_cost': 0.0,
#                         'materials_detail': []
#                     }
                
#                 qty = float(rec['quantity']) if rec['quantity'] else 0.0
#                 price = get_latest_material_price(rec['material_subprice'])
#                 total = qty * price
                
#                 products_cost[hc]['material_cost'] += total
#                 products_cost[hc]['materials_detail'].append({
#                     'name': rec['material_name'],
#                     'group': rec['material_group'],
#                     'quantity': qty,
#                     'unit': rec['unit'],
#                     'price': price,
#                     'total': total
#                 })
            
#             # Response
#             response = f"💰 **BÁO CÁO CHI PHÍ - {len(products_cost)} SẢN PHẨM:**\n\n"
            
#             grand_total = 0.0
            
#             for prod_data in products_cost.values():
#                 response += f"### 📦 {prod_data['name']} (`{prod_data['headcode']}`)\n"
#                 response += f"**Danh mục:** {prod_data['category']}\n\n"
#                 response += f"**Chi phí nguyên vật liệu:** {prod_data['material_cost']:,.0f} VNĐ\n"
#                 response += f"   • {len(prod_data['materials_detail'])} loại vật liệu"
#                 response += "\n\n---\n\n"
                
#                 grand_total += prod_data['material_cost']
            
#             response += f"## 💵 TỔNG CHI PHÍ NVL: {grand_total:,.0f} VNĐ\n\n"
#             response += "📋 *Chi phí được tính từ giá nguyên vật liệu gần nhất*"
            
#             # Tạo suggested prompts
#             first_headcode = ""
#             if len(products_cost) > 0:
#                 first_headcode = list(products_cost.values())[0]['headcode']

#             suggested_prompts = generate_suggested_prompts(
#                 "batch_cost",
#                 {
#                     "product_count": len(products_cost),
#                     "first_headcode": first_headcode,
#                 },
#             )
#             suggested_prompts_mess = format_suggested_prompts(suggested_prompts)
#             response += suggested_prompts_mess

#             return {
#                 "response": response,
#                 "products_cost": products_cost,
#                 "grand_total": grand_total,
#                 "suggested_prompts": suggested_prompts,
#                 "success": True
#             }
        
#         else:
#             return {
#                 "response": "ERROR: Operation không hợp lệ",
#                 "success": False
#             }
    
#     except Exception as e:
#         print(f"ERROR: Batch operation error: {e}")
#         import traceback
#         traceback.print_exc()
#         return {
#             "response": f"ERROR: {str(e)}",
#             "success": False
#         }

# # ================================================================================================
# # MODULE 1: CONSOLIDATED BOM REPORT
# # ================================================================================================

# @router.post("/report/consolidated", tags=["Chat qwen"])
# def create_consolidated_report(request: ConsolidatedBOMRequest):
#     """
#     📊 API Endpoint tạo báo cáo tổng hợp định mức vật tư
    
#     Input: {"product_headcodes": ["B001", "B002", "G001"], "session_id": "..."}
#     Output: File Excel (.xlsx)
#     """
#     try:
#         if not request.product_headcodes or len(request.product_headcodes) == 0:
#             return {
#                 "message": "WARNING: Vui lòng chọn ít nhất 1 sản phẩm",
#                 "success": False
#             }
        
#         print(f"INFO: Generating report for {len(request.product_headcodes)} products...")
        
#         # Tạo file Excel
#         excel_buffer = generate_consolidated_report(request.product_headcodes)
        
#         # Lưu lịch sử (Optional)
#         # if request.session_id:
#             # save_chat_history(
#             #     session_id=request.session_id,
#             #     user_message=f"[REPORT] Tổng hợp {len(request.product_headcodes)} sản phẩm",
#             #     bot_response="Đã tạo báo cáo Excel",
#             #     intent="generate_report",
#             #     params={"products": request.product_headcodes},
#             #     result_count=len(request.product_headcodes),
#             #     search_type="report"
#             # )

#         filename = f"BOM_Consolidated_{len(request.product_headcodes)}SP_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
#         return StreamingResponse(
#             excel_buffer,
#             media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#             headers={"Content-Disposition": f"attachment; filename={filename}"}
#         )
        
#     except ValueError as e:
#         return {
#             "message": f"ERROR: {str(e)}",
#             "success": False
#         }
#     except Exception as e:
#         print(f"ERROR: Report generation error: {e}")
#         import traceback
#         traceback.print_exc()
#         return {
#             "message": f"ERROR: {str(e)}", 
#             "success": False
#         }

# @router.post("/track/view", tags=["Chat qwen"])
# def track_product_view(request: TrackingRequest):
#     """
#     👁️ Track khi user XEM CHI TIẾT sản phẩm (Positive Signal)
#     """
#     try:
#         conn = get_db()
#         cur = conn.cursor(cursor_factory=RealDictCursor)
        
#         # Lấy embedding của sản phẩm
#         cur.execute("""
#             SELECT description_embedding 
#             FROM products_qwen 
#             WHERE headcode = %s AND description_embedding IS NOT NULL
#         """, (request.product_headcode,))
        
#         result = cur.fetchone()
        
#         if not result:
#             conn.close()
#             return {
#                 "message": "Product not found or no embedding",
#                 "success": False
#             }
        
#         product_vector = result['description_embedding']
        
#         # Lưu vào user_preferences
#         cur.execute("""
#             INSERT INTO user_preferences 
#             (session_id, product_headcode, product_vector, interaction_type, weight)
#             VALUES (%s, %s, %s, %s, %s)
#         """, (
#             request.session_id,
#             request.product_headcode,
#             product_vector,
#             'view',
#             1.0  # Positive signal
#         ))
        
#         conn.commit()
#         conn.close()
        
#         print(f"SUCCESS: Tracked VIEW: {request.product_headcode} by {request.session_id[:8]}")
        
#         return {
#             "message": "SUCCESS: Tracked successfully", "type": "view", 
#             "success": True
#         }
        
#     except Exception as e:
#         print(f"ERROR: Tracking error: {e}")
#         return {
#             "message": f"ERROR: {str(e)}",
#             "success": False
#         }

# @router.post("/track/reject", tags=["Chat qwen"])
# def track_product_reject(request: TrackingRequest):
#     """
#     ERROR: Track khi user BỎ QUA/REJECT sản phẩm (Negative Signal)
#     """
#     try:
#         conn = get_db()
#         cur = conn.cursor(cursor_factory=RealDictCursor)
        
#         cur.execute("""
#             SELECT description_embedding 
#             FROM products_qwen 
#             WHERE headcode = %s AND description_embedding IS NOT NULL
#         """, (request.product_headcode,))
        
#         result = cur.fetchone()
        
#         if not result:
#             conn.close()
#             return {
#                 "message": "Product not found",
#                 "success": False
#             }
        
#         product_vector = result['description_embedding']
        
#         cur.execute("""
#             INSERT INTO user_preferences 
#             (session_id, product_headcode, product_vector, interaction_type, weight)
#             VALUES (%s, %s, %s, %s, %s)
#         """, (
#             request.session_id,
#             request.product_headcode,
#             product_vector,
#             'reject',
#             -1.0  # Negative signal
#         ))
        
#         conn.commit()
#         conn.close()
        
#         print(f"ERROR: Tracked REJECT: {request.product_headcode} by {request.session_id[:8]}")
        
#         return {
#             "message": "SUCCESS: Tracked rejection", 
#             "type": "reject",
#             "success": True
#         }
        
#     except Exception as e:
#         print(f"ERROR: Tracking error: {e}")
#         return {
#             "message": f"ERROR: {str(e)}",
#             "success": False
#         }
