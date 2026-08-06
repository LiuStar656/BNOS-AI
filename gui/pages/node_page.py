"""节点管理页 — 适配 bnos_runtime，通过 bnos_status.json 读取引擎/节点状态"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.core.state import AppState

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BNOS_STATUS_PATH = str(PROJECT_ROOT / "bnos_status.json")
BNOS_CMD_PATH = str(PROJECT_ROOT / "bnos_cmd.json")
PIPELINE_PATH = str(PROJECT_ROOT / "pipeline.json")

# 状态文件超过此秒数未更新，认为引擎已失联
STALE_THRESHOLD = 15


class NodePage(QWidget):
    """节点管理仪表盘 — 适配 bnos_runtime。

    数据来源：
      - 引擎状态 / 节点状态 → 从 AppState 监听（message_manager 每 200ms 轮询 bnos_status.json）
      - 兜底检测 → 每 2s 检查状态文件新鲜度，进程是否存活
      - 重启命令 → 写入 bnos_cmd.json（引擎负责读取执行）
      - 启停引擎 → subprocess 管理 bnos_runtime.engine 进程
    """

    # 共享引擎进程引用（允许多处代码安全操作同一引擎进程）
    engine_proc: subprocess.Popen | None = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = AppState()
        self._cached_nodes: dict = {}  # 缓存上一次节点数据，避免频繁重建

        self._build_ui()

        # 监听 AppState 变化
        self._state.on_change("engine_status", self._on_status_changed)
        self._state.on_change("nodes", self._on_nodes_changed)

        # 兜底定时器：检测状态文件新鲜度 + 引擎进程存活
        self._stale_timer = QTimer(self)
        self._stale_timer.timeout.connect(self._check_stale)
        # 初始不启动，由 MainWindow 在打开面板时启动

        # 初始同步 UI
        self._sync_ui()

    # ── UI 构建 ────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 引擎状态栏
        bar = QHBoxLayout()
        self._status_label = QLabel("引擎状态: --")
        self._status_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self._start_btn = QPushButton("▶ 启动引擎")
        self._stop_btn = QPushButton("■ 停止引擎")
        self._start_btn.setMinimumWidth(110)
        self._stop_btn.setMinimumWidth(110)
        self._start_btn.clicked.connect(self._start_engine)
        self._stop_btn.clicked.connect(self._stop_engine)
        self._stop_btn.setEnabled(False)
        bar.addWidget(self._status_label)
        bar.addStretch()
        bar.addWidget(self._start_btn)
        bar.addWidget(self._stop_btn)
        layout.addLayout(bar)

        # 分隔线
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #d0d0d0;")
        layout.addWidget(sep)

        # 节点树
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["节点", "状态", "详情", "操作"])
        self._tree.setAlternatingRowColors(True)
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self._tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._tree.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self._tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self._tree)

        # 离线占位文案
        self._placeholder = QLabel("引擎未启动，请点击「启动引擎」启动 BNOS 运行时")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #999; font-size: 16px; padding: 40px;")
        layout.addWidget(self._placeholder)

    # ── AppState 回调 ──────────────────────────────

    def _on_status_changed(self, value: str):
        self._sync_ui()

    def _on_nodes_changed(self, value: dict):
        if self._state.engine_status == "online":
            # 只有数据真正变化时才重建树，防止 200ms 轮询导致闪烁
            if json.dumps(value, sort_keys=True, default=str) != json.dumps(self._cached_nodes, sort_keys=True, default=str):
                self._cached_nodes = dict(value)
                self._render_tree(value)

    # ── 新鲜度兜底检测 ─────────────────────────────

    def _check_stale(self):
        """检查 bnos_status.json 是否过时 + 引擎进程是否意外死亡。"""
        # 若引擎标记为 online 但文件太久没更新 → 怀疑已死
        if self._state.engine_status != "online":
            return
        try:
            mtime = os.path.getmtime(BNOS_STATUS_PATH)
        except OSError:
            return
        age = time.time() - mtime
        if age < STALE_THRESHOLD:
            return  # 文件仍在更新，引擎正常

        # 文件太久未更新 → 检查引擎进程是否还在
        proc = self.__class__.engine_proc
        if proc is not None and proc.poll() is not None:
            # 进程已退出，标记 offline
            print(f"[NodePage] 引擎进程已退出 (exit_code={proc.poll()})，标记为 offline")
            self._state.engine_status = "offline"
            self.__class__.engine_proc = None
        elif proc is None:
            # 没有进程引用但状态文件却长时间未更新
            self._state.engine_status = "offline"

    # ── UI 同步 ────────────────────────────────────

    def _sync_ui(self):
        """根据 AppState.engine_status 切换 UI。"""
        status = self._state.engine_status
        if status == "online":
            self._status_label.setText("引擎状态: ● online")
            self._status_label.setStyleSheet(
                "font-weight: bold; font-size: 14px; color: #4caf50;"
            )
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
            self._tree.show()
            self._placeholder.hide()
            self._render_tree(self._state.nodes)
        else:
            # offline / starting / error
            if status == "starting":
                label = "引擎状态: ● starting"
                color = "#ff9800"
            elif status == "error":
                label = "引擎状态: ● error"
                color = "#f44336"
            else:
                label = "引擎状态: ○ offline"
                color = "#999"
            self._status_label.setText(label)
            self._status_label.setStyleSheet(
                f"font-weight: bold; font-size: 14px; color: {color};"
            )
            self._start_btn.setEnabled(True)
            self._stop_btn.setEnabled(False)
            self._tree.hide()
            self._placeholder.show()

    def _render_tree(self, nodes: dict[str, dict]):
        """填充节点树。"""
        self._tree.clear()
        for node_name, info in nodes.items():
            online = info.get("online", False)
            pid = info.get("pid", 0)
            detail = info.get("detail", "")
            display_status = "running" if online else "crashed"
            item = QTreeWidgetItem([node_name, display_status, detail, ""])
            self._tree.addTopLevelItem(item)
            btn = QPushButton("重启")
            btn.setFixedWidth(60)
            btn.setFixedHeight(26)
            btn.clicked.connect(
                lambda checked, nid=node_name: self._restart_node(nid)
            )
            self._tree.setItemWidget(item, 3, btn)
        self._tree.expandAll()

    # ── 引擎生命周期 ───────────────────────────────

    @staticmethod
    def _is_engine_running() -> bool:
        """检查是否存在 bnos_runtime 引擎进程（PowerShell 方式）。"""
        try:
            if os.name == "nt":
                ps_cmd = (
                    'Get-CimInstance Win32_Process | '
                    'Where-Object { '
                    "$_.Name -like '*python*' -and "
                    "$_.CommandLine -match 'bnos_runtime' "
                    "} | Measure-Object | Select-Object -ExpandProperty Count"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                count = int(result.stdout.strip()) if result.stdout.strip().isdigit() else 0
                return count > 0
            else:
                result = subprocess.run(
                    ["pgrep", "-f", "bnos_runtime"],
                    capture_output=True, text=True,
                )
                return result.returncode == 0
        except Exception:
            return False

    def _start_engine(self):
        """启动 BNOS 引擎（适配 bnos_runtime）。"""
        # 防重复：检查是否已有引擎进程在运行
        if self.__class__.engine_proc is not None:
            proc = self.__class__.engine_proc
            if proc.poll() is None:
                print("[NodePage] 引擎已在运行")
                return
        if self._is_engine_running():
            print("[NodePage] 存在其他引擎进程，跳过启动")
            self._state.engine_status = "online"
            return

        if not os.path.exists(PIPELINE_PATH):
            self._status_label.setText("引擎状态: ● error - pipeline.json 不存在")
            self._status_label.setStyleSheet(
                "font-weight: bold; font-size: 14px; color: #f44336;"
            )
            return
        try:
            python_exe = sys.executable
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUNBUFFERED"] = "1"
            env.setdefault("PYTHONPATH", "")
            paths = [p for p in env["PYTHONPATH"].split(os.pathsep) if p]
            pr = str(PROJECT_ROOT)
            if pr not in paths:
                paths.insert(0, pr)
            env["PYTHONPATH"] = os.pathsep.join(paths)

            # 获取当前批次的引擎日志目录
            _engine_log_dir = None
            try:
                from gui.core.logger import get_batch_dir
                _batch = get_batch_dir()
                if _batch:
                    _engine_log_dir = _batch / "engine"
                    _engine_log_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

            proc = subprocess.Popen(
                [python_exe, "-m", "bnos_runtime.engine", PIPELINE_PATH,
                 "--log-dir", str(_engine_log_dir)] if _engine_log_dir else
                [python_exe, "-m", "bnos_runtime.engine", PIPELINE_PATH],
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                text=True,
            )
            self.__class__.engine_proc = proc
            print(f"[NodePage] 引擎已启动 PID={proc.pid}")

            # 后台线程读取引擎输出，防止管道阻塞（与 main.py 一致）
            self._pipe_engine_output(proc, log_dir=_engine_log_dir)

            self._state.engine_status = "starting"
        except Exception as e:
            print(f"[NodePage] 启动引擎失败: {e}")
            self._state.engine_status = "error"

    @staticmethod
    def _pipe_engine_output(proc: subprocess.Popen, log_dir: Path | None = None):
        """后台线程：持续读取引擎的子进程输出，打印到控制台并写入日志文件。

        Args:
            proc: 引擎子进程。
            log_dir: 引擎日志目录（可选）。指定时输出追加写入 engine_pipe.log。
        """
        # 准备日志文件句柄
        log_fh = None
        if log_dir:
            log_dir = Path(log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            log_fh = open(log_dir / "engine_pipe.log", "a", encoding="utf-8")

        def _reader():
            try:
                for line in iter(proc.stdout.readline, ""):
                    if line:
                        print(f"[引擎] {line}", end="")
                        if log_fh:
                            log_fh.write(line)
                            log_fh.flush()
            except Exception:
                pass
            finally:
                if log_fh:
                    log_fh.close()

        t = threading.Thread(target=_reader, daemon=True)
        t.start()

    def _stop_engine(self):
        """停止 BNOS 引擎 — 用 PowerShell 查找并终止所有 bnos 进程。"""
        killed = 0
        my_pid = os.getpid()
        try:
            # 1) 通过 engine_proc 引用停止（如果是本页启动的）
            proc = self.__class__.engine_proc
            if proc is not None and proc.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                else:
                    proc.terminate()
                    proc.wait(timeout=5)
                killed += 1

            # 2) 用 PowerShell 匹配 bnos_runtime 相关进程（同 run.bat 清理方式）
            #    匹配条件：python 进程 + 命令行含 bnos_runtime 或 listener
            if os.name == "nt":
                ps_cmd = (
                    'Get-CimInstance Win32_Process | '
                    'Where-Object { '
                    "$_.Name -like '*python*' -and "
                    "( $_.CommandLine -match 'bnos_runtime' -or "
                    "( $_.CommandLine -match 'listener' -and $_.CommandLine -match 'node_' ) ) "
                    "} | Select-Object -ExpandProperty ProcessId"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    capture_output=True, text=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line.isdigit():
                        pid = int(line)
                        if pid and pid != my_pid:
                            r = subprocess.run(
                                ["taskkill", "/F", "/PID", line],
                                capture_output=True, text=True,
                                creationflags=subprocess.CREATE_NO_WINDOW,
                            )
                            if r.returncode == 0:
                                killed += 1
                            else:
                                print(f"[NodePage] taskkill PID {line} 失败: {r.stderr.strip()}")

            # 3) 清理残留状态文件
            try:
                if os.path.exists(BNOS_STATUS_PATH):
                    os.remove(BNOS_STATUS_PATH)
                    print(f"[NodePage] 已清理 {BNOS_STATUS_PATH}")
            except OSError as e:
                print(f"[NodePage] 清理状态文件失败: {e}")
        except Exception as e:
            print(f"[NodePage] 停止引擎时出错: {e}")

        self.__class__.engine_proc = None
        if killed > 0:
            print(f"[NodePage] 已终止 {killed} 个引擎进程")
        else:
            print(f"[NodePage] 未找到运行中的引擎进程")
        self._state.engine_status = "offline"
        self._sync_ui()

    # ── 节点操作 ───────────────────────────────────

    def _restart_node(self, node_id: str):
        """发送重启指令给引擎（写入 bnos_cmd.json）。"""
        cmd = {
            "cmd": "restart",
            "node_id": node_id,
            "timestamp": datetime.now().isoformat(),
        }
        try:
            with open(BNOS_CMD_PATH, "w", encoding="utf-8") as f:
                json.dump(cmd, f, ensure_ascii=False, indent=2)
            print(f"[NodePage] 已发送重启命令: {node_id}")
        except Exception as e:
            print(f"[NodePage] 发送重启命令失败: {e}")
