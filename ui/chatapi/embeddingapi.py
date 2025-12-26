
from fastapi import APIRouter
from psycopg2.extras import RealDictCursor
import psycopg2
from psycopg2.extras import RealDictCursor
import google.generativeai as genai
import time
import psycopg2
from config import settings


def get_db():
    return psycopg2.connect(**settings.DB_CONFIG)

router = APIRouter()
# Configure once
if settings.My_GOOGLE_API_KEY:
    genai.configure(api_key=settings.My_GOOGLE_API_KEY)
    
# ========================================
# FUNCTION DEFINITIONS
# ========================================

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
        print(f"ERROR embedding: {e}")
        return None

# ========================================
# API ENDPOINTS
# ========================================

@router.post("/generate-embeddings")
def generate_product_embeddings():
    """Táº¡o embeddings cho products"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT headcode, product_name, category, sub_category, material_primary
        FROM products_gemi 
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
                    UPDATE products_gemi 
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

@router.post("/generate-material-embeddings")
def generate_material_embeddings():
    """Táº¡o embeddings cho materials"""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT id_sap, material_name, material_group, material_subgroup
        FROM materials_gemi 
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
        "message": f"Tạo embeddings cho {success}/{len(materials)} materials",
        "success": success,
        "total": len(materials),
        "errors": errors[:5] if errors else []
    }
