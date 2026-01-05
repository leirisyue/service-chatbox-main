import time
import requests
from typing import List, Tuple, Any
from app.core.config import settings
from .func import insert_embedding_rows


def embed_with_qwen_service(
    table_name: str,
    texts: List[str],
    raw_rows: List[Any],
) -> dict:
    url = f"{settings.QWEN_API_BASE}/api/embeddings"
    
    embeddings = []
    start = time.time()

    for t in texts:
        payload = {
            "model": settings.QWEN_EMBED_MODEL,
            "prompt": t,
        }
        resp = requests.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

        emb = data.get("embedding") or data.get("data", [{}])[0].get("embedding")
        if emb is None:
            raise ValueError("Qwen response missing embedding")

        embeddings.append(emb)

    elapsed = time.time() - start

    insert_embedding_rows(
        model="qwen",
        table_name=table_name,
        texts=texts,
        raw_rows=raw_rows,
        embeddings=embeddings,
    )

    return {
        "table": table_name,
        "rows": len(embeddings),
        "time_sec": round(elapsed, 2),
    }


