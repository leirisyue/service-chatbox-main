
import json
import os
import time
import uuid
from typing import Dict, List

import google.generativeai as genai
import psycopg2
from fastapi import (APIRouter, File, Form, UploadFile)
from historiesapi import histories
from PIL import Image
from psycopg2.extras import RealDictCursor

from .textfunc import call_gemini_with_retry,format_suggested_prompts
from .textapi_qwen import generate_suggested_prompts, search_products
from config import settings

def get_db():
    return psycopg2.connect(**settings.DB_CONFIG)

router = APIRouter()
# ================================================================================================
# FUNCTION DEFINITIONS
# ================================================================================================
    
def batch_classify_materials(materials_batch: List[Dict]) -> List[Dict]:
    if not materials_batch:
        return []
    
    # [FIX] Switch to gemini-1.5-flash model for better stability and to avoid Rate Limit errors
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
    
    # Call Gemini with retry
    response_text = call_gemini_with_retry(model, prompt, max_retries=3)
    
    # Create default results (Fallback) to return if AI fails
    default_results = [{
        'id_sap': m['id_sap'],
        'material_group': 'Not classified',
        'material_subgroup': 'Not classified'
    } for m in materials_batch]

    if not response_text:
        return default_results
    
    try:
        clean = response_text.strip()
        # Clean markdown JSON
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        
        results = json.loads(clean)
        
        # Check if number of results matches input
        if len(results) != len(materials_batch):
            print(f"WARNING: Batch materials mismatch: expected {len(materials_batch)}, got {len(results)}")
            return default_results
        
        return results
        
    except Exception as e:
        print(f"ERROR: Batch materials classification error: {e}")
        return default_results

def batch_classify_products(products_batch: List[Dict]) -> List[Dict]:
    if not products_batch:
        return []
    
    # [FIX] Switch to stable model to avoid Rate Limit errors from Experimental version
    model = genai.GenerativeModel("gemini-2.5-flash")
    
    # Create product list in prompt
    products_text = ""
    for i, prod in enumerate(products_batch, 1):
        products_text += f"{i}. ID: {prod['id_sap']}, Name: {prod['name']}\n"
    
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
    
    # Call AI with retry logic
    response_text = call_gemini_with_retry(model, prompt, max_retries=3)
    
    # Default fallback if AI completely fails
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
        # Handle case when Gemini returns markdown code block
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        
        results = json.loads(clean)
        
        # Ensure result count matches input
        if len(results) != len(products_batch):
            print(f"WARNING: Batch size mismatch: expected {len(products_batch)}, got {len(results)}")
            return default_results
        
        return results
        
    except Exception as e:
        print(f"ERROR: Batch classification parse error: {e}")
        return default_results

# ================================================================================================
# API ENDPOINTS
# ================================================================================================
@router.post("/search-image", tags=["Classifyapi"])
async def search_by_image(
    file: UploadFile = File(...),
    session_id: str = Form(default=str(uuid.uuid4()))
):
    file_path = f"./media/temp_{uuid.uuid4()}.jpg"
    try:
        # Read file content
        contents = await file.read()
        
        # Save to temporary file
        with open(file_path, "wb") as buffer:
            buffer.write(contents)
        
        # Open image using PIL
        img = Image.open(file_path)
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        prompt = """
            ROLE
            You are a Senior Interior Materials Analyst at AA Corporation. You have deep knowledge of materials, construction, and interior design styles.

            TASK
            Analyze the provided image and extract technical information into a standard JSON Array format for input into the database search system.

            CHIẾN LƯỢC DỮ LIỆU (DATA STRATEGY)
            Output phải là một mảng chứa chính xác 2 đối tượng (objects) nhằm phục vụ cơ chế tìm kiếm đa tầng:

            Object 1 (Ưu tiên): Tìm kiếm chính xác (Exact Match). Từ khóa phải mô tả cụ thể đặc tính nổi bật nhất của sản phẩm, bao gồm hình thái và công dụng.

            Object 2 (Dự phòng): Tìm kiếm mở rộng (Broad Match). Từ khóa là danh mục chung hoặc từ đồng nghĩa để đảm bảo kết quả tìm kiếm không bị rỗng nếu tìm chính xác thất bại.

            HƯỚNG DẪN CÁC TRƯỜNG (FIELDS)
            category: Chỉ chọn 1 danh mục chính xác nhất (VD: Ghế, Bàn, Sofa, Tủ, Đèn...).

            visual_description: Viết đoạn văn mô tả chuyên nghiệp (catalogue). Tập trung: cấu trúc khung, chất liệu bề mặt, tính năng và cảm giác sử dụng. (Nội dung này giống nhau ở cả 2 object).

            search_keywords:

            Tại Object 1: Trích xuất từ khóa "ngách" cụ thể, mô tả chi tiết (VD: "ghế xoay lưới", "sofa da bò", "bàn ăn mặt đá", "ghế văn phòng công thái học",...).

            Tại Object 2: Trích xuất từ khóa "gốc" phổ biến (VD: "ghế văn phòng", "sofa phòng khách", "bàn ăn",..).

            material_detected: Liệt kê vật liệu nhìn thấy, ngăn cách bằng dấu phẩy. Ưu tiên từ chuyên ngành (Nhựa PP, Thép mạ chrome, Vải nỉ...).

            color_tone: Màu sắc chủ đạo (Tối đa 2 màu).

            ĐỊNH DẠNG OUTPUT (CONSTRAINTS)
            Bắt buộc trả về định dạng mảng JSON: [ {...}, {...} ].

            Không bao bọc bởi markdown (json ... ).

            Không thêm lời dẫn hay giải thích.

            Ngôn ngữ: Tiếng Việt.

            VÍ DỤ MẪU (ONE-SHOT EXAMPLE)
            Input: [Hình ảnh một chiếc ghế văn phòng lưới đen chân xoay] Output: [ { "category": "Ghế", "visual_description": "Ghế xoay văn phòng lưng trung, thiết kế khung nhựa đúc nguyên khối kết hợp lưng lưới thoáng khí. Tay vịn nhựa cố định dạng vòm. Đệm ngồi bọc vải lưới xốp êm ái. Chân ghế sao 5 cánh bằng thép mạ chrome sáng bóng, có bánh xe di chuyển và cần gạt điều chỉnh độ cao.", "search_keywords": "ghế xoay lưới", "material_detected": "Lưới, Nhựa PP, Thép mạ chrome, Vải, Mút", "color_tone": "Đen, Bạc" }, { "category": "Ghế", "visual_description": "Ghế xoay văn phòng lưng trung, thiết kế khung nhựa đúc nguyên khối kết hợp lưng lưới thoáng khí. Tay vịn nhựa cố định dạng vòm. Đệm ngồi bọc vải lưới xốp êm ái. Chân ghế sao 5 cánh bằng thép mạ chrome sáng bóng, có bánh xe di chuyển và cần gạt điều chỉnh độ cao.", "search_keywords": "ghế văn phòng", "material_detected": "Lưới, Nhựa PP, Thép mạ chrome, Vải, Mút", "color_tone": "Đen, Bạc" } ]

            BẮT ĐẦU PHÂN TÍCH HÌNH ẢNH NÀY
        """
        
        response = model.generate_content([prompt, img])
        
        # print("response Image analysis response:", response)
        
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
                "search_keywords": "",
                "category": "Nội thất"
            }
        
        print(f"INFO: AI Image Analysis Result: {ai_result}")
        # Get search_keywords and shorten if too long
        search_keywords = ai_result[0].get("search_keywords", "").strip()
        category = ai_result[0].get("category", "")
        
        # If search_keywords too long (>50 chars) or empty, use category
        if not search_keywords or len(search_keywords) > 50:
            search_text = category  # Only use simplest category
            print(f"INFO: Using category as search term: {search_text}")
        else:
            # Get max first 3 words of search_keywords
            words = search_keywords.split()[:3]
            search_text = " ".join(words)
            print(f"INFO: Using simplified keywords: {search_text}")
        
        # Get secondary keywords from ai_result[1] if available (for better matching)
        secondary_keywords = ""
        secondary_category = ""
        secondary_material = ""
        
        if len(ai_result) > 1:
            secondary_keywords = ai_result[1].get("search_keywords", "").strip()
            secondary_category = ai_result[1].get("category", "")
            secondary_material = ai_result[1].get("material_detected", "")
            print(f"INFO: Using secondary keywords from AI: {secondary_keywords}")
        
        # ========== PARALLEL SEARCH WITH BOTH MAIN & SECONDARY KEYWORDS ==========
        params = {
            "category": category,
            "keywords_vector": search_text,  # EXTREMELY simple keywords
            "material_primary": ai_result[0].get("material_detected"),
            "main_keywords": ai_result[0].get("search_keywords"),
            "secondary_keywords": secondary_keywords,
            "secondary_category": secondary_category,
            "secondary_material": secondary_material,
        }
        
        print(f"INFO: Parallel search - Main: {ai_result[0].get('search_keywords')}, Secondary: {secondary_keywords}")
        
        # Disable automatic fallback in search_products, we handle dual search here
        search_result = search_products(params, session_id=session_id, disable_fallback=True)
        
        products = search_result.get("products", [])
        products_second = search_result.get("products_second", [])
        
        # Handle case when search_products returns None or empty
        if products is None:
            products = []
        if products_second is None:
            products_second = []
        
        print(f"INFO: Parallel search results - Products: {len(products)}, Products second: {len(products_second)}")
        
        # ========== IMAGE MATCHING VALIDATION ==========
        # Products already have base_score from parallel search, just apply image matching validation
        ai_interpretation = ai_result[0].get("visual_description", "").lower()
        
        for product in products:
            product_name = (product.get('product_name') or '').lower()
            category_prod = (product.get('category') or '').lower()
            
            # Check if name or category is in ai_interpretation
            name_match = any(word in ai_interpretation for word in product_name.split() if len(word) > 2)
            category_match = category_prod in ai_interpretation
            
            # If no match → deduct base_score
            if not name_match and not category_match:
                current_score = product.get('base_score', 0.6)
                penalty = 0.25  # Deduct 0.25 points
                product['base_score'] = max(0, current_score - penalty)
                product['image_mismatch'] = True
                product['penalty_applied'] = penalty
                print(f"  ⚠️ Image mismatch penalty for {product.get('headcode')}: {current_score:.3f} -> {product['base_score']:.3f}")
            else:
                product['image_mismatch'] = False
        
        # # Apply same validation for products_second if they exist
        # if products_second and len(ai_result) > 1:
        #     ai_interpretation_second = ai_result[1].get("visual_description", "").lower()
            
        #     for product in products_second:
        #         product_name = (product.get('product_name') or '').lower()
        #         category_prod = (product.get('category') or '').lower()
                
        #         name_match = any(word in ai_interpretation_second for word in product_name.split() if len(word) > 2)
        #         category_match = category_prod in ai_interpretation_second
                
        #         if not name_match and not category_match:
        #             current_score = product.get('base_score', 0.5)
        #             penalty = 0.25
        #             product['base_score'] = max(0, current_score - penalty)
        #             product['image_mismatch'] = True
        #             product['penalty_applied'] = penalty
        #             print(f"  ⚠️ Image mismatch penalty (2nd) for {product.get('headcode')}: {current_score:.3f} -> {product['base_score']:.3f}")
        #         else:
        #             product['image_mismatch'] = False
        
        print(f"\nINFO: Image search completed. Total Products: found: {products:}\n")
        print(f"\nINFO: Image search completed. Total Products second: found: {products_second:}\n")
        # Classify products by base_score
        products_main = [p for p in products if p.get('final_score', 0) >= 0.75]
        products_low_confidence = [p for p in products if p.get('similarity', 0) < 0.6]
        products_second_main = [p for p in products_second if p.get('similarity', 0) >= 0.6 and p.get('final_score', 0) < 0.75] if products_second else []
        
        print(f"INFO: Image search - Main products: {len(products_main)}, Products second: {len(products_second_main)}, Low confidence: {len(products_low_confidence)}")
        
        histories.save_chat_to_histories(
            email="test@gmail.com",
            session_id=session_id,
            question="[IMAGE_UPLOAD]",
            answer=f"Phân tích ảnh: {ai_result[0].get('visual_description', 'N/A')[:100]}... | Tìm thấy {len(products_main)} sản phẩm theo yêu cầu của bạn, {len(products_second_main)} sản phẩm phụ"
        )
        response_msg = ""
        # Build response message based on results
        if products_main or products_second_main:
            response_msg = f"📋 **Phân tích ảnh:** Tôi nhận thấy đây là **{ai_result[0].get('visual_description', 'sản phẩm')}**.\n\n"
            if products_main:
                response_msg += f"✅ Dựa trên hình ảnh bạn đã tải lên, tôi có **{len(products_main)} sản phẩm theo yêu cầu của bạn** gợi ý cho bạn"
            # if products_second_main:
            #     response_msg += f"{', và ' if products_main else '✅ Tôi có '}**{len(products_second_main)} sản phẩm tương tự** với yêu cầu trên của bạn! Bạn có thể tham khảo"
            # response_msg += ":"
        if not products_main and products_second_main:
            response_msg = f"📋 **Phân tích ảnh:** Tôi nhận thấy đây là **{ai_result[0].get('visual_description', 'sản phẩm nội thất')}**.\n\n"
            response_msg += f"⚠️ Rất tiếc, tôi chưa tìm thấy sản phẩm hoàn toàn phù hợp với yêu cầu của bạn trong cơ sở dữ liệu.\n\n" 
            # response_msg += f"✅ Tuy nhiên, tôi có **{len(products_second_main)} sản phẩm tương tự** với yêu cầu của bạn! Bạn có thể tham khảo:"
        else:
            response_msg = f"📋 **Phân tích ảnh:** Tôi nhận thấy đây là **{ai_result[0].get('visual_description', 'sản phẩm nội thất')}**.\n\n"
            response_msg += f"💔  Thật xin lỗi tôi không tìm thấy sản phẩm phù hợp với yêu cầu của bạn trong cơ sở dữ liệu.\n"
            response_msg = f"📋 **Phân tích ảnh:** Tôi nhận thấy đây là **{ai_result[0].get('visual_description', 'sản phẩm nội thất')}**.\n\n" \
                            f"💔  Thật xin lỗi, rất tiếc tôi không tìm thấy sản phẩm phù hợp với yêu cầu của bạn.\n\n" \
                            f"⭐ **Ghi chú**: Bạn có thể mô tả chi tiết hơn. Hoặc bạn có thể tìm sản phẩm khác. Tôi sẽ gợi ý cho bạn danh sách sản phẩm"

        tmp = generate_suggested_prompts(
                        "search_product_not_found",
                        {"query": "Tìm sản phẩm trong ảnh"}
                    )
        suggested_prompts_mess = format_suggested_prompts(tmp)
        return {
            "response": response_msg,
            "products": products_main if products_main else None,
            "products_second": products_second_main if products_second_main else None,
            "productLowConfidence": products_low_confidence[:5] if products_low_confidence else [],
            "ai_interpretation": ai_result[0].get("visual_description", ""),
            "search_method": "image_vector_dual_search",
            "confidence_summary": {
                "products_main_count": len(products_main),
                "products_second_count": len(products_second_main),
                "low_confidence": len(products_low_confidence)
            },
            "success": True,
            "suggested_prompts_mess": suggested_prompts_mess
        }
    
    except Exception as e:
        print(f"ERROR: Image search error: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            "response": f"⚠️ Lỗi xử lý ảnh: {str(e)}. Vui lòng thử lại.",
            "products": [],
            "success": False,
        }
    
    finally:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass

@router.post("/classify-products", tags=["Classifyapi"])
def classify_pending_products():
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get unclassified products
        cur.execute("""
            SELECT headcode, id_sap, product_name 
            FROM products_qwen 
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
        
        BATCH_SIZE = 8  # Gemini handles well with 5-10 items
        
        for i in range(0, len(pending_products), BATCH_SIZE):
            batch = pending_products[i:i+BATCH_SIZE]
            
            # Prepare input for batch classification
            batch_input = [{
                'id_sap': p['id_sap'],
                'name': p['product_name']
            } for p in batch]
            
            print(f"INFO: Classifying batch {i//BATCH_SIZE + 1} ({len(batch)} products)...")
            
            try:
                # CALL BATCH CLASSIFICATION
                results = batch_classify_products(batch_input)
                
                # Update to DB
                for j, result in enumerate(results):
                    try:
                        cur.execute("""
                            UPDATE products_qwen 
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
                # Delay between batches to avoid rate limit
                if i + BATCH_SIZE < len(pending_products):
                    time.sleep(4)
                
            except Exception as e:
                print(f"ERROR: Batch {i//BATCH_SIZE + 1} failed: {e}")
                errors.append(f"Batch {i//BATCH_SIZE + 1}: {str(e)[:100]}")
                # Continue with next batch
                continue
        
        conn.close()
        
        # Check how many remain unclassified
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM products_qwen 
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

@router.post("/classify-materials", tags=["Classifyapi"])
def classify_pending_materials():
    """
    🤖 Phân loại HÀNG LOẠT các vật liệu chưa phân loại
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute(f"""
            SELECT id_sap, material_name, material_group
            FROM {settings.MATERIALS_TABLE} 
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
            
            print(f"BOT: Classifying materials batch {i//BATCH_SIZE + 1} ({len(batch)} items)...")
            
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
                print(f"ERROR: Materials batch {i//BATCH_SIZE + 1} failed: {e}")
                errors.append(f"Batch {i//BATCH_SIZE + 1}: {str(e)[:100]}")
                continue
        
        conn.close()
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute(f"""
            SELECT COUNT(*) FROM {settings.MATERIALS_TABLE} 
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

@router.post("/search-image-with-text", tags=["Classifyapi"])
async def search_by_image_with_text(
    file: UploadFile = File(...),
    description: str = Form(...),
    session_id: str = Form(default=str(uuid.uuid4()))
):
    file_path = f"./media/temp_{uuid.uuid4()}.jpg"
    try:
        # Read and save uploaded file
        contents = await file.read()
        with open(file_path, "wb") as buffer:
            buffer.write(contents)
        
        # Open image with PIL
        img = Image.open(file_path)
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        # Enhanced prompt that combines image analysis with user's text description
        prompt = f"""
            ROLE
            You are a Senior Interior Materials Analyst at AA Corporation with expertise in analyzing products based on both visual and textual information.

            TASK
            Analyze the provided image AND the user's description to extract comprehensive technical information for database search.

            USER'S DESCRIPTION & REQUIREMENTS:
            {description}

            CHIẾN LƯỢC DỮ LIỆU (DATA STRATEGY)
            Output phải là một mảng chứa chính xác 2 đối tượng (objects):

            Object 1 (Ưu tiên): Kết hợp thông tin từ hình ảnh VÀ mô tả của user để tạo từ khóa tìm kiếm chính xác nhất.
            - Ưu tiên các yêu cầu cụ thể từ user (màu sắc, kích thước, chất liệu, phong cách...)
            - Kết hợp với đặc điểm nổi bật từ hình ảnh

            Object 2 (Dự phòng): Tìm kiếm mở rộng dựa trên danh mục chung.

            HƯỚNG DẪN CÁC TRƯỜNG (FIELDS)
            category: Danh mục sản phẩm (Ghế, Bàn, Sofa, Tủ, Đèn, Giường, Kệ...)

            visual_description: Mô tả chuyên nghiệp kết hợp:
            - Những gì nhìn thấy từ hình ảnh
            - Yêu cầu cụ thể từ mô tả của user
            - Phong cách, chất liệu, màu sắc, kích thước...

            search_keywords:
            - Object 1: Từ khóa chi tiết kết hợp yêu cầu user + đặc điểm hình ảnh
            - Object 2: Từ khóa tổng quát hơn

            material_detected: Vật liệu nhìn thấy từ hình ảnh hoặc được user đề cập

            color_tone: Màu sắc (từ hình ảnh hoặc yêu cầu của user)

            user_requirements: Tóm tắt các yêu cầu đặc biệt của user (kích thước, giá, tính năng...)

            ĐỊNH DẠNG OUTPUT
            Trả về JSON array: [ {{...}}, {{...}} ]
            Không dùng markdown, không giải thích thêm.
            Ngôn ngữ: Tiếng Việt.

            VÍ DỤ:
            User description: "Tôi cần ghế văn phòng màu xám, có tựa lưng cao, giá dưới 3 triệu"
            Output: [
                {{
                    "category": "Ghế",
                    "visual_description": "Ghế văn phòng công thái học lưng cao, khung nhựa PP đen kết hợp lưới thoáng khí màu xám. Tay vịn nhựa chữ T điều chỉnh được. Đệm ngồi bọc vải màu xám xốp êm. Chân sao 5 cánh thép mạ có bánh xe, cần nâng hạ khí nén. Thiết kế theo yêu cầu: màu xám, lưng cao, phù hợp văn phòng.",
                    "search_keywords": "ghế văn phòng lưng cao xám",
                    "material_detected": "Lưới, Nhựa PP, Thép mạ, Vải",
                    "color_tone": "Xám, Đen",
                    "user_requirements": "Màu xám, tựa lưng cao, giá < 3 triệu"
                }},
                {{
                    "category": "Ghế",
                    "visual_description": "Ghế văn phòng công thái học lưng cao, khung nhựa PP đen kết hợp lưới thoáng khí màu xám. Tay vịn nhựa chữ T điều chỉnh được. Đệm ngồi bọc vải màu xám xốp êm. Chân sao 5 cánh thép mạ có bánh xe, cần nâng hạ khí nén.",
                    "search_keywords": "ghế văn phòng",
                    "material_detected": "Lưới, Nhựa PP, Thép mạ, Vải",
                    "color_tone": "Xám, Đen",
                    "user_requirements": "Màu xám, tựa lưng cao, giá < 3 triệu"
                }}
            ]

            BẮT ĐẦU PHÂN TÍCH HÌNH ẢNH NÀY
        """
        
        # Generate content with both image and prompt
        response = model.generate_content([prompt, img])
        
        if not response.text:
            return {
                "response": "⚠️ Không phân tích được ảnh và mô tả. Vui lòng thử lại.",
                "products": []
            }
        
        # Parse AI response
        clean = response.text.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0].strip()
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0].strip()
        try:
            ai_result = json.loads(clean)
        except json.JSONDecodeError as e:
            print(f"JSON Parse Error: {e}")
            return {
                "response": "⚠️ Lỗi phân tích dữ liệu. Vui lòng thử lại.",
                "products": [],
                "success": False,
            }
        
        print(f"INFO: AI Image+Text Analysis Result: {ai_result}")
        
        # Extract search parameters from AI result
        search_keywords = ai_result[0].get("search_keywords", "").strip()
        category = ai_result[0].get("category", "")
        user_requirements = ai_result[0].get("user_requirements", "")
        
        # Prepare search text
        if not search_keywords or len(search_keywords) > 50:
            search_text = category
            print(f"INFO: Using category as search term: {search_text}")
        else:
            words = search_keywords.split()[:4]  # Use up to 4 words for better matching
            search_text = " ".join(words)
            print(f"INFO: Using keywords: {search_text}")
        
        # Get secondary keywords if available
        secondary_keywords = ""
        secondary_category = ""
        if len(ai_result) > 1:
            secondary_keywords = ai_result[1].get("search_keywords", "").strip()
            secondary_category = ai_result[1].get("category", "")
        
        # Prepare search parameters
        params = {
            "category": category,
            "keywords_vector": search_text,
            "material_primary": ai_result[0].get("material_detected"),
            "main_keywords": search_keywords,
            "secondary_keywords": secondary_keywords,
            "secondary_category": secondary_category,
            "user_description": description  # Include original user description
        }
        
        print(f"INFO: Search params - Main: {search_keywords}, Secondary: {secondary_keywords}")
        print(f"INFO: User requirements: {user_requirements}")
        
        # Execute search
        search_result = search_products(params, session_id=session_id, disable_fallback=True)
        
        products = search_result.get("products", []) or []
        products_second = search_result.get("products_second", []) or []
        
        print(f"INFO: Search results - Main: {len(products)}, Secondary: {len(products_second)}")
        
        # Validate products against image and text description
        ai_interpretation = ai_result[0].get("visual_description", "").lower()
        description_lower = description.lower()
        
        for product in products:
            product_name = (product.get('product_name') or '').lower()
            category_prod = (product.get('category') or '').lower()
            
            # Check match with AI interpretation and user description
            name_match = any(word in ai_interpretation or word in description_lower 
                            for word in product_name.split() if len(word) > 2)
            category_match = category_prod in ai_interpretation or category_prod in description_lower
            
            if not name_match and not category_match:
                current_score = product.get('base_score', 0.6)
                penalty = 0.2
                product['base_score'] = max(0, current_score - penalty)
                product['mismatch'] = True
                print(f"  ⚠️ Mismatch penalty for {product.get('headcode')}: {current_score:.3f} -> {product['base_score']:.3f}")
            else:
                product['mismatch'] = False
        
        # Classify products by confidence score
        products_main = [p for p in products if p.get('final_score', 0) >= 0.75]
        products_second_main = [p for p in products_second if p.get('similarity', 0) >= 0.6 and p.get('final_score', 0) < 0.75] if products_second else []
        products_low_confidence = [p for p in products if p.get('similarity', 0) < 0.6]
        
        print(f"INFO: Final results - Main: {len(products_main)}, Secondary: {len(products_second_main)}, Low: {len(products_low_confidence)}")
        
        # Save to chat history
        histories.save_chat_to_histories(
            email="test@gmail.com",
            session_id=session_id,
            question=f"[IMAGE+TEXT] {description[:100]}...",
            answer=f"Phân tích: {ai_result[0].get('visual_description', '')[:100]}... | Tìm thấy {len(products_main)} sản phẩm phù hợp với yêu cầu, {len(products_second_main)} sản phẩm phụ"
        )
        
        # Build response message
        if products_main or products_second_main:
            response_msg = f"🎉 **Phân tích hình ảnh và yêu cầu của bạn:**\n\n"
            response_msg += f"🔍 **Mô tả sản phẩm:** {ai_result[0].get('visual_description', 'N/A')}\n\n"
            if user_requirements:
                response_msg += f"✨ **Yêu cầu của bạn:** {user_requirements}\n\n"
            
            if products_main:
                response_msg += f"✅ Tôi tìm thấy **{len(products_main)} sản phẩm phù hợp** với yêu cầu của bạn"
            if products_main and products_second_main:
                response_msg += f"Những sản phẩm trên có phù hợp với yêu cầu của bạn không?. Nếu không hãy để tôi tìm kiếm thêm cho bạn"
            
            response_msg += "!"
        if not products_main and products_second_main:
            response_msg = f"🎉 **Phân tích hình ảnh và yêu cầu của bạn:**\n\n"
            response_msg += f"🔍 **Mô tả sản phẩm:** {ai_result[0].get('visual_description', 'N/A')}\n\n"
            if user_requirements:
                response_msg += f"✨ **Yêu cầu của bạn:** {user_requirements}\n\n"
            response_msg += f"⚠️ Rất tiếc, tôi chưa tìm thấy sản phẩm hoàn toàn phù hợp với yêu cầu của bạn trong cơ sở dữ liệu.\n\n"
            # response_msg += f"✅ Tôi tìm thấy **{len(products_second_main)} sản phẩm tương tự** với yêu cầu của bạn! Bạn có thể tham khảo:"
        else:
            response_msg = f"🎉 **Phân tích hình ảnh và yêu cầu:**\n\n"
            response_msg += f"🔍 **Mô tả:** {ai_result[0].get('visual_description', 'N/A')}\n\n"
            if user_requirements:
                response_msg += f"✨ **Yêu cầu:** {user_requirements}\n\n"
            response_msg += f"⚠️ Rất tiếc, tôi chưa tìm thấy sản phẩm hoàn toàn phù hợp với yêu cầu của bạn.\n\n"
            response_msg += f"⭐ **Ghi chú:** Bạn có thể thử mô tả chi tiết hơn hoặc điều chỉnh yêu cầu của bạn."

        tmp = generate_suggested_prompts(
                        "search_product_not_found",
                        {"query": user_requirements}
                    )
        suggested_prompts_mess = format_suggested_prompts(tmp)
        
        return {
            "response": response_msg,
            "products": products_main if products_main else None,
            "products_second": products_second_main if products_second_main else None,
            "products_low_confidence": products_low_confidence[:5] if products_low_confidence else [],
            "ai_interpretation": ai_result[0].get("visual_description", ""),
            "user_requirements": user_requirements,
            "search_method": "image_text_combined_search",
            "confidence_summary": {
                "products_main_count": len(products_main),
                "products_second_count": len(products_second_main),
                "low_confidence_count": len(products_low_confidence)
            },
            "success": True,
            "suggested_prompts_mess": suggested_prompts_mess
        }
    
    except Exception as e:
        print(f"ERROR: Image+Text search error: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            "response": f"⚠️ Lỗi xử lý: {str(e)}. Vui lòng thử lại.",
            "products": [],
            "success": False,
        }
    
    finally:
        # Clean up temporary file
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
