"""跨平台 Python 解释器定位。"""

from __future__ import annotations

import platform
import sys
from pathlib import Path


def resolve_python(node_path: Path) -> Path:
    """按优先级定位节点的 Python 解释器。

    优先级：
        1. 节点自身的 .venv 或 venv（BNOS 节点使用 venv 目录）
        2. 项目级 venv
        3. 系统 Python

    Args:
        node_path: 节点目录路径。

    Returns:
        可执行 Python 解释器的路径。
    """
    is_win = platform.system() == "Windows"

    # 1) 节点自身的 .venv 或 venv（BNOS 节点常用 venv 目录）
    for venv_name in (".venv", "venv"):
        if is_win:
            candidate = node_path / venv_name / "Scripts" / "python.exe"
        else:
            candidate = node_path / venv_name / "bin" / "python3"
        if candidate.exists():
            return candidate

    # 2) 项目级 venv
    project_venv = node_path.parent.parent / "venv"
    if is_win:
        candidate = project_venv / "Scripts" / "python.exe"
    else:
        candidate = project_venv / "bin" / "python3"
    if candidate.exists():
        return candidate

    # 3) 系统 Python
    return Path(sys.executable)
