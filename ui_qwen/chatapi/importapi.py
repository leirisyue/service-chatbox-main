
import io
import json

import pandas as pd
import psycopg2
from fastapi import APIRouter, File, UploadFile
from config import settings
from historiesapi.histories import router as history_router
from imageapi.media import router as media_router

def get_db():
    return psycopg2.connect(**settings.DB_CONFIG)

router = APIRouter()
# ================================================================================================
# FUNCTION DEFINITIONS
# ================================================================================================

# ================================================================================================
# API ENDPOINTS
# ================================================================================================

@router.post("/import/products", tags=["Importapi"])
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
                    INSERT INTO products_qwen (
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
            SELECT COUNT(*) FROM products_qwen 
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

@router.post("/import/materials", tags=["Importapi"])
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
            SELECT COUNT(*) FROM materials_qwen 
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

@router.post("/import/product-materials", tags=["Importapi"])
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
        cur.execute("SELECT headcode FROM products_qwen")
        existing_products = {row[0] for row in cur.fetchall()}
        
        cur.execute("SELECT id_sap FROM materials_qwen")
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
