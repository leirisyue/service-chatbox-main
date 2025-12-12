from typing import List, Optional
import google.generativeai as genai
from PIL.Image import Image as PILImage
from app.config import settings

# Configure once
if settings.GOOGLE_API_KEY:
    genai.configure(api_key=settings.GOOGLE_API_KEY)

def health_check_gemini() -> bool:
    try:
        m = _resolve_supported_model()
        if not m:
            return False
        model = genai.GenerativeModel(m)
        _ = model.generate_content("ping", generation_config={"max_output_tokens": 1})
        return True
    except Exception:
        return False

SYSTEM_PROMPT = (
    "Bạn là trợ lý AI cho hệ thống RAG. Trả lời ngắn gọn, đúng trọng tâm, bằng tiếng Việt khi có thể. "
    "Chỉ dựa vào CONTEXT cung cấp; nếu thiếu thông tin thì nói rõ là không chắc chắn."
)

def generate_answer(
    user_query: str,
    contexts: List[str],
    images: Optional[List[PILImage]] = None,
) -> str:
    """
    Gọi Gemini để sinh câu trả lời, truyền cả ảnh (nếu có).
    """
    print(f"Generating answer with Gemini: ")
    parts: List = [SYSTEM_PROMPT]
    if contexts:
        ctx_joined = "\n\n---- CONTEXT ----\n" + "\n\n".join(contexts) + "\n-----------------\n"
        parts.append(ctx_joined)
    parts.append(f"Câu hỏi của người dùng: {user_query}")

    if images:
        # Append images to multimodal prompt
        parts.extend(images)

    # Resolve a model that supports generateContent for the current API
    m = _resolve_supported_model()
    if not m:
        return "Xin lỗi, không tìm thấy model Gemini hỗ trợ generateContent trong API hiện tại. Vui lòng kiểm tra API key và quyền truy cập."
    try:
        model = genai.GenerativeModel(m)
        resp = model.generate_content(parts, safety_settings=None)
        text = (getattr(resp, "text", None) or "").strip()
        print(f"Gemini response text (model={m}): {text}")
        if text:
            return text
    except Exception as e:
        return "Xin lỗi, lỗi gọi Gemini generateContent với model '" + m + "': " + str(e)
    return "Xin lỗi, tôi chưa thể trả lời câu hỏi này."

def _resolve_supported_model() -> Optional[str]:
    """Pick a model that supports generateContent from the account's available models.
    Preference order: env-configured model, then any 'flash' model, then any 'pro' model.
    """
    print(f"Resolving supported model: ")
    try:
        # List models available to the API key
        ms = genai.list_models()
        available = []
        for m in ms:
            # Some client versions expose supported methods via 'supported_generation_methods'
            methods = getattr(m, "supported_generation_methods", None)
            if methods and ("generateContent" in methods or "generate_content" in methods):
                available.append(m.name)
        if not available:
            return None
        # If the configured model is available, prefer it
        if settings.APP_GEMINI_MODEL in available:
            return settings.APP_GEMINI_MODEL
        # Prefer flash models
        for name in available:
            if "flash" in name:
                return name
        # Else fall back to any
        return available[0]
    except Exception:
        # If listing fails, try a small known-good set
        fallbacks = [settings.APP_GEMINI_MODEL, "gemini-2.0-flash"]
        for name in fallbacks:
            try:
                model = genai.GenerativeModel(name)
                # Lightweight check: do not call API here
                return name
            except Exception:
                continue
        return None