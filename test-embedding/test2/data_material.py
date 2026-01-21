
import json
import os
import time
import uuid
from typing import Dict, List

import google.generativeai as genai
import psycopg2
from fastapi import APIRouter

router = APIRouter()
# ================================================================================================
# FUNCTION DEFINITIONS
# ================================================================================================
My_GOOGLE_API_KEY = os.getenv("My_GOOGLE_API_KEY", "localhost") 

# ================= CONFIG GEMINI =================
genai.configure(
    api_key=os.getenv("GOOGLE_API_KEY")
)

# =================================================
def batch_classify_materials(materials_batch: List[Dict]) -> List[Dict]:
    """
    Input:
    [
        {"ID_Material_SAP": "M001", "name": "Gỗ sồi tự nhiên"}
    ]

    Output (LUÔN ĐỦ FIELD):
    [
        {
            "ID_Material_SAP": "M001",
            "material_group": "Gỗ",
            "material_subgroup": "Gỗ tự nhiên"
        }
    ]
    """

    if not materials_batch:
        return []

    model = genai.GenerativeModel("gemini-2.5-flash-lite")

    materials_text = "\n".join(
        f"{i}. ID: {m['ID_Material_SAP']}, Name: {m['name']}"
        for i, m in enumerate(materials_batch, 1)
    )

    prompt = f"""
            You are a classification API.

            Return ONLY valid JSON.
            No markdown.
            No explanation.
            No extra text.

            Classify {len(materials_batch)} interior materials.

            {materials_text}

            Rules:
            - material_group ∈ [Gỗ, Da, Vải, Đá, Kim loại, Kính, Nhựa, Sơn, Keo, Phụ kiện, Khác]
            - material_subgroup: short Vietnamese noun phrase

            JSON format:
            [
            {{
                "ID_Material_SAP": "M001",
                "material_group": "Gỗ",
                "material_subgroup": "Gỗ tự nhiên"
            }}
            ]
            """

    response_text = call_gemini_with_retry(model, prompt)

    # ================= FALLBACK =================
    fallback = {
        m["ID_Material_SAP"]: {
            "ID_Material_SAP": m["ID_Material_SAP"],
            "material_group": "Not classified",
            "material_subgroup": "Not classified",
        }
        for m in materials_batch
    }

    # ✅ FIX CỨNG: KHÔNG PARSE RESPONSE RỖNG
    if not response_text or not response_text.strip():
        print("WARNING: Gemini returned empty response")
        return list(fallback.values())

    try:
        clean = response_text.strip()

        if "```" in clean:
            clean = clean.split("```")[1].strip()

        results = json.loads(clean)

        for r in results:
            if "ID_Material_SAP" not in r:
                continue

            fallback[r["ID_Material_SAP"]] = {
                "ID_Material_SAP": r["ID_Material_SAP"],
                "material_group": r.get("material_group", "Not classified"),
                "material_subgroup": r.get("material_subgroup", "Not classified"),
            }

        return list(fallback.values())

    except Exception as e:
        print(f"ERROR: parse Gemini response failed: {e}")
        return list(fallback.values())

# =================================================
def call_gemini_with_retry(model, prompt, max_retries=3, timeout=20):
    import signal

    def timeout_handler(signum, frame):
        raise TimeoutError("Gemini API timeout")

    for attempt in range(max_retries):
        try:
            if hasattr(signal, "SIGALRM"):
                signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(timeout)

            response = model.generate_content(
                prompt,
                request_options={"timeout": timeout}
            )

            if hasattr(signal, "SIGALRM"):
                signal.alarm(0)

            if response and response.text and response.text.strip():
                return response.text

            # ⚠️ empty response → retry
            print("WARNING: Gemini empty response, retrying...")
            time.sleep(2)

        except TimeoutError:
            print(f"WARNING: Gemini timeout on attempt {attempt + 1}")
        except Exception as e:
            print(f"ERROR Gemini: {e}")
            time.sleep(2)

    return None