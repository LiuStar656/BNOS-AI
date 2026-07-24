"""复合节点运行器 — 支持 inprocess（编排器）和 process 两种模式。"""

from __future__ import annotations

import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from bnos_runtime.pipeline_loader import NodeDef
from bnos_runtime.resource_limit import create_resource_limit
from bnos_runtime.venv_resolver import resolve_python


class CompositeRunner:
    """复合节点执行器。

    支持两种运行时模式：
    - inprocess: 自动生成的 orchestrator.py 在同一进程内串行执行所有子节点
    - process: 每个子节点作为独立进程并行启动
    """

    def __init__(self, node_id: str, node_def: NodeDef, project_root: Path):
        self.node_id = node_id
        self.defn = node_def
        self.project_root = project_root

    def run(self) -> "NodeResult":
        from bnos_runtime.engine import NodeResult

        mode = self.defn.runtime or "inprocess"
        if mode == "process":
            return self._run_process()
        return self._run_inprocess()

    def _run_inprocess(self) -> "NodeResult":
        """编排器模式：运行预生成的 orchestrator.py，所有子节点在同一进程。"""
        from bnos_runtime.engine import NodeResult

        node_path = self.project_root / self.defn.path
        python_exe = resolve_python(node_path)
        orchestrator = node_path / (self.defn.entry or "orchestrator.py")

        if not orchestrator.exists():
            return NodeResult(
                self.node_id, "composite", -2, "", f"orchestrator.py not found: {orchestrator}", 0, False,
            )

        limit = None
        if self.defn.resource_limit:
            limit = create_resource_limit(None, self.defn.resource_limit)

        t0 = time.perf_counter()
        try:
            proc = subprocess.Popen(
                [str(python_exe), str(orchestrator)],
                cwd=str(self.project_root),  # 项目根目录，确保 sys.path 可 import 子节点
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if limit:
                limit.assign_to_pid(proc.pid)

            stdout, stderr = proc.communicate(timeout=self.defn.timeout)
            duration_ms = (time.perf_counter() - t0) * 1000
            return NodeResult(
                self.node_id, "composite", proc.returncode, stdout, stderr, duration_ms,
                proc.returncode == 0,
            )
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            duration_ms = (time.perf_counter() - t0) * 1000
            return NodeResult(
                self.node_id, "composite", -1, stdout or "",
                f"Timeout after {self.defn.timeout}s\n{stderr or ''}", duration_ms, False,
            )

    def _run_process(self) -> "NodeResult":
        """独立进程模式：并行启动每个子节点为独立进程。"""
        from bnos_runtime.engine import NodeResult

        t0 = time.perf_counter()
        sub_results: list[NodeResult] = []

        with ThreadPoolExecutor(max_workers=len(self.defn.sub_nodes)) as pool:
            futures = {}
            for name, sn in self.defn.sub_nodes.items():
                node_path = self.project_root / sn["path"]
                python_exe = resolve_python(node_path)
                entry = sn.get("entry", "main.py")

                limit = None
                if sn.get("resource_limit"):
                    limit = create_resource_limit(None, sn["resource_limit"])

                def _do_run(*, py=python_exe, e=entry, np=node_path, l=limit, to=self.defn.timeout, nid=name):
                    p = subprocess.Popen(
                        [str(py), e], cwd=str(np),
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    )
                    if l:
                        l.assign_to_pid(p.pid)
                    out, err = p.communicate(timeout=to)
                    return NodeResult(nid, "standalone", p.returncode, out, err, 0, p.returncode == 0)

                futures[pool.submit(_do_run)] = name

            for future in as_completed(futures):
                result = future.result()
                sub_results.append(result)
                if not result.success:
                    break  # 快速失败

        duration_ms = (time.perf_counter() - t0) * 1000
        all_ok = all(r.success for r in sub_results)
        combined_stderr = "\n".join(f"[{r.node_id}] {r.stderr}" for r in sub_results if r.stderr)
        combined_stdout = "\n".join(f"[{r.node_id}] {r.stdout}" for r in sub_results if r.stdout)

        return NodeResult(
            self.node_id, "composite",
            0 if all_ok else 1,
            combined_stdout, combined_stderr, duration_ms, all_ok,
        )
