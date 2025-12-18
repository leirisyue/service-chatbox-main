import logging
import os
from logging.handlers import TimedRotatingFileHandler

LOG_DIR = os.getenv("LOG_DIR", "/app/logs")
os.makedirs(LOG_DIR, exist_ok=True)

def setup_logger(name: str) -> logging.Logger:
    """
    Tạo logger:
    - Ghi ra console (stdout)
    - Ghi ra file log, xoay file theo ngày (mỗi ngày 1 file)
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Tránh add handler trùng lặp nếu setup nhiều lần
    if logger.handlers:
        return logger

    # Format chung
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Handler console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Handler file, xoay hàng ngày, giữ 7 file gần nhất (tùy chỉnh)
    log_file = os.path.join(LOG_DIR, "app.log")
    file_handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d"  # tên file dạng app.log.2025-12-11
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger