"""独立节点运行器 — 单进程子进程执行，依赖 pipeline.json 的 venv 字段。"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from bnos_runtime.pipeline_loader import NodeDef
from bnos_runtime.resource_limit import create_resource_limit
from bnos_runtime.venv_resolver import resolve_python


class StandaloneRunner:
    """独立节点执行器。

    数据流说明：
    - 节点间的数据路由已由 GUI 写入各节点的 node_config.json
      （listen_upper_file / port_mappings）
    - 引擎的职责是按拓扑顺序执行节点，确保上游输出文件存在后再启动下游
    - 不需要在运行时修改 node_config.json 或写额外的路由配置
    """

    def __init__(self, node_id: str, node_def: NodeDef, project_root: Path):
        self.node_id = node_id
        self.defn = node_def
        self.project_root = project_root

    @staticmethod
    def _kill_existing_instance(node_path: Path) -> None:
        """根据 PID 文件杀掉该节点的旧进程，防止残留实例导致重复处理。"""
        pid_file = node_path / f"{node_path.name}.pid"
        if pid_file.exists():
            try:
                old_pid = int(pid_file.read_text().strip())
                try:
                    if os.name == "nt":
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(old_pid)],
                            capture_output=True, timeout=5,
                        )
                    else:
                        os.kill(old_pid, 9)
                except Exception:
                    pass  # 进程已不存在则忽略
                pid_file.unlink(missing_ok=True)
            except (ValueError, OSError):
                pid_file.unlink(missing_ok=True)

    def run(self) -> "NodeResult":
        """（旧接口）启动节点并等待完成 — 用于短任务节点。"""
        from bnos_runtime.engine import NodeResult

        node_path = self.project_root / self.defn.path
        self._kill_existing_instance(node_path)

        if self.defn.exe_entry:
            exe_path = node_path / self.defn.exe_entry
            if exe_path.exists():
                return self._run_exe(exe_path, node_path)

        python_exe, entry = self._resolve_entry()
        entry_path = node_path / entry
        if not entry_path.exists():
            return NodeResult(
                node_id=self.node_id, node_type="standalone",
                exit_code=-2, stdout="",
                stderr=f"Entry file not found: {entry_path}",
                duration_ms=0, success=False,
            )

        limit = None
        if self.defn.resource_limit:
            limit = create_resource_limit(None, self.defn.resource_limit)

        t0 = time.perf_counter()
        try:
            proc = subprocess.Popen(
                [str(python_exe), entry],
                cwd=str(node_path),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
                env={**os.environ, "BNOS_RUNTIME": "1"},
            )
            if limit:
                limit.assign_to_pid(proc.pid)
            stdout, stderr = proc.communicate(timeout=self.defn.timeout)
            duration_ms = (time.perf_counter() - t0) * 1000
            return NodeResult(
                node_id=self.node_id, node_type="standalone",
                exit_code=proc.returncode, stdout=stdout, stderr=stderr,
                duration_ms=duration_ms, success=proc.returncode == 0,
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            duration_ms = (time.perf_counter() - t0) * 1000
            return NodeResult(
                node_id=self.node_id, node_type="standalone",
                exit_code=-1, stdout=stdout or "",
                stderr=f"Timeout after {self.defn.timeout}s\n{stderr or ''}",
                duration_ms=duration_ms, success=False,
            )

    def start(self) -> tuple[str, subprocess.Popen]:
        """（新接口）非阻塞启动节点进程，立即返回 (node_id, proc)。

        适用于长时间运行的 event-loop 节点（listener.py / listener.js）。
        支持 Python (.py) 和 JavaScript (.js) 两种入口。
        调用方负责调用 proc.kill() / proc.terminate()。
        """
        node_path = self.project_root / self.defn.path
        self._kill_existing_instance(node_path)

        # 优先尝试 exe_entry
        if self.defn.exe_entry:
            exe_path = node_path / self.defn.exe_entry
            if exe_path.exists():
                proc = subprocess.Popen(
                    [str(exe_path)],
                    cwd=str(node_path),
                    stdout=None, stderr=None,
                    env={**os.environ, "BNOS_RUNTIME": "1"},
                )
                return self.node_id, proc

        # 解析入口文件
        entry = self.defn.entry or "main.py"
        entry_lower = entry.lower()

        if entry_lower.endswith(".js"):
            # JavaScript 节点：使用 node 执行
            proc = subprocess.Popen(
                ["node", entry],
                cwd=str(node_path),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env={**os.environ, "BNOS_RUNTIME": "1", "PYTHONIOENCODING": "utf-8"},
            )
        else:
            # Python 节点：使用解析到的 Python 解释器
            python_exe = self._resolve_python()
            proc = subprocess.Popen(
                [str(python_exe), entry],
                cwd=str(node_path),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env={**os.environ, "BNOS_RUNTIME": "1", "PYTHONIOENCODING": "utf-8"},
            )
        return self.node_id, proc

    def _resolve_python(self) -> Path:
        """仅解析 Python 解释器路径（不返回入口）。"""
        node_path = self.project_root / self.defn.path
        if self.defn.venv:
            return self._resolve_from_venv_path(self.defn.venv)
        return resolve_python(node_path)

    def _resolve_entry(self) -> tuple[Path, str]:
        """解析 Python 解释器和入口文件。"""
        python_exe = self._resolve_python()
        entry = self.defn.entry or "main.py"
        return python_exe, entry

    def _run_exe(self, exe_path: Path, node_path: Path) -> "NodeResult":
        """直接运行编译好的 exe，跳过 Python/venv 依赖。"""
        from bnos_runtime.engine import NodeResult

        t0 = time.perf_counter()
        try:
            proc = subprocess.Popen(
                [str(exe_path)],
                cwd=str(node_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={**os.environ, "BNOS_RUNTIME": "1"},
            )
            stdout, stderr = proc.communicate(timeout=self.defn.timeout)
            duration_ms = (time.perf_counter() - t0) * 1000
            return NodeResult(
                node_id=self.node_id, node_type="standalone",
                exit_code=proc.returncode, stdout=stdout, stderr=stderr,
                duration_ms=duration_ms, success=proc.returncode == 0,
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            duration_ms = (time.perf_counter() - t0) * 1000
            return NodeResult(
                node_id=self.node_id, node_type="standalone",
                exit_code=-1, stdout=stdout or "",
                stderr=f"Timeout after {self.defn.timeout}s\n{stderr or ''}",
                duration_ms=duration_ms, success=False,
            )

    def _resolve_from_venv_path(self, venv_rel: str) -> Path:
        """从 pipeline.json 的 venv 字段解析 Python 解释器。"""
        is_win = os.name == "nt"
        venv_dir = self.project_root / venv_rel
        if is_win:
            python = venv_dir / "Scripts" / "python.exe"
        else:
            python = venv_dir / "bin" / "python3"
        if python.exists():
            return python
        # Fallback
        return resolve_python(self.project_root / self.defn.path)
