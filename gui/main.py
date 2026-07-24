"""BNOS AI 伴侣 — 新 GUI 入口

数据流：GUI -> gui_input.json -> aaa_cognition (中枢, 合并了旧 gui_adapter+user_input)
                                     <- gui_reply.json <-

启动流程：
1. 清理旧的输出文件
2. 启动引擎（拉起所有节点）
3. 启动 GUI
4. GUI 关闭时自动清理引擎
"""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

# 将项目根目录加入 sys.path，确保 from gui.xxx 导入可用
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from gui.main_window import MainWindow
from gui.pages.node_page import NodePage


def _cleanup_gui_adapter():
    """启动时清理 gui_reply.json，避免残留数据干扰"""
    reply_path = Path(_project_root) / "nodes" / "shared" / "gui_reply.json"
    if reply_path.exists():
        try:
            reply_path.unlink()
        except OSError:
            pass


def _start_engine():
    """启动引擎进程（运行 bnos_runtime/engine.py）"""
    pipeline_path = Path(_project_root) / "pipeline.json"

    # 使用系统 Python 启动引擎（非 GUI venv，因为引擎无 GUI 依赖）
    # 重要：使用 -m 方式启动，确保引擎内部 from bnos_runtime.xxx 导入正常
    python_exe = sys.executable

    # 设置环境变量（解决编码问题）
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    # 把项目根目录加入 PYTHONPATH，确保 -m bnos_runtime.engine 能正常工作
    env.setdefault("PYTHONPATH", "")
    paths = [p for p in env["PYTHONPATH"].split(os.pathsep) if p]
    if _project_root not in paths:
        paths.insert(0, _project_root)
    env["PYTHONPATH"] = os.pathsep.join(paths)

    try:
        # 启动引擎，后台运行（事件驱动模式）
        proc = subprocess.Popen(
            [python_exe, "-m", "bnos_runtime.engine", str(pipeline_path)],
            cwd=_project_root,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            text=True,
        )
        NodePage.engine_proc = proc
        print("引擎启动成功，PID:", proc.pid)

        # 后台线程读取引擎输出，防止管道阻塞
        NodePage._pipe_engine_output(proc)

    except Exception as e:
        print("引擎启动失败:", e)
        NodePage.engine_proc = None


def _stop_engine():
    """停止引擎进程"""
    proc = NodePage.engine_proc
    if proc is not None:
        try:
            print("正在停止引擎...")

            # 在 Windows 上使用 taskkill 杀死整个进程树
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                os.kill(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)

            print("引擎已停止")

        except Exception as e:
            print("停止引擎失败:", e)

        NodePage.engine_proc = None


def main():
    # 清理旧文件
    _cleanup_gui_adapter()

    # 启动引擎
    _start_engine()

    # 注册退出时清理引擎
    atexit.register(_stop_engine)

    # 启动 GUI
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    exit_code = app.exec()

    # 先停止引擎再退出
    _stop_engine()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
