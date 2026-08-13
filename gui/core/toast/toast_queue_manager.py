"""
Toast 队列管理器 - 实现提示信息的有序排队与依次显示
适配自 BNOS 参考项目

核心功能：
1. FIFO队列管理：确保提示按顺序显示
2. 智能替换机制：同节点同操作的提示可以替换（如"正在启动"替换为"启动成功"）
3. 堆叠显示支持：最多同时显示3个Toast
4. 立即显示优先：操作状态提示（如"正在启动"）优先显示
5. 生命周期回调：Toast关闭后自动处理队列
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal


class ToastRequest:
    """Toast请求封装"""

    def __init__(
        self,
        message: str,
        toast_type: str = "info",
        duration: int = 3000,
        node_name: str | None = None,
        operation_type: str | None = None,
        is_status: bool = False,
    ):
        self.message = message
        self.toast_type = toast_type
        self.duration = duration
        self.node_name = node_name
        self.operation_type = operation_type
        self.is_status = is_status


class ToastQueueManager(QObject):
    """Toast队列管理器 - 单例模式"""

    _instance = None

    show_toast_requested = Signal(dict)

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            instance = super().__new__(cls, *args, **kwargs)
            QObject.__init__(instance)
            cls._instance = instance
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return

        self._queue = deque()
        self._active_toasts = []
        self._max_active = 3
        self._operation_toasts: dict[tuple, Any] = {}
        self._create_toast_callback: Callable | None = None
        self._parent_window = None

        self._initialized = True

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def initialize(self, parent_window, create_toast_callback):
        self._parent_window = parent_window
        self._create_toast_callback = create_toast_callback

    def show_toast(
        self,
        message: str,
        toast_type: str = "info",
        duration: int = 3000,
        node_name: str | None = None,
        operation_type: str | None = None,
    ):
        """请求显示Toast提示"""
        is_status = toast_type == "info" and (operation_type in ("start", "stop", "delete", "create"))

        if node_name is not None and operation_type is not None:
            key = (node_name, operation_type)

            if key in self._operation_toasts:
                existing_toast = self._operation_toasts[key]
                if existing_toast and existing_toast.isVisible():
                    if is_status:
                        existing_toast._label.setText(message)
                        existing_toast._stay_timer.start(duration)
                        return
                    else:
                        self._remove_toast(existing_toast, key)

            for req in self._queue:
                if req.node_name == node_name and req.operation_type == operation_type:
                    req.message = message
                    req.toast_type = toast_type
                    req.duration = duration
                    req.is_status = is_status
                    return

        request = ToastRequest(
            message=message,
            toast_type=toast_type,
            duration=duration,
            node_name=node_name,
            operation_type=operation_type,
            is_status=is_status,
        )

        if is_status:
            self._queue.appendleft(request)
        else:
            self._queue.append(request)

        self._process_queue()

    def _process_queue(self):
        """处理队列，显示下一个Toast"""
        if self._parent_window and (
            self._parent_window.isMinimized() or not self._parent_window.isVisible()
        ):
            return

        if len(self._active_toasts) >= self._max_active:
            return

        if not self._queue:
            return

        request = self._queue.popleft()

        if self._create_toast_callback:
            stack_index = len(self._active_toasts)
            toast = self._create_toast_callback(
                message=request.message,
                toast_type=request.toast_type,
                duration=request.duration,
                stack_index=stack_index,
                node_name=request.node_name,
                operation_type=request.operation_type,
            )

            if request.node_name is not None and request.operation_type is not None:
                key = (request.node_name, request.operation_type)
                self._operation_toasts[key] = toast

            self._active_toasts.append(toast)
            toast.closed.connect(lambda t=toast: self._on_toast_closed(t))
            toast.show_toast()

    def _remove_toast(self, toast, key: tuple = None):
        toast._anim_timer.stop()
        if toast._stay_timer.isActive():
            toast._stay_timer.stop()

        if toast in self._active_toasts:
            self._active_toasts.remove(toast)

        if key:
            if self._operation_toasts.get(key) == toast:
                del self._operation_toasts[key]

        toast.close()
        self._update_positions()
        QTimer.singleShot(50, self._process_queue)

    def _on_toast_closed(self, toast):
        keys_to_remove = []
        for key, t in self._operation_toasts.items():
            if t == toast:
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del self._operation_toasts[key]

        if toast in self._active_toasts:
            self._active_toasts.remove(toast)

        self._update_positions()
        QTimer.singleShot(50, self._process_queue)

    def _update_positions(self):
        for i, toast in enumerate(self._active_toasts):
            if toast.stack_index != i:
                toast.stack_index = i
                toast.update_position()

        QTimer.singleShot(50, self._process_queue)

    def clear_all(self):
        self._queue.clear()
        for toast in list(self._active_toasts):
            self._remove_toast(toast)
        self._operation_toasts.clear()

    def get_active_count(self):
        return len(self._active_toasts)

    def get_queue_size(self):
        return len(self._queue)
