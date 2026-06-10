"""日誌初始化：檔案日誌讓所有搬移操作可事後回溯"""
import logging
import os
from datetime import datetime

from .config import LOG_DIR

logger = logging.getLogger("javrename")

LOG_FORMAT = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')


def init_logging() -> logging.Logger:
    """初始化檔案日誌（重複呼叫不會疊加 handler）"""
    if any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        return logger

    logger.setLevel(logging.INFO)
    os.makedirs(LOG_DIR, exist_ok=True)
    file_handler = logging.FileHandler(
        os.path.join(LOG_DIR, f"javrename_{datetime.now():%Y%m%d}.log"),
        encoding="utf-8",
    )
    file_handler.setFormatter(LOG_FORMAT)
    logger.addHandler(file_handler)
    return logger
