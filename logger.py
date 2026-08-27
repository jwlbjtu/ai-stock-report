"""日志初始化：控制台 + 滚动文件，幂等。"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "app.log"

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """配置根 logger（控制台 + 文件）。重复调用不会重复添加 handler。"""
    root = logging.getLogger()
    root.setLevel(level)

    if root.handlers:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=7, encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger。"""
    return logging.getLogger(name)
