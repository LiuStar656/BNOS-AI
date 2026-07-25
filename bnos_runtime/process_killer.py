"""进程终止工具 — 终止运行中节点的进程树，无 GUI 依赖。

从 GUI 版 `ui/core/node/node_process.py` 和 `ui/main_window/lifecycle.py`
的关闭所有节点进程逻辑中提取，适配运行时环境使用。

用法:
    from bnos_runtime.process_killer import stop_node_process, stop_all_node_processes

    # 停止单个节点
    stop_node_process(Path("/project/nodes/my_node"))

    # 停止项目中所有节点
    stop_all_node_processes(Path("/project"))
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from bnos_runtime.logger import logger


# ══════════════════════════════════════════════
# PID 文件工具
# ══════════════════════════════════════════════


def _pid_file(node_path: Path) -> Path:
    """标准 PID 文件路径 (.pid)"""
    return node_path / ".pid"


def _named_pid_file(node_path: Path) -> Path:
    """命名 PID 文件路径 (<目录名>.pid)"""
    return node_path / f"{node_path.name}.pid"


def _get_pid_file(node_path: Path) -> Path | None:
    """获取实际存在的 PID 文件路径（优先命名格式）"""
    named = _named_pid_file(node_path)
    if named.exists():
        return named
    std = _pid_file(node_path)
    if std.exists():
        return std
    return None


def _read_pid(node_path: Path) -> int | None:
    """读取 PID 文件，返回 PID 或 None"""
    pf = _get_pid_file(node_path)
    if pf is None:
        return None
    try:
        content = pf.read_text(encoding="utf-8").strip()
        return int(content) if content else None
    except (OSError, ValueError):
        return None


def _delete_pid(node_path: Path) -> None:
    """删除所有 PID 文件（标准格式 + 命名格式）"""
    try:
        pf = _pid_file(node_path)
        if pf.exists():
            pf.unlink()
        npf = _named_pid_file(node_path)
        if npf.exists():
            npf.unlink()
    except OSError:
        pass


# ══════════════════════════════════════════════
# 进程树查询与终止
# ══════════════════════════════════════════════


def _kill_process_tree(root_pid: int) -> bool:
    """终止整棵进程树。

    Windows:  taskkill /F /T /PID  ← 内核递归杀所有后代
    Linux:    killpg(sig=SIGKILL)  ← 杀进程组

    Returns:
        True 表示至少成功终止了一个进程（或进程已不存在）。
    """
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(root_pid)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode == 0:
                logger.info("已终止进程树 PID=%d", root_pid)
                return True
            logger.warning(
                "终止进程树 PID=%d 失败 (exit=%d)",
                root_pid, result.returncode,
            )
            return False
        else:
            os.killpg(os.getpgid(root_pid), signal.SIGKILL)
            logger.info("已终止进程组 PGID=%d", root_pid)
            return True
    except (ProcessLookupError, OSError):
        logger.debug("进程 PID=%d 已不存在", root_pid)
        return True  # 已死 = 成功
    except Exception as e:
        logger.warning("终止进程树 PID=%d 异常: %s", root_pid, e)
        return False


def _find_node_processes_by_path(node_path: Path) -> list[int]:
    """扫描系统中占用节点文件夹的进程（按 cwd 和打开文件匹配）。

    这是 PID 文件丢失时的兜底扫描方式。

    Returns:
        PID 列表。
    """
    import psutil

    pids: list[int] = []
    node_path_lower = str(node_path).lower().replace("/", "\\")

    for proc in psutil.process_iter(["pid", "name", "cwd"]):
        try:
            try:
                cwd = proc.cwd()
                if cwd and node_path_lower in cwd.lower().replace("/", "\\"):
                    pids.append(proc.pid)
                    continue
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
            try:
                for f in proc.open_files():
                    if f.path and node_path_lower in f.path.lower().replace("/", "\\"):
                        pids.append(proc.pid)
                        break
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

    return pids


def _kill_all_by_path(node_path: Path) -> int:
    """强制终止所有占用节点文件夹的进程（兜底方案）。

    Returns:
        成功终止的进程数量。
    """
    pids = _find_node_processes_by_path(node_path)
    killed = 0
    for pid in pids:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                os.kill(pid, signal.SIGKILL)
            killed += 1
            logger.info("已清理孤儿进程 PID=%d (节点: %s)", pid, node_path.name)
        except Exception as e:
            logger.warning("清理孤儿进程 PID=%d 失败: %s", pid, e)
    if killed:
        logger.info("共清理 %d 个孤儿进程 (节点: %s)", killed, node_path.name)
    return killed


# ══════════════════════════════════════════════
# 公开 API
# ══════════════════════════════════════════════


def stop_node_process(node_path: str | Path) -> bool:
    """停止指定节点的所有进程。

    流程：
    1. 读取 PID 文件获取主进程 PID
    2. 用 taskkill /T 或 killpg 终止进程树
    3. 兜底：按路径扫描清理残留进程
    4. 删除 PID 文件

    Args:
        node_path: 节点目录的绝对路径。

    Returns:
        True 表示节点进程已被终止（或已不存在）。
    """
    node_path = Path(node_path)
    node_name = node_path.name

    # 1. 读取 PID 文件
    pid = _read_pid(node_path)
    killed = False

    if pid is not None:
        killed = _kill_process_tree(pid)
        if killed:
            logger.info("进程树已终止 PID=%d (%s)", pid, node_name)
        else:
            logger.warning("进程树终止失败 PID=%d (%s)，尝试兜底扫描", pid, node_name)

    # 2. 兜底：按路径扫描清理
    if not killed:
        _kill_all_by_path(node_path)

    # 3. 二次确认
    time.sleep(0.3)
    remaining = _find_node_processes_by_path(node_path)
    if remaining:
        logger.warning("节点 %s 仍有 %d 个残留进程: %s", node_name, len(remaining), remaining)
    else:
        logger.info("节点 %s 已确认停止", node_name)

    # 4. 清理 PID 文件
    _delete_pid(node_path)

    return len(remaining) == 0


def stop_all_node_processes(project_root: str | Path) -> list[str]:
    """停止项目中所有运行中的节点进程。

    遍历 project_root 下的 nodes/ 目录，对每个含有 PID 文件的节点
    调用 stop_node_process() 进行清理。

    Args:
        project_root: BNOS 项目根目录。

    Returns:
        被停止操作的节点名列表。
    """
    project_root = Path(project_root)
    nodes_dir = project_root / "nodes"
    if not nodes_dir.is_dir():
        logger.warning("项目中不存在 nodes/ 目录: %s", nodes_dir)
        return []

    stopped: list[str] = []

    for node_dir in sorted(nodes_dir.iterdir()):
        if not node_dir.is_dir():
            continue
        if node_dir.name.startswith("__"):
            continue
        if _get_pid_file(node_dir) is None:
            continue

        logger.info("正在停止节点: %s", node_dir.name)
        stop_node_process(node_dir)
        stopped.append(node_dir.name)

    # 也扫描复合节点目录
    composite_dir = project_root / "composite_nodes"
    if composite_dir.is_dir():
        for comp_dir in sorted(composite_dir.iterdir()):
            if not comp_dir.is_dir():
                continue
            if _get_pid_file(comp_dir) is None:
                continue
            logger.info("正在停止复合节点: %s", comp_dir.name)
            stop_node_process(comp_dir)
            stopped.append(comp_dir.name)

    if stopped:
        logger.info("共停止了 %d 个节点的进程: %s", len(stopped), stopped)
    else:
        logger.info("没有运行中的节点需要停止")

    return stopped
