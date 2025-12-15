from typing import List
import requests
from tenacity import retry, stop_after_attempt, wait_fixed
from app.config import settings

@retry(stop=stop_after_attempt(3), wait=wait_fixed(0.5))
def embed_text(text: str) -> List[float]:
    url = f"{settings.OLLAMA_HOST.rstrip('/')}/api/embeddings"
    # url = f"{settings.OLLAMA_HOST.rstrip('/')}"
    print('Embedding text via Ollama: ', url)
    payload = {
        "model": settings.APP_EMBEDDING_MODEL,
        "prompt": text
    }
    r = requests.post(url, json=payload, timeout=60)
    # chuyen query thanh vector
    # print('Ollama response:', r.text)
    r.raise_for_status()
    data = r.json()
    if "embedding" in data:
        return data["embedding"]
    # Some servers return {"data": {"embedding": ...}}
    return data.get("data", {}).get("embedding", [])

def health_check_ollama() -> bool:
    try:
        _ = embed_text("ping")
        return True
    except Exception:
        return False