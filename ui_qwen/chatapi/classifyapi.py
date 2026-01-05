
import json
import os
import time
import uuid
from typing import Dict, List, Optional

import google.generativeai as genai
import psycopg2
from fastapi import (APIRouter, File, Form, UploadFile)
from historiesapi import histories
from PIL import Image
from psycopg2.extras import RealDictCursor

from .textfunc import call_gemini_with_retry
from .textapi_qwen import search_products
from config import settings

def get_db():
    return psycopg2.connect(**settings.DB_CONFIG)

router = APIRouter()
# ================================================================================================
# FUNCTION DEFINITIONS
# ================================================================================================
    
def batch_classify_materials(materials_batch: List[Dict]) -> List[Dict]:
    """
    Phân loại HÀNG LOẠT vật liệu
    Input: [{'name': 'GỖ SỒI', 'id_sap': 'M001'}, ...]
    Output: [{'id_sap': 'M001', 'material_group': 'Gỗ', ...}, ...]
    """
    if not materials_batch:
        return []
    
    # [FIX] Đổi sang model gemini-1.5-flash để ổn định hơn và tránh lỗi Rate Limit
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
            print(f"WARNING: Batch materials mismatch: expected {len(materials_batch)}, got {len(results)}")
            return default_results
        
        return results
        
    except Exception as e:
        print(f"ERROR: Batch materials classification error: {e}")
        return default_results

def batch_classify_products(products_batch: List[Dict]) -> List[Dict]:
    """
    Phân loại HÀNG LOẠT sản phẩm - 1 API call cho nhiều sản phẩm
    Input: [{'name': 'BÀN GỖ', 'id_sap': 'SP001'}, ...]
    Output: [{'id_sap': 'SP001', 'category': 'Bàn', ...}, ...]
    """
    if not products_batch:
        return []
    
    # [FIX] Đổi sang model ổn định để tránh lỗi Rate Limit của bản Experimental
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    
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
            print(f"WARNING: Batch size mismatch: expected {len(products_batch)}, got {len(results)}")
            return default_results
        
        return results
        
    except Exception as e:
        print(f"ERROR: Batch classification parse error: {e}")
        return default_results

# ================================================================================================
# API ENDPOINTS
# ================================================================================================
@router.post("/search-image")
async def search_by_image(
    file: UploadFile = File(...),
    session_id: str = Form(default=str(uuid.uuid4()))
):
    """Tìm kiếm theo ảnh"""
    file_path = f"./media/temp_{uuid.uuid4()}.jpg"
    try:
        # Read file content
        contents = await file.read()
        
        # Save to temporary file
        with open(file_path, "wb") as buffer:
            buffer.write(contents)
        
        # Open image using PIL
        img = Image.open(file_path)
        model = genai.GenerativeModel("gemini-2.5-flash-lite")
        
        prompt = """
        Đóng vai chuyên viên tư vấn vật tư AA corporation (Nội thất cao cấp).
        Phân tích ảnh nội thất này để trích xuất thông tin tìm kiếm Database.
        Phân tích chi tiết về hình dáng, vật liệu, màu sắc, phong cách thiết kế.
        Trả lời như một chuyên viên bán hàng chuyên nghiệp.
        
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
        
        search_result = search_products(params, session_id=session_id)
        products = search_result.get("products", [])
        
        histories.save_chat_to_histories(
            email="test@gmail.com",
            session_id=session_id,
            question="[IMAGE_UPLOAD]",
            answer=f"Phân tích ảnh: {ai_result.get('visual_description', 'N/A')[:100]}... | Tìm thấy {len(products)} sản phẩm"
        )

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
        print(f"ERROR: Image search error: {e}")
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

@router.post("/classify-products")
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
        
        BATCH_SIZE = 8  # Gemini xử lý tốt với 5-10 items
        
        for i in range(0, len(pending_products), BATCH_SIZE):
            batch = pending_products[i:i+BATCH_SIZE]
            
            # Chuẩn bị input cho batch classification
            batch_input = [{
                'id_sap': p['id_sap'],
                'name': p['product_name']
            } for p in batch]
            
            print(f"INFO: Classifying batch {i//BATCH_SIZE + 1} ({len(batch)} products)...")
            
            try:
                # GỌI BATCH CLASSIFICATION
                results = batch_classify_products(batch_input)
                
                # Cập nhật vào DB
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
                # Delay giữa các batch để tránh rate limit
                if i + BATCH_SIZE < len(pending_products):
                    time.sleep(4)
                
            except Exception as e:
                print(f"ERROR: Batch {i//BATCH_SIZE + 1} failed: {e}")
                errors.append(f"Batch {i//BATCH_SIZE + 1}: {str(e)[:100]}")
                # Tiếp tục với batch tiếp theo
                continue
        
        conn.close()
        
        # Kiểm tra còn bao nhiêu chưa phân loại
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

@router.post("/classify-materials")
def classify_pending_materials():
    """
    🤖 Phân loại HÀNG LOẠT các vật liệu chưa phân loại
    """
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT id_sap, material_name, material_group
            FROM materials_qwen 
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
        cur.execute("""
            SELECT COUNT(*) FROM materials_qwen 
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
