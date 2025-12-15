from typing import List, Optional, Tuple, Dict, Any
import json
import google.generativeai as genai
from dataclasses import dataclass
from app.config import settings

from .logger import setup_logger

logger = setup_logger(__name__)

@dataclass
class TableSchemaDesc:
    schema: str
    table: str
    description: str
    columns: Optional[str] = None  # Mô tả các cột quan trọng

class TableSelectorLLM:
    """
    Sử dụng Gemini LLM để phân tích câu hỏi và chọn bảng phù hợp nhất
    thay vì dùng embedding similarity
    """
    
    def __init__(self):
        self.tables: List[TableSchemaDesc] = []
        self._load_schemas()
        
        if settings.GOOGLE_API_KEY:
            genai.configure(api_key=settings.GOOGLE_API_KEY)
        else:
            logger.warning("GOOGLE_API_KEY not configured for TableSelector")
    
    def _load_schemas(self):
        """Load table schemas từ config hoặc mặc định"""
        raw = (getattr(settings, "APP_TABLE_SCHEMAS_JSON", None) or "").strip()
        if raw:
            try:
                data = json.loads(raw)
                for item in data:
                    self.tables.append(TableSchemaDesc(
                        schema=item.get("schema", "public"),
                        table=item["table"],
                        description=item["description"],
                        columns=item.get("columns", None)
                    ))
                logger.info(f"Loaded {len(self.tables)} table schemas from config")
                return
            except Exception as e:
                logger.error(f"Failed to parse APP_TABLE_SCHEMAS_JSON: {e}")
        
        # Mặc định - cập nhật theo thực tế của bạn
        self.tables = [
            TableSchemaDesc(
                schema="public", 
                table="bompk_data",
                description="Chứa thông tin về vật liệu, đá, kích thước, trọng lượng của các assembly/sản phẩm",
                columns="original_data, original_data, content_text, embedding, created_at"
            ),
            TableSchemaDesc(
                schema="public", 
                table="bom_son_data",
                description="Chứa chi tiết BOM (Bill of Materials) về màu sơn, mã màu, thành phần chi tiết",
                columns="original_data, original_data, content_text, embedding, created_at"
            ),
        ]
        logger.info(f"Using {len(self.tables)} default table schemas")
    
    def _build_selection_prompt(self, query_text: str) -> str:
        """Xây dựng prompt cho LLM để chọn bảng"""
        
        # Format danh sách bảng
        tables_info = []
        for idx, t in enumerate(self.tables, 1):
            info = f"{idx}. Bảng: {t.schema}.{t.table}\n"
            info += f"   Mô tả: {t.description}\n"
            if t.columns:
                info += f"   Cột chính: {t.columns}\n"
            tables_info.append(info)
        
        tables_text = "\n".join(tables_info)
        
        prompt = f"""Bạn là một chuyên gia phân tích database. Nhiệm vụ của bạn là chọn bảng phù hợp nhất để trả lời câu hỏi của người dùng.

                    DANH SÁCH CÁC BẢNG AVAILABLE:
                    {tables_text}

                    CÂU HỎI CỦA NGƯỜI DÙNG:
                    "{query_text}"

                    YÊU CẦU:
                    1. Phân tích câu hỏi và xác định bảng nào chứa thông tin cần thiết
                    2. Có thể chọn nhiều bảng nếu cần kết hợp dữ liệu
                    3. Trả về kết quả dưới dạng JSON với format:
                    {{
                        "selected_tables": [
                            {{
                                "schema": "schema_name",
                                "table": "table_name",
                                "confidence": 0.95,
                                "reason": "Lý do chọn bảng này"
                            }}
                        ],
                        "analysis": "Phân tích ngắn gọn về câu hỏi"
                    }}

                    4. confidence là số từ 0.0 đến 1.0 (càng cao càng chắc chắn)
                    5. Chỉ chọn bảng có confidence >= 0.5
                    6. Sắp xếp theo độ ưu tiên giảm dần

                    CHÚ Ý: Chỉ trả về JSON, không thêm text nào khác.
                """

        return prompt
    
    def select_tables_with_llm(
        self, 
        query_text: str,
        max_tables: int = 3,
        min_confidence: float = 0.5
    ) -> List[Tuple[str, str, float, str]]:
        """
        Sử dụng Gemini LLM để chọn bảng
        
        Returns:
            List of (schema, table, confidence, reason)
        """
        if not self.tables:
            logger.warning("No tables configured")
            return []
        
        if not settings.GOOGLE_API_KEY:
            logger.error("Cannot use LLM selector without GOOGLE_API_KEY")
            # Fallback: trả về tất cả bảng với confidence thấp
            return [(t.schema, t.table, 0.3, "No LLM available") for t in self.tables]
        
        try:
            prompt = self._build_selection_prompt(query_text)
            
            # Gọi Gemini
            model = genai.GenerativeModel(settings.APP_GEMINI_MODEL)
            response = model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.1,  # Thấp để output ổn định hơn
                    "max_output_tokens": 1000,
                }
            )
            
            response_text = response.text.strip()
            logger.info(f"LLM response: {response_text[:200]}...")
            
            # Parse JSON response
            # Remove markdown code blocks if present
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            result = json.loads(response_text)
            
            # Extract selected tables
            selected = []
            for item in result.get("selected_tables", []):
                confidence = float(item.get("confidence", 0.0))
                if confidence >= min_confidence:
                    selected.append((
                        item["schema"],
                        item["table"],
                        confidence,
                        item.get("reason", "")
                    ))
            
            # Sort by confidence descending
            selected.sort(key=lambda x: x[2], reverse=True)
            
            # Limit number of tables
            selected = selected[:max_tables]
            
            logger.info(f"LLM selected {len(selected)} tables: {[(s[1], s[2]) for s in selected]}")
            return selected
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON response: {e}\nResponse: {response_text}")
            # Fallback: chọn bảng đầu tiên
            if self.tables:
                return [(self.tables[0].schema, self.tables[0].table, 0.5, "JSON parse error - fallback")]
            return []
            
        except Exception as e:
            logger.error(f"LLM table selection failed: {e}", exc_info=True)
            # Fallback: trả về bảng đầu tiên
            if self.tables:
                return [(self.tables[0].schema, self.tables[0].table, 0.4, f"Error: {str(e)}")]
            return []
    
    def select_best_table(
        self, 
        query_text: str
    ) -> Optional[Tuple[str, str, float]]:
        """
        Wrapper để tương thích với code cũ.
        Chỉ trả về 1 bảng tốt nhất.
        
        Returns:
            (schema, table, confidence) hoặc None
        """
        results = self.select_tables_with_llm(query_text, max_tables=1)
        if results:
            schema, table, confidence, _ = results[0]
            return (schema, table, confidence)
        return None
    
    def get_tables_info_for_context(self) -> str:
        """
        Trả về mô tả các bảng để thêm vào context cho LLM answer generation
        """
        info_parts = []
        for t in self.tables:
            info = f"- {t.schema}.{t.table}: {t.description}"
            if t.columns:
                info += f" (Cột: {t.columns})"
            info_parts.append(info)
        return "\n".join(info_parts)

# Singleton instance
selector = TableSelectorLLM()