"""精简日志模块 — 运行时引擎使用，无 GUI 依赖。"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path


_LOG_FMT = logging.Formatter(
    "[%(asctime)s] %(levelname)-5s (%(filename)s:%(lineno)d): %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def setup_logger(
    name: str = "BNOS-Runtime",
    log_file: str | Path | None = None,
    level: int = logging.INFO,
) -> logging.Logger:
    """配置并返回运行时日志记录器。

    Args:
        name: 日志记录器名称。
        log_file: 日志文件路径（可选）。不指定则仅输出到 stdout。
        level: 日志级别。

    Returns:
        配置好的日志记录器。
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)

    # 控制台处理器：INFO+
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(_LOG_FMT)
    logger.addHandler(console)

    # 文件处理器（可选）
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,  # 5MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(_LOG_FMT)
        logger.addHandler(file_handler)

    return logger


# 全局日志记录器实例
logger = setup_logger()
