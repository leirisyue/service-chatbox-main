
# import json
# import os
# import time
# import uuid
# from typing import Dict, List

# import google.generativeai as genai
# import psycopg2
# from fastapi import (APIRouter, File, Form, UploadFile)
# from historiesapi import histories
# from PIL import Image
# from psycopg2.extras import RealDictCursor

# from .textfunc import call_gemini_with_retry
# from .textapi_qwen import search_products
# from config import settings

# def get_db():
#     return psycopg2.connect(**settings.DB_CONFIG)

# router = APIRouter()
# # ================================================================================================
# # FUNCTION DEFINITIONS
# # ================================================================================================
    
# def batch_classify_materials(materials_batch: List[Dict]) -> List[Dict]:
#     """
#     Phân loại HÀNG LOẠT vật liệu
#     Input: [{'name': 'GỖ SỒI', 'id_sap': 'M001'}, ...]
#     Output: [{'id_sap': 'M001', 'material_group': 'Gỗ', ...}, ...]
#     """
#     if not materials_batch:
#         return []
    
#     # [FIX] Đổi sang model gemini-1.5-flash để ổn định hơn và tránh lỗi Rate Limit
#     model = genai.GenerativeModel("gemini-2.5-flash")
    
#     materials_text = ""
#     for i, mat in enumerate(materials_batch, 1):
#         materials_text += f"{i}. ID: {mat['id_sap']}, Tên: {mat['name']}\n"
    
#     prompt = f"""
#                 Phân loại {len(materials_batch)} nguyên vật liệu nội thất:
#                 {materials_text}
#                 Xác định:
#                 1. material_group: Gỗ, Da, Vải, Đá, Kim loại, Kính, Nhựa, Sơn, Keo, Phụ kiện, Khác
#                 2. material_subgroup: Nhóm con cụ thể (VD: "Gỗ tự nhiên", "Da thật", "Vải cao cấp")
#                 OUTPUT JSON ARRAY ONLY:
#                 [
#                     {{"id_sap": "M001", "material_group": "...", "material_subgroup": "..."}},
#                     {{"id_sap": "M002", "material_group": "...", "material_subgroup": "..."}}
#                 ]
#             """
    
#     # Gọi Gemini với retry
#     response_text = call_gemini_with_retry(model, prompt, max_retries=3)
    
#     # Tạo kết quả mặc định (Fallback) để trả về nếu AI lỗi
#     default_results = [{
#         'id_sap': m['id_sap'],
#         'material_group': 'Chưa phân loại',
#         'material_subgroup': 'Chưa phân loại'
#     } for m in materials_batch]

#     if not response_text:
#         return default_results
    
#     try:
#         clean = response_text.strip()
#         # Xử lý làm sạch markdown JSON
#         if "```json" in clean:
#             clean = clean.split("```json")[1].split("```")[0].strip()
#         elif "```" in clean:
#             clean = clean.split("```")[1].split("```")[0].strip()
        
#         results = json.loads(clean)
        
#         # Kiểm tra số lượng kết quả trả về có khớp input không
#         if len(results) != len(materials_batch):
#             print(f"WARNING: Batch materials mismatch: expected {len(materials_batch)}, got {len(results)}")
#             return default_results
        
#         return results
        
#     except Exception as e:
#         print(f"ERROR: Batch materials classification error: {e}")
#         return default_results

# def batch_classify_products(products_batch: List[Dict]) -> List[Dict]:
#     """
#     Phân loại HÀNG LOẠT sản phẩm - 1 API call cho nhiều sản phẩm
#     Input: [{'name': 'BÀN GỖ', 'id_sap': 'SP001'}, ...]
#     Output: [{'id_sap': 'SP001', 'category': 'Bàn', ...}, ...]
#     """
#     if not products_batch:
#         return []
    
#     # [FIX] Đổi sang model ổn định để tránh lỗi Rate Limit của bản Experimental
#     model = genai.GenerativeModel("gemini-2.5-flash")
    
#     # Tạo danh sách sản phẩm trong prompt
#     products_text = ""
#     for i, prod in enumerate(products_batch, 1):
#         products_text += f"{i}. ID: {prod['id_sap']}, Tên: {prod['name']}\n"
    
#     prompt = f"""
#             Bạn là chuyên gia phân loại sản phẩm nội thất cao cấp.
#             Phân loại {len(products_batch)} sản phẩm sau:
#             {products_text}
#             Mỗi sản phẩm cần phân loại theo:
#             1. category: Bàn, Ghế, Sofa, Tủ, Giường, Đèn, Kệ, Bàn làm việc, Khác
#             2. sub_category: Danh mục phụ cụ thể (VD: "Bàn ăn", "Ghế bar", "Sofa góc"...)
#             3. material_primary: Gỗ, Da, Vải, Kim loại, Đá, Kính, Nhựa, Mây tre, Hỗn hợp
#             OUTPUT JSON ARRAY ONLY (no markdown, no backticks):
#             [
#                 {{"id_sap": "SP001", "category": "...", "sub_category": "...", "material_primary": "..."}},
#                 {{"id_sap": "SP002", "category": "...", "sub_category": "...", "material_primary": "..."}}
#             ]
#     """
    
#     # Gọi AI với retry logic
#     response_text = call_gemini_with_retry(model, prompt, max_retries=3)
    
#     # Fallback mặc định nếu AI lỗi hẳn
#     default_results = [{
#         'id_sap': p['id_sap'],
#         'category': 'Chưa phân loại',
#         'sub_category': 'Chưa phân loại',
#         'material_primary': 'Chưa xác định'
#     } for p in products_batch]

#     if not response_text:
#         return default_results
    
#     try:
#         clean = response_text.strip()
#         # Xử lý trường hợp Gemini trả về markdown code block
#         if "```json" in clean:
#             clean = clean.split("```json")[1].split("```")[0].strip()
#         elif "```" in clean:
#             clean = clean.split("```")[1].split("```")[0].strip()
        
#         results = json.loads(clean)
        
#         # Đảm bảo số lượng kết quả khớp với input
#         if len(results) != len(products_batch):
#             print(f"WARNING: Batch size mismatch: expected {len(products_batch)}, got {len(results)}")
#             return default_results
        
#         return results
        
#     except Exception as e:
#         print(f"ERROR: Batch classification parse error: {e}")
#         return default_results

# # ================================================================================================
# # API ENDPOINTS
# # ================================================================================================
# @router.post("/search-image", tags=["Classifyapi"])
# async def search_by_image(
#     file: UploadFile = File(...),
#     session_id: str = Form(default=str(uuid.uuid4()))
# ):
#     """Tìm kiếm theo ảnh"""
#     file_path = f"./media/temp_{uuid.uuid4()}.jpg"
#     try:
#         # Read file content
#         contents = await file.read()
        
#         # Save to temporary file
#         with open(file_path, "wb") as buffer:
#             buffer.write(contents)
        
#         # Open image using PIL
#         img = Image.open(file_path)
#         model = genai.GenerativeModel("gemini-2.5-flash")
        
#         # prompt = """
#         # Đóng vai chuyên viên tư vấn vật tư AA corporation (Nội thất cao cấp).
#         # Phân tích ảnh nội thất này để trích xuất thông tin tìm kiếm Database.
        
#         # OUTPUT JSON ONLY (no markdown, no backticks):
#         # {
#         #     "category": "Loại SP (Bàn, Ghế, Sofa, Tủ, Giường, Đèn, Kệ...)",
#         #     "visual_description": "Mô tả chi tiết cho khách hàng hiểu sản phẩm",
#         #     "search_keywords": "CHỈ 1-2 TỪ KHÓA ĐƠN GIẢN NHẤT (VD: bàn làm việc, ghế sofa, tủ gỗ, giường ngủ)",
#         #     "material_detected": "Vật liệu chính (Gỗ, Da, Vải, Đá, Kim loại...)",
#         #     "color_tone": "Màu chủ đạo"
#         # }
        
#         # LƯU Ý: search_keywords PHẢI CỰC KỲ NGẮN GỌN, CHỈ TÊN LOẠI SẢN PHẨM. VD: "bàn làm việc" KHÔNG PHẢI "bàn làm việc gỗ hiện đại màu nâu"
#         # """
        
#         prompt = """
#         VAI TRÒ (ROLE)
#         Bạn là Chuyên viên Phân tích Vật tư Nội thất cao cấp tại AA Corporation. Bạn có kiến thức sâu rộng về vật liệu, kết cấu và phong cách thiết kế nội thất.

#         NHIỆM VỤ (TASK)
#         Phân tích hình ảnh được cung cấp và trích xuất thông tin kỹ thuật vào định dạng JSON Array (Mảng) chuẩn để nhập vào hệ thống cơ sở dữ liệu tìm kiếm.

#         CHIẾN LƯỢC DỮ LIỆU (DATA STRATEGY)
#         Output phải là một mảng chứa chính xác 2 đối tượng (objects) nhằm phục vụ cơ chế tìm kiếm đa tầng:

#         Object 1 (Ưu tiên): Tìm kiếm chính xác (Exact Match). Từ khóa phải mô tả cụ thể đặc tính nổi bật nhất của sản phẩm.

#         Object 2 (Dự phòng): Tìm kiếm mở rộng (Broad Match). Từ khóa là danh mục chung hoặc từ đồng nghĩa để đảm bảo kết quả tìm kiếm không bị rỗng nếu tìm chính xác thất bại.

#         HƯỚNG DẪN CÁC TRƯỜNG (FIELDS)
#         category: Chỉ chọn 1 danh mục chính xác nhất (VD: Ghế, Bàn, Sofa, Tủ, Đèn...).

#         visual_description: Viết đoạn văn mô tả chuyên nghiệp (catalogue). Tập trung: cấu trúc khung, chất liệu bề mặt, tính năng và cảm giác sử dụng. (Nội dung này giống nhau ở cả 2 object).

#         search_keywords:

#         Tại Object 1: Trích xuất từ khóa "ngách" cụ thể (VD: "ghế xoay lưới", "sofa da bò", "bàn ăn mặt đá").

#         Tại Object 2: Trích xuất từ khóa "gốc" phổ biến (VD: "ghế văn phòng", "sofa phòng khách", "bàn ăn").

#         material_detected: Liệt kê vật liệu nhìn thấy, ngăn cách bằng dấu phẩy. Ưu tiên từ chuyên ngành (Nhựa PP, Thép mạ chrome, Vải nỉ...).

#         color_tone: Màu sắc chủ đạo (Tối đa 2 màu).

#         ĐỊNH DẠNG OUTPUT (CONSTRAINTS)
#         Bắt buộc trả về định dạng mảng JSON: [ {...}, {...} ].

#         Không bao bọc bởi markdown (json ... ).

#         Không thêm lời dẫn hay giải thích.

#         Ngôn ngữ: Tiếng Việt.

#         VÍ DỤ MẪU (ONE-SHOT EXAMPLE)
#         Input: [Hình ảnh một chiếc ghế văn phòng lưới đen chân xoay] Output: [ { "category": "Ghế", "visual_description": "Ghế xoay văn phòng lưng trung, thiết kế khung nhựa đúc nguyên khối kết hợp lưng lưới thoáng khí. Tay vịn nhựa cố định dạng vòm. Đệm ngồi bọc vải lưới xốp êm ái. Chân ghế sao 5 cánh bằng thép mạ chrome sáng bóng, có bánh xe di chuyển và cần gạt điều chỉnh độ cao.", "search_keywords": "ghế xoay lưới", "material_detected": "Lưới, Nhựa PP, Thép mạ chrome, Vải, Mút", "color_tone": "Đen, Bạc" }, { "category": "Ghế", "visual_description": "Ghế xoay văn phòng lưng trung, thiết kế khung nhựa đúc nguyên khối kết hợp lưng lưới thoáng khí. Tay vịn nhựa cố định dạng vòm. Đệm ngồi bọc vải lưới xốp êm ái. Chân ghế sao 5 cánh bằng thép mạ chrome sáng bóng, có bánh xe di chuyển và cần gạt điều chỉnh độ cao.", "search_keywords": "ghế văn phòng", "material_detected": "Lưới, Nhựa PP, Thép mạ chrome, Vải, Mút", "color_tone": "Đen, Bạc" } ]

#         BẮT ĐẦU PHÂN TÍCH HÌNH ẢNH NÀY:
#         [AI sẽ chờ bạn upload ảnh tại đây]
#         """
        
#         response = model.generate_content([prompt, img])
        
#         # print("response Image analysis response:", response)
        
#         if not response.text:
#             return {
#                 "response": "⚠️ Không phân tích được ảnh. Vui lòng thử ảnh khác.",
#                 "products": []
#             }
        
#         clean = response.text.strip()
        
#         if "```json" in clean:
            
#             clean = clean.split("```json")[1].split("```")[0].strip()
#         elif "```" in clean:
#             clean = clean.split("```")[1].split("```")[0].strip()
        
#         try:
#             ai_result = json.loads(clean)
#         except json.JSONDecodeError as e:
#             print(f"JSON Parse Error: {e}")
#             ai_result = {
#                 "visual_description": clean[:200],
#                 "search_keywords": "",
#                 "category": "Nội thất"
#             }
        
#         # Lấy search_keywords và rút gọn nếu quá dài
#         search_keywords = ai_result[0].get("search_keywords", "").strip()
#         category = ai_result[0].get("category", "")
        
#         # Nếu search_keywords quá dài (>50 ký tự) hoặc rỗng, dùng category
#         if not search_keywords or len(search_keywords) > 50:
#             search_text = category  # Chỉ dùng category đơn giản nhất
#             print(f"INFO: Using category as search term: {search_text}")
#         else:
#             # Lấy tối đa 3 từ đầu tiên của search_keywords
#             words = search_keywords.split()[:3]
#             search_text = " ".join(words)
#             print(f"INFO: Using simplified keywords: {search_text}")
        
#         params = {
#             "category": category,
#             "keywords_vector": search_text,  # Từ khóa CỰC KỲ đơn giản
#             "material_primary": ai_result[0].get("material_detected")
#         }
        
#         search_result = search_products(params, session_id=session_id)
#         products = search_result.get("products", [])
        
#         # ========== IMAGE MATCHING VALIDATION ==========
#         # Kiểm tra sản phẩm có khớp với ai_interpretation không
#         ai_interpretation = ai_result[0].get("visual_description", "").lower()
        
#         for product in products:
#             product_name = (product.get('product_name') or '').lower()
#             category = (product.get('category') or '').lower()
            
#             # Kiểm tra tên hoặc danh mục có trong ai_interpretation không
#             name_match = any(word in ai_interpretation for word in product_name.split() if len(word) > 2)
#             category_match = category in ai_interpretation
            
#             # Nếu không khớp -> trừ base_score
#             if not name_match and not category_match:
#                 current_score = product.get('base_score', 0.5)
#                 penalty = 0.25  # Trừ 0.25 điểm
#                 product['base_score'] = max(0, current_score - penalty)
#                 product['image_mismatch'] = True
#                 product['penalty_applied'] = penalty
#                 print(f"  ⚠️ Image mismatch penalty for {product.get('headcode')}: {current_score:.3f} -> {product['base_score']:.3f}")
#             else:
#                 product['image_mismatch'] = False
        
#         # Phân loại sản phẩm theo base_score
#         products_main = [p for p in products if p.get('base_score', 0) >= 0.7]
#         products_low_confidence = [p for p in products if p.get('base_score', 0) < 0.6]
        
#         print(f"INFO: Image search - Main products: {len(products_main)}, Low confidence: {len(products_low_confidence)}")
        
#         histories.save_chat_to_histories(
#             email="test@gmail.com",
#             session_id=session_id,
#             question="[IMAGE_UPLOAD]",
#             answer=f"Phân tích ảnh: {ai_result[0].get('visual_description', 'N/A')[:100]}... | Tìm thấy {len(products_main)} sản phẩm (High confidence)"
#         )

#         # Nếu không có sản phẩm nào đạt base_score >= 0.7
#         if not products_main:
#             return {
#                 "response": f"📸 **Phân tích ảnh:** Tôi nhận thấy đây là **{ai_result[0].get('visual_description', 'sản phẩm nội thất')}**.\n\n"
#                         f"⚠️ Không tìm thấy sản phẩm phù hợp với yêu cầu.\n\n"
#                         f"💡 **Gợi ý**: Bạn có thể mô tả chi tiết hơn. Hoặc bạn có thể tìm sản phẩm khác. Tôi sẽ gợi ý cho bạn danh sách sản phẩm",
#                 "products": None,
#                 "productLowConfidence": products_low_confidence[:5] if products_low_confidence else [],
#                 "ai_interpretation": ai_result[0].get("visual_description", ""),
#                 "search_method": "image_vector"
#             }
        
#         return {
#             "response": f"📸 **Phân tích ảnh:** Tôi nhận thấy đây là **{ai_result[0].get('visual_description', 'sản phẩm')}**.\n\n"
#                        f"✅ Đã tìm thấy **{len(products_main)} sản phẩm** phù hợp:",
#             "products": products_main,
#             "productLowConfidence": products_low_confidence[:5] if products_low_confidence else [],
#             "ai_interpretation": ai_result[0].get("visual_description", ""),
#             "search_method": "image_vector",
#             "confidence_summary": {
#                 "high_confidence": len(products_main),
#                 "low_confidence": len(products_low_confidence)
#             }
#         }
    
#     except Exception as e:
#         print(f"ERROR: Image search error: {e}")
#         import traceback
#         traceback.print_exc()
        
#         return {
#             "response": f"⚠️ Lỗi xử lý ảnh: {str(e)}. Vui lòng thử lại.",
#             "products": []
#         }
    
#     finally:
#         if os.path.exists(file_path):
#             try:
#                 os.remove(file_path)
#             except:
#                 pass

# @router.post("/classify-products", tags=["Classifyapi"])
# def classify_pending_products():
#     """
#     🤖 Phân loại HÀNG LOẠT các sản phẩm chưa phân loại
#     Batch size: 8 sản phẩm/lần (tránh quá dài response)
#     """
#     try:
#         conn = get_db()
#         cur = conn.cursor(cursor_factory=RealDictCursor)
        
#         # Lấy sản phẩm chưa phân loại
#         cur.execute("""
#             SELECT headcode, id_sap, product_name 
#             FROM products_qwen 
#             WHERE category = 'Chưa phân loại' 
#                 OR sub_category = 'Chưa phân loại'
#                 OR material_primary = 'Chưa xác định'
#             LIMIT 100
#         """)
        
#         pending_products = cur.fetchall()
        
#         if not pending_products:
#             conn.close()
#             return {
#                 "message": "✅ Tất cả sản phẩm đã được phân loại!",
#                 "classified": 0,
#                 "total": 0,
#                 "remaining": 0
#             }
        
#         total_pending = len(pending_products)
#         classified = 0
#         errors = []
        
#         BATCH_SIZE = 8  # Gemini xử lý tốt với 5-10 items
        
#         for i in range(0, len(pending_products), BATCH_SIZE):
#             batch = pending_products[i:i+BATCH_SIZE]
            
#             # Chuẩn bị input cho batch classification
#             batch_input = [{
#                 'id_sap': p['id_sap'],
#                 'name': p['product_name']
#             } for p in batch]
            
#             print(f"INFO: Classifying batch {i//BATCH_SIZE + 1} ({len(batch)} products)...")
            
#             try:
#                 # GỌI BATCH CLASSIFICATION
#                 results = batch_classify_products(batch_input)
                
#                 # Cập nhật vào DB
#                 for j, result in enumerate(results):
#                     try:
#                         cur.execute("""
#                             UPDATE products_qwen 
#                             SET category = %s,
#                                 sub_category = %s,
#                                 material_primary = %s,
#                                 updated_at = NOW()
#                             WHERE headcode = %s
#                         """, (
#                             result['category'],
#                             result['sub_category'],
#                             result['material_primary'],
#                             batch[j]['headcode']
#                         ))
#                         classified += 1
#                     except Exception as e:
#                         errors.append(f"{batch[j]['headcode']}: {str(e)[:50]}")
#                 conn.commit()
#                 # Delay giữa các batch để tránh rate limit
#                 if i + BATCH_SIZE < len(pending_products):
#                     time.sleep(4)
                
#             except Exception as e:
#                 print(f"ERROR: Batch {i//BATCH_SIZE + 1} failed: {e}")
#                 errors.append(f"Batch {i//BATCH_SIZE + 1}: {str(e)[:100]}")
#                 # Tiếp tục với batch tiếp theo
#                 continue
        
#         conn.close()
        
#         # Kiểm tra còn bao nhiêu chưa phân loại
#         conn = get_db()
#         cur = conn.cursor()
#         cur.execute("""
#             SELECT COUNT(*) FROM products_qwen 
#             WHERE category = 'Chưa phân loại' 
#             OR sub_category = 'Chưa phân loại'
#             OR material_primary = 'Chưa xác định'
#         """)
#         remaining = cur.fetchone()[0]
#         conn.close()
        
#         return {
#             "message": f"✅ Đã phân loại {classified}/{total_pending} sản phẩm",
#             "classified": classified,
#             "total": total_pending,
#             "remaining": remaining,
#             "errors": errors[:10] if errors else []
#         }
        
#     except Exception as e:
#         return {
#             "message": f"❌ Lỗi: {str(e)}",
#             "classified": 0,
#             "total": 0,
#             "remaining": 0
#         }

# @router.post("/classify-materials", tags=["Classifyapi"])
# def classify_pending_materials():
#     """
#     🤖 Phân loại HÀNG LOẠT các vật liệu chưa phân loại
#     """
#     try:
#         conn = get_db()
#         cur = conn.cursor(cursor_factory=RealDictCursor)
        
#         cur.execute(f"""
#             SELECT id_sap, material_name, material_group
#             FROM {settings.MATERIALS_TABLE} 
#             WHERE material_subgroup = 'Chưa phân loại'
#             LIMIT 100
#         """)
        
#         pending_materials = cur.fetchall()
        
#         if not pending_materials:
#             conn.close()
#             return {
#                 "message": "✅ Tất cả vật liệu đã được phân loại!",
#                 "classified": 0,
#                 "total": 0,
#                 "remaining": 0
#             }
        
#         total_pending = len(pending_materials)
#         classified = 0
#         errors = []
        
#         BATCH_SIZE = 10
        
#         for i in range(0, len(pending_materials), BATCH_SIZE):
#             batch = pending_materials[i:i+BATCH_SIZE]
            
#             batch_input = [{
#                 'id_sap': m['id_sap'],
#                 'name': m['material_name']
#             } for m in batch]
            
#             print(f"BOT: Classifying materials batch {i//BATCH_SIZE + 1} ({len(batch)} items)...")
            
#             try:
#                 results = batch_classify_materials(batch_input)
                
#                 for j, result in enumerate(results):
#                     try:
#                         cur.execute("""
#                             UPDATE materials 
#                             SET material_subgroup = %s,
#                                 updated_at = NOW()
#                             WHERE id_sap = %s
#                         """, (
#                             result['material_subgroup'],
#                             batch[j]['id_sap']
#                         ))
#                         classified += 1
#                     except Exception as e:
#                         errors.append(f"{batch[j]['id_sap']}: {str(e)[:50]}")
                
#                 conn.commit()
                
#                 if i + BATCH_SIZE < len(pending_materials):
#                     time.sleep(4)
                
#             except Exception as e:
#                 print(f"ERROR: Materials batch {i//BATCH_SIZE + 1} failed: {e}")
#                 errors.append(f"Batch {i//BATCH_SIZE + 1}: {str(e)[:100]}")
#                 continue
        
#         conn.close()
        
#         conn = get_db()
#         cur = conn.cursor()
#         cur.execute(f"""
#             SELECT COUNT(*) FROM {settings.MATERIALS_TABLE} 
#             WHERE material_subgroup = 'Chưa phân loại'
#         """)
#         remaining = cur.fetchone()[0]
#         conn.close()
        
#         return {
#             "message": f"✅ Đã phân loại {classified}/{total_pending} vật liệu",
#             "classified": classified,
#             "total": total_pending,
#             "remaining": remaining,
#             "errors": errors[:10] if errors else []
#         }
        
#     except Exception as e:
#         return {
#             "message": f"❌ Lỗi: {str(e)}",
#             "classified": 0,
#             "total": 0,
#             "remaining": 0
#         }
