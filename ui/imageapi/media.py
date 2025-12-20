# app/media.py
import hashlib
import os
import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .utils import convert_gdrive_url

router = APIRouter()

MEDIA_DIR = "media"
os.makedirs(MEDIA_DIR, exist_ok=True)

class ImageRequest(BaseModel):
    image_url: str

class ImageResponse(BaseModel):
    local_url: str

@router.post("/media", response_model=ImageResponse)
def create_media(req: ImageRequest):
    if not req.image_url:
        raise HTTPException(status_code=400, detail="image_url required")

    direct_url = convert_gdrive_url(req.image_url)

    # hash URL → tên file ổn định
    file_hash = hashlib.sha1(direct_url.encode()).hexdigest()
    file_path = f"{MEDIA_DIR}/{file_hash}.jpg"

    if not os.path.exists(file_path):
        r = requests.get(
            direct_url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail="Cannot fetch image")

        with open(file_path, "wb") as f:
            f.write(r.content)

    return {
        "local_url": f"/media/{file_hash}.jpg"
    }
