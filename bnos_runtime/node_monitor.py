"""节点状态监控器 — 周期性检查子进程健康状态，输出统一状态文件。

职责：
  - 周期性检查 ProcessManager 中所有子进程是否存活
  - 检测进程崩溃（exit_code != 0），更新引擎状态为 degraded
  - 将状态输出到项目根目录的 bnos_status.json
  - 为 GUI 和外部工具提供统一的节点状态查询接口

用法（由 engine.py 集成，不直接调用）:
    monitor = NodeMonitor(process_manager, project_root)
    status = monitor.check_and_report()
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


class NodeMonitor:
    """节点状态监控器 — 周期性检查子进程健康状态。

    Args:
        process_manager: ProcessManager 实例，通过其 _procs 属性获取子进程列表。
        project_root: 项目根目录，用于定位状态文件输出位置。
        status_file: 状态文件名（相对 project_root 或绝对路径）。
        check_interval: 健康检查间隔（秒）。
    """

    CHECK_INTERVAL = 5  # 默认检查间隔（秒）

    def __init__(
        self,
        process_manager,
        project_root: Path,
        status_file: str = "bnos_status.json",
        check_interval: int = CHECK_INTERVAL,
    ):
        self._pm = process_manager
        self._project_root = Path(project_root)
        self._status_path = self._project_root / status_file
        self._check_interval = check_interval
        self._last_status: dict = {}
        self._last_check_time: float = 0

    @property
    def last_status(self) -> dict:
        """最近一次健康检查的结果快照。"""
        return dict(self._last_status)

    def check_and_report(self) -> dict:
        """检查所有进程状态并输出到状态文件。

        每次调用会：
        1. 轮询 `ProcessManager._procs` 中所有进程的 `poll()`
        2. 判断状态：running / crashed / stopped
        3. 更新引擎整体状态：online / degraded
        4. 写入 `bnos_status.json`

        Returns:
            {
                "updated_at": "2026-07-24T15:30:00",
                "engine_status": "online" | "degraded" | "offline",
                "nodes": {
                    "node_python_xxx": {
                        "status": "running" | "crashed" | "stopped",
                        "pid": 12345
                    },
                    ...
                }
            }
        """
        all_procs = {}
        try:
            all_procs = dict(self._pm._procs)
        except AttributeError:
            pass

        status: dict = {
            "updated_at": self._iso_now(),
            "engine_status": "online",
            "nodes": {},
        }

        has_crashed = False
        for node_id, proc in all_procs.items():
            poll = proc.poll()
            if poll is None:
                # 进程仍在运行
                status["nodes"][node_id] = {
                    "status": "running",
                    "pid": proc.pid,
                }
            else:
                # 进程已退出
                node_status = "crashed" if poll != 0 else "stopped"
                status["nodes"][node_id] = {
                    "status": node_status,
                    "pid": proc.pid,
                    "exit_code": poll,
                }
                if poll != 0:
                    has_crashed = True

        if has_crashed:
            status["engine_status"] = "degraded"

        # 如果没有任何节点在运行，标记为 offline
        running_count = sum(
            1 for n in status["nodes"].values() if n.get("status") == "running"
        )
        if running_count == 0:
            status["engine_status"] = "offline"

        self._last_status = status

        # 写入状态文件
        self._write_status(status)

        return status

    def should_check(self) -> bool:
        """是否到了应该检查的时刻（基于时间间隔）。"""
        return (time.time() - self._last_check_time) >= self._check_interval

    def mark_checked(self):
        """标记本次检查完成。"""
        self._last_check_time = time.time()

    # ── 内部方法 ──────────────────────────────────

    def _write_status(self, status: dict) -> None:
        """将状态 dict 安全写入 JSON 文件。"""
        try:
            d = self._status_path.parent
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
            tmp = self._status_path.with_suffix(self._status_path.suffix + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(status, f, indent=2, ensure_ascii=False)
            if self._status_path.exists():
                self._status_path.unlink(missing_ok=True)
            tmp.rename(self._status_path)
        except OSError:
            pass

    @staticmethod
    def _iso_now() -> str:
        """返回 ISO 格式时间戳。"""
        return time.strftime("%Y-%m-%dT%H:%M:%S")


# ── 快捷函数 ─────────────────────────────────────


def read_status(project_root: Path, status_file: str = "bnos_status.json") -> dict:
    """从项目根目录读取最近的节点状态。

    供 GUI 或外部工具调用，无需导入 engine 模块。

    Args:
        project_root: 项目根目录。
        status_file: 状态文件名。

    Returns:
        状态字典，文件不存在时返回空状态。
    """
    path = Path(project_root) / status_file
    if not path.exists():
        return {
            "updated_at": "",
            "engine_status": "unknown",
            "nodes": {},
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {
            "updated_at": "",
            "engine_status": "unknown",
            "nodes": {},
        }
