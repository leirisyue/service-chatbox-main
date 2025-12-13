import requests
from typing import List
from app.config import settings

class EmbeddingService:
    def __init__(self):
        # Thống nhất dùng OLLAMA_HOST từ settings
        self.base_url = settings.OLLAMA_HOST.rstrip("/")
        self.model = settings.APP_EMBEDDING_MODEL

    def embed(self, text: str) -> List[float]:
        url = f"{self.base_url}/api/embeddings"
        payload = {
            "model": self.model,
            "prompt": text,
        }
        try:
            resp = requests.post(url, json=payload, timeout=120)
        except Exception as e:
            raise RuntimeError(f"Error calling Ollama embeddings: {e}") from e

        if not resp.ok:
            raise RuntimeError(
                f"Ollama embedding failed. Status: {resp.status_code}, Body: {resp.text}"
            )

        data = resp.json()
        emb = data.get("embedding")
        if emb is None or not isinstance(emb, list):
            raise RuntimeError(f"Unexpected Ollama response: {data}")
        return emb

embedding_service = EmbeddingService()