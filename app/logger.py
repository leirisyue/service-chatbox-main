import logging
import os
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

LOG_DIR = os.getenv("LOG_DIR", "/app/logs")
os.makedirs(LOG_DIR, exist_ok=True)


class TZFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt=fmt, datefmt=datefmt)
        tz_name = os.getenv("TZ", "Asia/Ho_Chi_Minh")
        if ZoneInfo:
            try:
                self.tz = ZoneInfo(tz_name)
            except Exception:
                self.tz = ZoneInfo("Asia/Ho_Chi_Minh")
        else:
            self.tz = timezone(timedelta(hours=7))

    def formatTime(self, record, datefmt=None):
        dt_utc = datetime.utcfromtimestamp(record.created).replace(
            tzinfo=timezone.utc
        )
        dt = dt_utc.astimezone(self.tz)
        return dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S")


class DailyLogFileHandler(TimedRotatingFileHandler):
    """
    Handler ghi log theo format:
    app-log-YYYY-MM-DD.log
    """

    def __init__(self, log_dir, **kwargs):
        today = datetime.now().strftime("%Y-%m-%d")
        filename = os.path.join(log_dir, f"app-log-{today}.log")

        super().__init__(
            filename,
            when="midnight",
            interval=1,
            backupCount=7,
            encoding="utf-8",
            utc=False,
            **kwargs,
        )

    def rotation_filename(self, default_name):
        # Không cho dạng app-log-YYYY-MM-DD.log.2025-12-15
        return default_name


def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = TZFormatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File
    file_handler = DailyLogFileHandler(LOG_DIR)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger
