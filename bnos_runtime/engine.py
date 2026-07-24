"""BNOS 运行时执行引擎 — 零 GUI 依赖，支持独立节点 + 复合节点混合管线。"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from bnos_runtime.pipeline_loader import load_pipeline, PipelineDef
from bnos_runtime.standalone_runner import StandaloneRunner


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
        """杀死所有已注册的子进程。"""
        for node_id, proc in self._procs.items():
            try:
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

    用法:
        runner = PipelineRunner("pipeline.json")
        results = runner.run()
    """

    def __init__(self, pipeline_path: Path):
        self.pipeline_path = Path(pipeline_path)
        self.project_root = self.pipeline_path.parent  # 项目根目录
        self.pipeline: PipelineDef = load_pipeline(pipeline_path)
        self.results: dict[str, NodeResult] = {}
        self.process_manager = ProcessManager()

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

        # 等待关闭信号（每 500ms 检查一次）
        try:
            while not self.process_manager.shutdown_requested:
                time.sleep(0.5)
        except KeyboardInterrupt:
            self._p("\n[BNOS] Interrupted by user.")
            self.process_manager.request_shutdown()

        # 统一清理子进程
        self.process_manager.shutdown()
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
            self._p(f"  [S] {nid}: PID {proc.pid}")
        except Exception as e:
            self._p(f"  [S] {node_id}: FAILED - {e}")


def _kill_orphan_listeners(project_root: Path) -> None:
    """用 PowerShell 杀死项目中所有残留的 listener 进程（兜底清理）。"""
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
        "$_.Name -like '*python*' -and $_.CommandLine -match 'listener' -and ({0}) "
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

    # 启动前杀死所有残留的 listener 进程（防止重复处理）
    _kill_orphan_listeners(pipeline_path.parent)
    print("[BNOS] Orphan listeners cleaned up.")

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
