# imageapi/media.py
import hashlib
import requests

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .image_cache import image_cache

router = APIRouter()

def convert_drive_url(url: str) -> str:
    """
    Convert Google Drive share URL to direct download URL
    """
    if "drive.google.com" not in url:
        return url

    if "/file/d/" in url:
        file_id = url.split("/file/d/")[1].split("/")[0]
        return f"https://drive.google.com/uc?export=download&id={file_id}"

    if "id=" in url:
        file_id = url.split("id=")[1].split("&")[0]
        return f"https://drive.google.com/uc?export=download&id={file_id}"

    return url

# ================================================================================================
# POST: tạo media từ image_url
# ================================================================================================
@router.post("/media", tags=["Media"])
def create_media(url:str, request: Request):
    # image_url = payload.get("image_url")
    image_url = url
    # if not image_url:
    #     raise HTTPDException(status_code=400, detail="image_url is required")

    # Convert Google Drive link
    direct_url = convert_drive_url(image_url)

    try:
        r = requests.get(direct_url, timeout=15)
        r.raise_for_status()
    except Exception:
        raise HTTPException(status_code=400, detail="Cannot download image")

    content_type = r.headers.get("Content-Type", "")

    # Nếu vẫn trả HTML → sai link hoặc chưa public
    if "text/html" in content_type:
        raise HTTPException(
            status_code=400,
            detail="Google Drive link is not public or not an image"
        )

    image_bytes = r.content
    media_id = hashlib.sha1(image_bytes).hexdigest()

    # Cache RAM
    image_cache[media_id] = (image_bytes, content_type)

    base_url = str(request.base_url).rstrip("/")

    return {
        "media_id": media_id,
        "url": f"{base_url}/api/media/{media_id}"
    }

# ================================================================================================
# GET: trả ảnh từ cache
# ================================================================================================

@router.get("/media/{media_id}", tags=["Media"])
def get_media(media_id: str):
    clean_id = media_id.split(".")[0]

    if clean_id not in image_cache:
        raise HTTPException(status_code=404, detail="Media not found")

    image_bytes, content_type = image_cache[clean_id]

    return Response(
        content=image_bytes,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=3600"
        }
    )
