import math
import requests
from typing import List
from app.config import settings

class EmbeddingService:
    def __init__(self):
        # Thống nhất dùng OLLAMA_HOST từ settings
        self.base_url = settings.OLLAMA_HOST.rstrip("/")
        self.model = settings.APP_EMBEDDING_MODEL
        self.chunk_size = max(1, int(getattr(settings, "EMBEDDING_CHUNK_SIZE", 3000)))
        self.chunk_overlap = max(0, int(getattr(settings, "EMBEDDING_CHUNK_OVERLAP", 200)))

    def _embed_single(self, text: str) -> List[float]:
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

    def _chunk_text(self, text: str) -> List[str]:
        # Simple character-based chunking with overlap
        n = len(text)
        if n <= self.chunk_size:
            return [text]
        chunks: List[str] = []
        start = 0
        step = max(1, self.chunk_size - self.chunk_overlap)
        while start < n:
            end = min(n, start + self.chunk_size)
            chunks.append(text[start:end])
            if end == n:
                break
            start += step
        return chunks

    def _mean_pool(self, vectors: List[List[float]], weights: List[float] | None = None) -> List[float]:
        if not vectors:
            raise RuntimeError("No vectors to pool")
        dim = len(vectors[0])
        for v in vectors:
            if len(v) != dim:
                raise RuntimeError("Inconsistent embedding dimensions across chunks")
        if weights is None:
            weights = [1.0] * len(vectors)
        wsum = sum(weights)
        if wsum == 0:
            weights = [1.0] * len(vectors)
            wsum = float(len(vectors))
        pooled = [0.0] * dim
        for v, w in zip(vectors, weights):
            for i in range(dim):
                pooled[i] += v[i] * w
        return [x / wsum for x in pooled]

    def embed(self, text: str) -> List[float]:
        # If short enough, embed directly
        if len(text) <= self.chunk_size:
            return self._embed_single(text)

        # Otherwise, chunk, embed each chunk, then pool (weighted by chunk length)
        chunks = self._chunk_text(text)
        vectors: List[List[float]] = []
        weights: List[float] = []
        for ch in chunks:
            vec = self._embed_single(ch)
            vectors.append(vec)
            weights.append(float(len(ch)))
        return self._mean_pool(vectors, weights)

embedding_service = EmbeddingService()