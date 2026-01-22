# imageapi/image_cache.py
from cachetools import TTLCache

image_cache = TTLCache(
    maxsize=1000,
    ttl=60 * 30  # 30 phút
)
