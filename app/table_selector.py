from typing import List, Optional, Tuple
import json
from dataclasses import dataclass, field
from app.embedding import embed_text
from app.config import settings
from app.logger import setup_logger

logger = setup_logger(__name__)

@dataclass
class TableSchemaDesc:
    schema: str
    table: str
    description: str
    embedding: List[float] = field(default_factory=list)

class TableSelector:
    def __init__(self):
        self.tables: List[TableSchemaDesc] = []
        self._load_schemas()
        self._ensure_embeddings()

    def _load_schemas(self):
        raw = (getattr(settings, "APP_TABLE_SCHEMAS_JSON", None) or "").strip()
        if raw:
            try:
                data = json.loads(raw)
                for item in data:
                    self.tables.append(TableSchemaDesc(
                        schema=item["schema"],
                        table=item["table"],
                        description=item["description"],
                    ))
                return
            except Exception:
                pass
        # Mặc định — cập nhật theo thực tế
        self.tables = [
            TableSchemaDesc(schema="public", table="bompk_data", description="vật iệu, đá, kích thước"),
            TableSchemaDesc(schema="public", table="bom_son_data", description="vật liệu sơn màu chi tiêt bom"),
        ]

    def _ensure_embeddings(self):
        for t in self.tables:
            if not t.embedding:
                t.embedding = embed_text(t.description) # lấy description

    def select_best_table(self, query_text: str) -> Optional[Tuple[str, str, float]]:
        print("Selecting best table for query: ")
        # tinh vector query
        q_emb = embed_text(query_text)
        
        best = None
        best_score = -1.0

        def cosine(a: List[float], b: List[float]) -> float:
            import math
            if not a or not b:
                return -1.0
            if len(a) != len(b):
                return -1.0
            dot = sum(x*y for x, y in zip(a, b))
            na = math.sqrt(sum(x*x for x in a))
            nb = math.sqrt(sum(y*y for y in b))
            if na == 0.0 or nb == 0.0:
                return -1.0
            return dot / (na * nb)
        
        q_lower = (query_text or "").strip().lower()
        keywords = [w for w in q_lower.split() if w]

        def keyword_boost(desc: str) -> float:
            if not keywords or not desc:
                return 0.0
            d = desc.lower()
            hits = sum(1 for k in keywords if k in d)
            return min(1.0, hits / max(1, len(keywords)))

        COSINE_WEIGHT = 0.7
        KEYWORD_WEIGHT = 0.3

        for t in self.tables:
            s_cos = cosine(q_emb, t.embedding)
            s_kw = keyword_boost(t.description)
            s = (COSINE_WEIGHT * max(0.0, s_cos)) + (KEYWORD_WEIGHT * s_kw)
            print(f"Table {t.schema}.{t.table} score: cosine={s_cos:.4f}, keyword={s_kw:.4f}, total={s:.4f}")
            if s > best_score:
                best_score = s
                best = (t.schema, t.table)

        MIN_CONFIDENCE = 0.2
        if best is None:
            return None
        if best_score < MIN_CONFIDENCE:
            print(f"Low confidence ({best_score:.4f}); no suitable table selected.")
            return None
        return best[0], best[1], best_score

selector = TableSelector()