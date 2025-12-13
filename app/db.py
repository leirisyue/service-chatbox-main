import logging
from typing import List, Tuple, Dict, Any, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector
from pgvector.psycopg import Vector

from app.config import settings
from app.embedding_service import embedding_service

from app.logger import setup_logger
logger = setup_logger(__name__)

dsn = (
    f"host={settings.APP_PG_HOST} "
    f"port={settings.APP_PG_PORT} "
    f"dbname={settings.APP_PG_DATABASE} "
    f"user={settings.APP_PG_USER} "
    f"password={settings.APP_PG_PASSWORD}"
)

def _on_connect(conn):
    try:
        register_vector(conn)
    except Exception as e:
        logger.warning("Failed to register pgvector: %s", e)
    try:
        conn.execute("SELECT 1;")
    except Exception:
        pass

pool = ConnectionPool(conninfo=dsn, open=_on_connect, kwargs={"row_factory": dict_row})

def health_check_db() -> bool:
    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        return True
    except Exception as e:
        logger.error("DB health check failed: %s", e)
        return False

def list_embedding_tables() -> List[Tuple[str, str]]:
    q = """
    SELECT c.table_schema, c.table_name
    FROM information_schema.columns c
    WHERE c.column_name='embedding'
      AND c.table_schema NOT IN ('pg_catalog','information_schema');
    """
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(q)
        rows = cur.fetchall()
    return [(r["table_schema"], r["table_name"]) for r in rows]

def count_documents_per_table() -> Dict[str, int]:
    tables = list_embedding_tables()
    result: Dict[str, int] = {}
    with pool.connection() as conn, conn.cursor() as cur:
        for schema, table in tables:
            cur.execute(f'SELECT COUNT(*) AS c FROM "{schema}"."{table}" WHERE embedding IS NOT NULL;')
            c = cur.fetchone()["c"]
            result[f"{schema}.{table}"] = int(c)
    return result

def get_embedding_dimension(schema: str, table: str) -> Optional[int]:
    """
    Determine the dimension of the embedding vector column by reading one row.
    Returns None if not determinable.
    """
    with pool.connection() as conn, conn.cursor() as cur:
        try:
            cur.execute(f'SELECT embedding FROM "{schema}"."{table}" WHERE embedding IS NOT NULL LIMIT 1;')
            row = cur.fetchone()
            emb = row.get("embedding") if row else None
            if emb is None:
                return None
            if isinstance(emb, Vector):
                return len(list(emb))
            if isinstance(emb, (list, tuple)):
                # Column is likely wrong type (array). Fix schema to vector(N).
                return len(emb)
            try:
                return len(list(emb))
            except Exception:
                return None
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            logger.warning("Failed to read embedding dimension from %s.%s: %s", schema, table, e)
            return None

def _ensure_list(vec) -> List[float]:
    """
    Convert to list[float] and ensure no set sneaks in.
    """
    if isinstance(vec, set):
        vec = list(vec)
    if not isinstance(vec, list):
        raise TypeError(f"Embedding must be list[float], got {type(vec).__name__}")
    try:
        return [float(x) for x in vec]
    except Exception as e:
        raise TypeError(f"Embedding list must contain floats: {e}") from e

def _align_vector_dim(vec: List[float], target_dim: Optional[int]) -> List[float]:
    if target_dim is None:
        return vec
    if len(vec) == target_dim:
        return vec
    if len(vec) > target_dim:
        return vec[:target_dim]
    return vec + [0.0] * (target_dim - len(vec))

def _table_topk(schema: str, table: str, query_text: str, top_k: int) -> List[Dict[str, Any]]:
    """
    Embed text with the configured model, align dimension to table, and query top-k using pgvector operators.
    """
    # 1) Embed via Ollama
    q_vec_raw = embedding_service.embed(query_text)
    q_vec = _ensure_list(q_vec_raw)

    # 2) Align to table dimension if known
    dim = get_embedding_dimension(schema, table)
    q_vec = _align_vector_dim(q_vec, dim)
    if dim is not None:
        logger.info("Embedding model '%s': query dim=%d, aligned to table %s.%s dim=%d",
                    settings.APP_EMBEDDING_MODEL, len(q_vec_raw), schema, table, dim)

    # Pass raw list; pgvector adapter will cast to vector via ::vector
    param_vec = q_vec

    with pool.connection() as conn, conn.cursor() as cur:
        try:
            # Cosine distance
            sql = f'''
                SELECT 
                    id, original_data, content_text, 
                    (1 - (embedding::vector <=> %s::vector))::double precision AS score
                FROM "{schema}"."{table}"
                WHERE embedding IS NOT NULL
                ORDER BY embedding::vector <=> %s::vector
                LIMIT %s;
            '''
            cur.execute(sql, (param_vec, param_vec, top_k))
            return cur.fetchall()
        except Exception as e:
            logger.warning("Cosine query failed on %s.%s: %s. Falling back to Euclidean.", schema, table, e)
            try:
                conn.rollback()
            except Exception:
                pass

            # Euclidean distance (correct operator <->)
            sql = f'''
                SELECT 
                    id, original_data, content_text, 
                    (1.0 / (1.0 + (embedding::vector <-> %s::vector)))::double precision AS score
                FROM "{schema}"."{table}"
                WHERE embedding IS NOT NULL
                ORDER BY embedding::vector <-> %s::vector
                LIMIT %s;
            '''
            cur.execute(sql, (param_vec, param_vec, top_k))
            return cur.fetchall()

def similarity_search_table(schema: str, table: str, query_text: str, top_k: int, min_score: float) -> List[Dict[str, Any]]:
    rows = _table_topk(schema, table, query_text, top_k)
    out: List[Dict[str, Any]] = []
    for r in rows:
        r_out = dict(r)
        r_out["table"] = f"{schema}.{table}"
        out.append(r_out)
    out.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return [r for r in out if (r.get("score") or 0.0) >= min_score]