"""GUI 日志系统 — 按启动批次隔离，双文件 handler + 异常钩子。

目录结构:
    logs/YYYYMMDD_HHMMSS/
        ├── app.log      (INFO+)
        ├── error.log    (ERROR+)
        └── engine/      (引擎日志，由引擎自身写入)
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
_BATCH_DIR: Path | None = None
_CONFIGURED = False


def setup_gui_logger() -> Path:
    """创建批次目录，配置日志 handler，返回批次目录路径。

    幂等: 多次调用只生效一次。
    """
    global _BATCH_DIR, _CONFIGURED
    if _CONFIGURED and _BATCH_DIR is not None:
        return _BATCH_DIR

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _BATCH_DIR = _LOG_DIR / timestamp
    _BATCH_DIR.mkdir(parents=True, exist_ok=True)

    # 确保 engine 子目录存在（引擎自身也会创建，但提前建好更稳妥）
    (_BATCH_DIR / "engine" / "nodes").mkdir(parents=True, exist_ok=True)

    # app.log: INFO 及以上
    app_handler = logging.FileHandler(_BATCH_DIR / "app.log", encoding="utf-8")
    app_handler.setLevel(logging.INFO)

    # error.log: ERROR 及以上
    err_handler = logging.FileHandler(_BATCH_DIR / "error.log", encoding="utf-8")
    err_handler.setLevel(logging.ERROR)

    # 控制台: INFO 及以上
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-5s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for h in [app_handler, err_handler, console]:
        h.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # 清空旧 handler (防重复)
    root.handlers.clear()
    root.addHandler(app_handler)
    root.addHandler(err_handler)
    root.addHandler(console)

    # 异常钩子 → 写入 error.log
    def _excepthook(exc_type, exc_value, exc_tb):
        logging.exception("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    _CONFIGURED = True
    return _BATCH_DIR


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger。"""
    return logging.getLogger(name)


def get_batch_dir() -> Path | None:
    """获取当前批次目录（未初始化则返回 None）。"""
    return _BATCH_DIR
