import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from datetime import datetime
from app.core.config import settings


def setup_logging():
    """
    Ghi log mỗi ngày 1 file:
    logs/app-2026-01-05.log
    logs/app-2026-01-06.log
    """

    log_dir = Path(settings.LOG_DIR if hasattr(settings, "LOG_DIR") else "logs")
    log_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"app-{today}.log"

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    # Handler ghi file (xoay mỗi ngày)
    file_handler = TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=14,        # giữ 14 ngày log
        encoding="utf-8",
        utc=False,
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    # Handler console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Tránh add handler nhiều lần (uvicorn reload)
    if not root_logger.handlers:
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)

    logging.info("Logging initialized")
