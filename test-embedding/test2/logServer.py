
import logging
import os
import time


def setup_logging(log_dir: str = "logs", name: str = "embed_test") -> str:
    """
    Tạo thư mục logs/ nếu chưa có, tạo file log với timestamp.
    Trả về đường dẫn file log.
    """
    os.makedirs(log_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d")
    log_path = os.path.join(log_dir, f"{name}_{timestamp}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler()
        ],
    )
    logging.info(f"Logging to {log_path}")
    return log_path
