from typing import List, Optional, Tuple
import json
from dataclasses import dataclass, field
from app.embedding import embed_text
from app.config import settings

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
            TableSchemaDesc(schema="public", table="assembly_list_data", description="vật iệu, đá, kích thước"),
            TableSchemaDesc(schema="public", table="bom_son_data", description="vật liệu sơn màu chi tiêt bom"),
        ]

    def _ensure_embeddings(self):
        for t in self.tables:
            if not t.embedding:
                t.embedding = embed_text(t.description)

    def select_best_table(self, query_text: str) -> Optional[Tuple[str, str, float]]:
        print("Selecting best table for query")
        q_emb = embed_text(query_text)
        
        best = None
        best_score = -1.0

        def cosine(a: List[float], b: List[float]) -> float:
            import math
            if not a or not b or len(a) != len(b):
                return -1.0
            dot = sum(x*y for x, y in zip(a, b))
            na = math.sqrt(sum(x*x for x in a))
            nb = math.sqrt(sum(y*y for y in b))
            if na == 0.0 or nb == 0.0:
                return -1.0
            return dot / (na * nb)

        for t in self.tables:
            s = cosine(q_emb, t.embedding)
            if s > best_score:
                best_score = s
                best = (t.schema, t.table)

        if best is None:
            return None
        return best[0], best[1], best_score

selector = TableSelector()