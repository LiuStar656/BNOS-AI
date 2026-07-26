"""BNOS 运行时执行引擎 — 零 GUI 依赖，支持独立节点 + 复合节点混合管线。"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from bnos_runtime.pipeline_loader import load_pipeline, PipelineDef
from bnos_runtime.standalone_runner import StandaloneRunner
from bnos_runtime.node_monitor import NodeMonitor


@dataclass
class NodeResult:
    """单个节点的执行结果。"""

    node_id: str
    node_type: str  # "standalone" | "composite"
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    success: bool


class ProcessManager:
    """子进程生命周期管理器 — 注册所有 node 子进程，退出时统一清理。"""

    def __init__(self):
        self._procs: dict[str, subprocess.Popen] = {}
        self._shutdown_requested = False

    def register(self, node_id: str, proc: subprocess.Popen) -> None:
        self._procs[node_id] = proc

    def request_shutdown(self) -> None:
        """请求优雅关闭（由信号处理器调用）。"""
        self._shutdown_requested = True

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    def shutdown(self) -> None:
        """杀死所有已注册的子进程。

        Windows 上用 taskkill /T 确保进程树全部清理，防止 listener 变成孤儿进程。
        """
        for node_id, proc in self._procs.items():
            try:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True, timeout=5,
                    )
                else:
                    proc.kill()
                    proc.wait(timeout=5)
            except Exception:
                pass
        self._procs.clear()


class PipelineRunner:
    """管线执行器 — 混合节点类型（standalone + composite）。

    BNOS 节点是事件驱动的，支持双向数据流（循环依赖）。
    所有节点一次性并行启动，通过共享文件自主通信。
    引擎启动后等待关闭信号（Ctrl+C / SIGTERM），收到后统一清理子进程。

    支持通过 bnos_cmd.json 命令文件手动控制节点重启。

    用法:
        runner = PipelineRunner("pipeline.json")
        results = runner.run()
    """

    MAX_RESTART_ATTEMPTS = 3

    def __init__(self, pipeline_path: Path):
        self.pipeline_path = Path(pipeline_path)
        self.project_root = self.pipeline_path.parent  # 项目根目录
        self.pipeline: PipelineDef = load_pipeline(pipeline_path)
        self.results: dict[str, NodeResult] = {}
        self.process_manager = ProcessManager()
        self._restart_counts: dict[str, int] = {}
        # 命令文件：GUI 通过此文件发送重启指令
        self._cmd_file = self.project_root / "bnos_cmd.json"
        self._cmd_file_mtime: float = 0.0

    def _p(self, *args, **kwargs):
        """带自动刷新的 print，确保日志输出到文件时实时可见。"""
        print(*args, **kwargs, flush=True)

    def run(self) -> dict[str, NodeResult]:
        """执行整个管线 — 启动所有节点后等待关闭信号。"""
        node_ids = list(self.pipeline.nodes.keys())

        self._p(f"[BNOS] Pipeline '{self.pipeline.name}'")
        self._p(f"[BNOS] {len(node_ids)} nodes (all standalone)")
        self._p("-" * 50)

        # 启动所有节点（非阻塞）
        for nid in node_ids:
            self._start_node(nid)
        self._p(f"\n[BNOS] All {len(node_ids)} nodes started. Waiting for shutdown signal (Ctrl+C)...")
        self._p("[BNOS] ==================================================")

        # 初始化 NodeMonitor（周期性健康检查）
        monitor = NodeMonitor(self.process_manager, self.project_root)

        # 等待关闭信号，同时周期性检查进程健康和处理命令文件
        try:
            while not self.process_manager.shutdown_requested:
                time.sleep(0.5)
                # 每 N 秒检查一次节点健康状态并输出到文件
                if monitor.should_check():
                    mon_status = monitor.check_and_report()
                    if mon_status.get("engine_status") == "offline":
                        self._p("[BNOS] All nodes have exited.")
                        self.process_manager.request_shutdown()
                    monitor.mark_checked()
                # 检查命令文件（GUI 通过此文件发送重启等指令）
                self._process_cmd_file()
        except KeyboardInterrupt:
            self._p("\n[BNOS] Interrupted by user.")
            self.process_manager.request_shutdown()

        # 最终状态报告
        monitor.check_and_report()

        # 统一清理子进程
        self.process_manager.shutdown()
        # 兜底：杀死任何残留的节点进程（覆盖非 listener 入口如 TTS main.py）
        _kill_orphan_node_processes(self.project_root)
        self._p("[BNOS] All child processes terminated.")
        return self.results

    def _start_node(self, node_id: str) -> None:
        """启动单个节点并注册到 ProcessManager。"""
        node_def = self.pipeline.nodes[node_id]
        if node_def.type == "composite":
            self._p(f"  [C] {node_id}: composite nodes not supported yet, skipped.")
            return

        runner = StandaloneRunner(node_id, node_def, self.project_root)
        try:
            nid, proc = runner.start()
            self.process_manager.register(nid, proc)

            # 记录启动结果
            import time as _time
            t0 = _time.time()
            self.results[nid] = NodeResult(
                node_id=nid,
                node_type="standalone",
                exit_code=0,
                stdout=f"started as PID {proc.pid}",
                stderr="",
                duration_ms=(t0 - t0) * 1000,  # 0 ms，仅记录启动
                success=True,
            )
            self._p(f"  [S] {nid}: PID {proc.pid}")
        except Exception as e:
            self._p(f"  [S] {node_id}: FAILED - {e}")
            import time as _time
            t0 = _time.time()
            self.results[node_id] = NodeResult(
                node_id=node_id,
                node_type="standalone",
                exit_code=-1,
                stdout="",
                stderr=str(e),
                duration_ms=0,
                success=False,
            )

    def _restart_node(self, node_id: str) -> None:
        """重启指定节点 — 供命令文件或 GUI 手动调用。"""
        old_proc = self.process_manager._procs.pop(node_id, None)
        if old_proc:
            try:
                # 如果进程已退出，跳过 kill（避免 taskkill 报错延迟）
                if old_proc.poll() is not None:
                    self._p(f"  [S] {node_id}: process already exited, skipping kill.")
                elif os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(old_proc.pid)],
                        capture_output=True, timeout=5,
                    )
                else:
                    old_proc.kill()
                    old_proc.wait(timeout=5)
            except Exception:
                pass
        self._p(f"  [S] {node_id}: restarting...")
        self._start_node(node_id)

    def _process_cmd_file(self) -> None:
        """检查并处理命令文件（bnos_cmd.json）。

        命令格式: {"cmd": "restart", "node_id": "node_python_xxx"}
        执行后删除命令文件。
        """
        try:
            if not self._cmd_file.exists():
                self._cmd_file_mtime = 0.0
                return

            current_mtime = self._cmd_file.stat().st_mtime
            if current_mtime <= self._cmd_file_mtime:
                return

            with open(self._cmd_file, "r", encoding="utf-8") as f:
                cmd_data = json.load(f)

            cmd = cmd_data.get("cmd", "")
            if cmd == "restart":
                node_id = cmd_data.get("node_id", "")
                if node_id in self.pipeline.nodes:
                    self._restart_node(node_id)
                else:
                    self._p(f"[BNOS] Unknown node for restart: {node_id}")

            # 处理完毕，删除命令文件
            self._cmd_file.unlink(missing_ok=True)
            self._cmd_file_mtime = 0.0

        except (json.JSONDecodeError, OSError) as e:
            self._p(f"[BNOS] Cmd file error: {e}")
            self._cmd_file.unlink(missing_ok=True)
            self._cmd_file_mtime = 0.0


def _kill_orphan_node_processes(project_root: Path) -> None:
    """用 PowerShell 杀死项目中所有残留的 Python 节点进程（兜底清理）。

    不依赖 'listener' 关键词匹配，直接扫描命令行中的节点名。
    能覆盖 TTS 的 main.py、llama-server 子进程等遗漏场景。
    可在引擎启动前（清理旧进程）和 shutdown 后（兜底扫尾）调用。
    """
    if os.name != "nt":
        return
    nodes_dir = project_root / "nodes"
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
    import subprocess
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd],
                       capture_output=True, timeout=15)
    except Exception:
        pass


def main():
    """CLI 入口: python -m bnos_runtime.engine pipeline.json"""
    if len(sys.argv) < 2:
        print("Usage: python -m bnos_runtime.engine <pipeline.json>")
        sys.exit(1)

    pipeline_path = Path(sys.argv[1])
    if not pipeline_path.exists():
        print(f"[ERROR] Pipeline file not found: {pipeline_path}")
        sys.exit(1)

    # 启动前杀死所有残留的节点进程（防止重复处理）
    _kill_orphan_node_processes(pipeline_path.parent)
    print("[BNOS] Orphan node processes cleaned up.")

    runner = PipelineRunner(pipeline_path)

    # 注册信号处理器：优雅关闭所有子进程
    def _signal_handler(sig, frame):
        print(f"\n[BNOS] Signal {sig} received, shutting down...")
        runner.process_manager.request_shutdown()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    results = runner.run()

    failed = [n for n, r in results.items() if not r.success]
    if failed:
        print(f"[BNOS] Pipeline finished with {len(failed)} failed node(s): {failed}")
        sys.exit(1)


if __name__ == "__main__":
    main()
