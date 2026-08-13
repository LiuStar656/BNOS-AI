"""
通用文件工具
适配自 BNOS 参考项目，移除 BNOS 特定依赖
"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path


def get_project_root():
    """获取当前项目根目录"""
    current_path = Path(__file__).resolve().parent
    while current_path != current_path.parent:
        if (
            (current_path / "main.py").exists()
            or (current_path / "README.md").exists()
            or (current_path / "nodes").exists()
        ):
            return str(current_path)
        current_path = current_path.parent
    return str(Path.cwd())


def open_folder(path):
    """在系统文件管理器中打开指定路径

    Args:
        path: 文件夹路径

    Returns:
        bool: 是否成功打开
    """
    try:
        resolved = str(Path(path).resolve())
        system = platform.system()
        if system == "Windows":
            subprocess.Popen(["explorer", resolved])
        elif system == "Darwin":
            subprocess.Popen(["open", resolved])
        else:
            subprocess.Popen(["xdg-open", resolved])
        return True
    except Exception:
        return False


def open_terminal_in_directory(directory, terminal_type="default"):
    """在指定目录中打开终端

    Args:
        directory: 目录路径
        terminal_type: 终端类型 ("default", "powershell", "cmd")

    Returns:
        bool: 是否成功打开
    """
    try:
        system = platform.system()
        directory = str(Path(directory).resolve())

        if not Path(directory).exists():
            return False

        if system == "Windows":
            if terminal_type == "powershell":
                ps_cmd = f"Set-Location -LiteralPath '{directory}'"
                subprocess.Popen(
                    ["powershell.exe", "-NoExit", "-Command", ps_cmd],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            elif terminal_type == "cmd":
                subprocess.Popen(
                    ["cmd", "/k", "cd", "/d", directory],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            else:
                ps_cmd = f"Set-Location -LiteralPath '{directory}'"
                subprocess.Popen(
                    ["powershell.exe", "-NoExit", "-Command", ps_cmd],
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
        elif system == "Darwin":
            script = f"""tell application "Terminal"
                do script "cd '{directory}'"
            end tell"""
            subprocess.Popen(["osascript", "-e", script])
        else:
            for terminal in ["gnome-terminal", "konsole", "xterm", "xfce4-terminal"]:
                try:
                    subprocess.Popen([terminal, "--working-directory", directory])
                    return True
                except Exception:
                    continue
            return False

        return True
    except Exception:
        return False


def ensure_dir(path):
    """确保目录存在，如不存在则创建

    Args:
        path: 目录路径

    Returns:
        str: 规范化后的目录路径
    """
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return str(p.resolve())
