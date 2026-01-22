
from fastapi import APIRouter
from psycopg2.extras import RealDictCursor
import psycopg2
from psycopg2.extras import RealDictCursor
import google.generativeai as genai
import time
import psycopg2
import requests
from config import settings
import os

def get_db():
    return psycopg2.connect(**settings.DB_CONFIG)

router = APIRouter()
# Configure once
if settings.My_GOOGLE_API_KEY:
    genai.configure(api_key=settings.My_GOOGLE_API_KEY)

# Qwen configuration - now using settings
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
QWEN_EMBED_MODEL = settings.QWEN_MODEL
QWEN_TIMEOUT = settings.QWEN_TIMEOUT
    
# ================================================================================================
# FUNCTION DEFINITIONS
# ================================================================================================

def generate_embedding_qwen(text: str):
    try:
        url = f"{OLLAMA_HOST}/api/embeddings"
        payload = {
            "model": QWEN_EMBED_MODEL,
            "prompt": text,
        }
        resp = requests.post(url, json=payload, timeout=QWEN_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        
        # Get embedding from response
        emb = data.get("embedding") or data.get("data", [{}])[0].get("embedding")
        if emb is None:
            raise ValueError(f"Qwen API response has no 'embedding': {data}")
        
        return emb
    except Exception as e:
        print(f"⚠️ ERROR Qwen embedding: {e}")
        
# ================================================================================================
# API ENDPOINTS
# ================================================================================================

@router.post("/generate-embeddings-qwen", tags=["Embeddingapi"])
def generate_product_embeddings_qwen():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get products not yet in qwen table
    cur.execute("""
        SELECT p.headcode, p.product_name, p.category, p.sub_category, p.material_primary
        FROM products_qwen p
        LEFT JOIN qwen q ON q.table_name = 'products_qwen' AND q.record_id = p.headcode
        WHERE q.record_id IS NULL
        LIMIT 100
    """)
    
    products = cur.fetchall()
    
    if not products:
        conn.close()
        return {"message": "✅ All products_qwen already have embeddings in qwen table"}
    
    success = 0
    errors = []
    
    for prod in products:
        try:
            name_text = f"{prod['product_name']}"
            name_emb = generate_embedding_qwen(name_text)
            
            desc_text = f"{prod['product_name']} {prod.get('category', '')} {prod.get('sub_category', '')} {prod.get('material_primary', '')}"
            desc_emb = generate_embedding_qwen(desc_text)
            
            if name_emb and desc_emb:
                # Insert into qwen table
                cur.execute("""
                    INSERT INTO products_qwen (table_name, record_id, name_embedding, description_embedding, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (table_name, record_id) 
                    DO UPDATE SET 
                        name_embedding = EXCLUDED.name_embedding,
                        description_embedding = EXCLUDED.description_embedding,
                        updated_at = NOW()
                """, ('products', prod['headcode'], name_emb, desc_emb))
                
                success += 1
                time.sleep(0.5)
            
        except Exception as e:
            errors.append(f"{prod['headcode']}: {str(e)[:50]}")
    
    conn.commit()
    conn.close()
    
    return {
        "message": f"✅ Đã tạo embeddings cho {success}/{len(products)} products (Qwen3)",
        "success": success,
        "total": len(products),
        "errors": errors[:5] if errors else []
    }

@router.post("/generate-material-embeddings-qwen", tags=["Embeddingapi"])
def generate_material_embeddings_qwen():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Get materials not in qwen table
    cur.execute(f"""
        SELECT m.id_sap, m.material_name, m.material_group, m.material_subgroup
        FROM {settings.MATERIALS_TABLE} m
        LEFT JOIN qwen q ON q.table_name = '{settings.MATERIALS_TABLE}' AND q.record_id = m.id_sap
        WHERE q.record_id IS NULL
        LIMIT 100
    """)
    
    materials = cur.fetchall()
    
    if not materials:
        conn.close()
        return {"message": "✅ Tất cả materials đã có embeddings trong bảng qwen"}
    
    success = 0
    errors = []
    
    for mat in materials:
        try:
            name_text = f"{mat['material_name']}"
            name_emb = generate_embedding_qwen(name_text)
            
            desc_text = f"{mat['material_name']} {mat.get('material_group', '')} {mat.get('material_subgroup', '')}"
            desc_emb = generate_embedding_qwen(desc_text)
            
            if name_emb and desc_emb:
                # Insert into qwen table
                cur.execute(f"""
                    INSERT INTO {settings.MATERIALS_TABLE} (table_name, record_id, name_embedding, description_embedding, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, NOW(), NOW())
                    ON CONFLICT (table_name, record_id) 
                    DO UPDATE SET 
                        name_embedding = EXCLUDED.name_embedding,
                        description_embedding = EXCLUDED.description_embedding,
                        updated_at = NOW()
                """, ('materials', mat['id_sap'], name_emb, desc_emb))
                
                success += 1
                time.sleep(0.5)
            
        except Exception as e:
            errors.append(f"{mat['id_sap']}: {str(e)[:50]}")
    
    conn.commit()
    conn.close()
    
    return {
        "message": f"✅ Đã tạo embeddings cho {success}/{len(materials)} materials (Qwen3)",
        "success": success,
        "total": len(materials),
        "errors": errors[:5] if errors else []
    }
