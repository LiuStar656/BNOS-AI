"""资源限制封装 — 运行时引擎适配层。

复用 ui.core.system.resource_limit 的底层实现，提供进程 PID 级别的资源限制能力。
"""

from __future__ import annotations

import platform
from typing import Any

_SYSTEM = platform.system()

# 尝试导入 psutil，若不可用则降级
try:
    import psutil  # noqa: F401
except ImportError:
    psutil = None  # type: ignore[assignment]


def create_resource_limit(pid: int | None, config: dict[str, Any]) -> _ResourceLimit | None:
    """根据配置创建资源限制器。

    当 psutil 不可用或 config 为空时返回 None。

    Args:
        pid: 目标进程 ID。若为 None，延迟到 assign_to_pid 时设置。
        config: 资源配置字典，支持:
            - memory_mb: int
            - cpu_percent: int
            - priority: str

    Returns:
        _ResourceLimit 实例或 None。
    """
    if psutil is None or not config:
        return None
    if not any(k in config for k in ("memory_mb", "cpu_percent", "priority")):
        return None
    return _ResourceLimit(pid, config)


class _ResourceLimit:
    """轻量资源限制封装。"""

    def __init__(self, pid: int | None, config: dict[str, Any]) -> None:
        self._pid = pid
        self._config = config
        self._applied: list[str] = []

    def assign_to_pid(self, pid: int) -> None:
        """设置（或更新）目标 PID 并应用限制。"""
        self._pid = pid
        self.apply()

    def apply(self) -> list[str]:
        """应用资源限制。

        Returns:
            实际生效的限制列表。
        """
        if self._pid is None:
            return []

        try:
            from ui.core.system.resource_limit import create_resource_limit as _create_limit  # type: ignore[import-untyped]

            limiter = _create_limit(self._pid, self._config)
            if limiter:
                self._applied = limiter.apply()
        except ImportError:
            pass
        except Exception:
            pass
        return self._applied
