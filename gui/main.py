"""BNOS AI 伴侣 — GUI 入口

数据流：GUI -> gui_input.json -> aaa_cognition (中枢, 合并了旧 gui_adapter+user_input)
                                     <- gui_reply.json <-

启动流程：
1. 清理旧的输出文件
2. 启动 QApplication + 闪屏
3. 后台启动引擎（拉起所有节点）
4. 闪屏轮询 bnos_status.json 直至所有节点就绪（超时 60s）
5. 创建主窗口
6. GUI 关闭时自动清理引擎
"""

from __future__ import annotations

import atexit
import os
import signal
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

# 将项目根目录加入 sys.path，确保 from gui.xxx 导入可用
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from gui.main_window import MainWindow
from gui.pages.startup_splash import StartupSplash


def _cleanup_gui_adapter():
    """启动时清理 gui_reply.json，避免残留数据干扰"""
    reply_path = Path(_project_root) / "nodes" / "shared" / "gui_reply.json"
    if reply_path.exists():
        try:
            reply_path.unlink()
        except OSError:
            pass


def _start_engine(log_dir: Path | None = None):
    """启动引擎进程（--serve 事件驱动模式）"""
    pipeline_path = Path(_project_root) / "pipeline.json"

    python_exe = sys.executable

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONPATH", "")
    paths = [p for p in env["PYTHONPATH"].split(os.pathsep) if p]
    if _project_root not in paths:
        paths.insert(0, _project_root)
    env["PYTHONPATH"] = os.pathsep.join(paths)

    from gui.pages.node_page import NodePage

    # 构建命令行参数
    cmd = [python_exe, "-m", "bnos_runtime.engine", str(pipeline_path), "--serve"]
    if log_dir:
        cmd.extend(["--log-dir", str(log_dir)])

    try:
        proc = subprocess.Popen(
            cmd,
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
        NodePage._pipe_engine_output(proc, log_dir=log_dir)

    except Exception as e:
        print("引擎启动失败:", e)
        NodePage.engine_proc = None


def _sweep_orphan_processes(project_root: str) -> None:
    """兜底扫尾：杀死任何与 BNOS 节点相关的 Python 残留进程。

    不依赖 PID 文件或 'listener' 关键字匹配，直接用 PowerShell 扫描
    命令行中包含节点名的所有 Python 进程并强制终止。
    覆盖 TTS 的 main.py、llama-server 子进程等遗漏场景。
    """
    if os.name != "nt":
        return
    nodes_dir = Path(project_root) / "nodes"
    if not nodes_dir.exists():
        return
    node_names = [d.name for d in nodes_dir.iterdir() if d.is_dir() and d.name.startswith("node_")]
    if not node_names:
        return

    # 构建 PowerShell 匹配条件：节点名 1 -or 节点名 2 ...
    name_conditions = " -or ".join(f"($_.CommandLine -match '{n}')" for n in node_names)
    ps_cmd = (
        "Get-CimInstance Win32_Process | Where-Object {{ "
        "$_.Name -like '*python*' -and ({0}) "
        "}} | ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force }}"
    ).format(name_conditions)
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode == 0:
            print("  兜底扫尾完成（已清理残留 Python 进程）")
        else:
            print(f"  兜底扫尾: PowerShell 返回 {result.returncode}")
    except Exception as e:
        print(f"  兜底扫尾异常: {e}")


def _stop_engine():
    """停止引擎进程"""
    try:
        print("正在停止引擎...")

        # 第 1 层：按节点目录清理（PID 文件 + 路径扫描）
        try:
            from bnos_runtime.process_killer import stop_all_node_processes
            stopped = stop_all_node_processes(_project_root)
            if stopped:
                print("  process_killer 已清理节点:", ", ".join(stopped))
        except Exception as e:
            print("  process_killer 清理失败:", e)

        # 第 2 层：杀死引擎进程及其子进程树
        from gui.pages.node_page import NodePage
        proc = NodePage.engine_proc
        if proc is not None and proc.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                os.kill(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)

        # 第 2.5 层：引擎引用丢失时的兜底 — 按命令行匹配 bnos_runtime 进程
        if os.name == "nt":
            ps_cmd = (
                'Get-CimInstance Win32_Process | '
                'Where-Object { '
                "$_.Name -like '*python*' -and "
                "$_.CommandLine -match 'bnos_runtime' "
                "} | Select-Object -ExpandProperty ProcessId"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            for line in result.stdout.splitlines():
                pid = line.strip()
                if pid.isdigit():
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", pid],
                            capture_output=True, timeout=5,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                        print(f"  已终止引擎进程 PID={pid}")
                    except Exception:
                        pass

        # 第 3 层：兜底扫尾 — 杀死任何残留的 Python 节点进程
        # 解决 PID 文件丢失、非 listener 入口进程等遗漏问题
        _sweep_orphan_processes(_project_root)

        print("引擎已停止")

    except Exception as e:
        print("停止引擎失败:", e)

    from gui.pages.node_page import NodePage
    NodePage.engine_proc = None


def main():
    _cleanup_gui_adapter()

    # 初始化 GUI 日志系统（按启动批次隔离）
    from gui.core.logger import setup_gui_logger, get_logger
    _batch_dir = setup_gui_logger()
    _log = get_logger("main")
    _log.info("BNOS AI 启动 — 批次目录: %s", _batch_dir)

    # 必须先创建 QApplication 才能使用 QWidget
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 闪屏
    splash = StartupSplash(_project_root)

    # 启动引擎（非阻塞），传递批次日志目录
    _engine_log_dir = _batch_dir / "engine"
    _start_engine(log_dir=_engine_log_dir)
    atexit.register(_stop_engine)

    # 预设窗口：主窗口创建后再注册退出清理
    main_window_ref = [None]

    def on_nodes_ready():
        """所有节点就绪（或超时）→ 创建主窗口"""
        if main_window_ref[0] is not None:
            return
        splash.close()
        window = MainWindow()
        main_window_ref[0] = window
        window.show()

        # v1.3: 启动 GUI 层 Qt 定位提供者
        try:
            from gui.core.location_provider import QtLocationProvider
            from gui.core.config import AppConfig
            db_path = str(Path(_project_root) / "nodes" / "shared" / "chatbot.db")
            loc_cfg = AppConfig().get("location", {})
            identity_key = "gui:default"
            provider = QtLocationProvider(db_path, identity_key, parent=window)
            window._location_provider = provider
            loc_enabled = True
            if isinstance(loc_cfg, dict):
                loc_enabled = loc_cfg.get("enabled", True)
            if loc_enabled:
                provider.start()
        except Exception as e:
            print(f"[QtLocation] 启动失败（不影响主流程）: {e}")

    splash.nodes_ready.connect(on_nodes_ready)

    # 开始闪屏轮询
    splash.start_waiting()

    exit_code = app.exec()

    # 窗口关闭后停止引擎
    _stop_engine()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
