# app/utils.py
import re

def convert_gdrive_url(url: str) -> str:
    if "drive.google.com" not in url:
        return url

    match = re.search(r"/file/d/([^/]+)", url)
    if match:
        file_id = match.group(1)
    else:
        match = re.search(r"id=([^&]+)", url)
        file_id = match.group(1) if match else None

    if not file_id:
        return url

    return f"https://drive.google.com/uc?export=download&id={file_id}"
