"""AI 定位信息页面 — 独立标签页展示实时地图与位置状态

从设置面板的"AI 地理感知"区域迁移而来，作为 GUI 侧边栏独立标签页：
- 大尺寸地图显示（自动刷新当前城市位置）
- 位置信息栏（城市 / 精度 / 来源）
- 控制区（刷新位置 / 自动更新 / 启用位置信息 / 清除历史）
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.core.config import AppConfig
from gui.widgets.location_map_widget import LocationMapWidget


class LocationPage(QWidget):
    """AI 定位信息页（独立标签页）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = AppConfig()
        self._build_ui()

        # 初始加载位置
        QTimer.singleShot(1000, self._refresh_location)

    # ─── UI 构建 ──────────────────────────────────────────

    def _build_ui(self):
        colors = self._config.get_all_colors()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(10)

        # 标题行
        title_row = QHBoxLayout()
        title = QLabel("AI 定位信息")
        title.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {colors['text_primary']};")
        title_row.addWidget(title)
        title_row.addStretch()

        refresh_btn = QPushButton("刷新位置")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a73e8; color: white;
                border: none; border-radius: 4px;
                padding: 6px 16px; font-size: 12px;
            }
            QPushButton:hover { background-color: #1557b0; }
        """)
        refresh_btn.clicked.connect(self._refresh_location)
        title_row.addWidget(refresh_btn)

        clear_btn = QPushButton("清除历史")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #d32f2f; color: white;
                border: none; border-radius: 4px;
                padding: 6px 16px; font-size: 12px;
            }
            QPushButton:hover { background-color: #b71c1c; }
        """)
        clear_btn.clicked.connect(self._clear_location_history)
        title_row.addWidget(clear_btn)
        lay.addLayout(title_row)

        # 地图显示区（主区域）
        self.location_map = LocationMapWidget()
        self.location_map.setMinimumHeight(300)
        lay.addWidget(self.location_map, 1)

        # 位置信息栏
        self.location_info_label = QLabel("位置：加载中...")
        self.location_info_label.setStyleSheet(
            "font-weight: bold; padding: 8px 4px; font-size: 14px; color: #000000;")
        lay.addWidget(self.location_info_label)

        # 开关行
        toggle_row = QHBoxLayout()
        self.loc_auto_check = QCheckBox("自动更新（5 分钟）")
        self.loc_auto_check.setChecked(True)
        self.loc_auto_check.stateChanged.connect(self._on_auto_update_toggled)
        toggle_row.addWidget(self.loc_auto_check)

        self.loc_enable_check = QCheckBox("启用位置信息")
        self.loc_enable_check.setChecked(True)
        self.loc_enable_check.stateChanged.connect(self._on_location_enable_toggled)
        toggle_row.addWidget(self.loc_enable_check)

        toggle_row.addStretch()
        lay.addLayout(toggle_row)

    # ─── 位置获取 ─────────────────────────────────────────

    @staticmethod
    def _get_db_path() -> str:
        """获取共享数据库路径"""
        return str(Path(__file__).resolve().parent.parent.parent
                   / "nodes" / "shared" / "chatbot.db")

    def _get_location_manager(self):
        """延迟导入 LocationManager"""
        aaa_dir = str(Path(__file__).resolve().parent.parent.parent
                      / "nodes" / "node_python_aaa_cognition")
        if aaa_dir not in sys.path:
            sys.path.insert(0, aaa_dir)
        from location import LocationManager
        return LocationManager(self._get_db_path(), identity_key="gui:default")

    def _refresh_location(self):
        """手动刷新位置（后台线程，避免阻塞 UI）"""
        def _fetch():
            try:
                mgr = self._get_location_manager()
                result = mgr.get_location(force_refresh=True)
                if result.success and result.location:
                    loc = result.location
                    QTimer.singleShot(
                        0, lambda: self._update_location_ui(loc.to_dict()))
                else:
                    QTimer.singleShot(
                        0, lambda: self.location_info_label.setText(
                            f"定位失败: {result.error or '未知错误'}"))
            except Exception as e:
                QTimer.singleShot(
                    0, lambda: self.location_info_label.setText(f"定位异常: {e}"))

        self.location_info_label.setText("正在获取位置...")
        threading.Thread(target=_fetch, daemon=True).start()

    def _update_location_ui(self, location_dict: dict):
        """更新位置显示 UI"""
        city = location_dict.get("city") or "未知"
        accuracy = location_dict.get("accuracy", 0)
        source = location_dict.get("source", "unknown")

        source_map = {
            "qt_gps": "GPS", "qt_wifi": "Wi-Fi", "qt_cell": "基站",
            "qt_unknown": "系统定位", "ip": "IP", "cache": "缓存",
        }
        source_text = source_map.get(source, source)

        info = f"位置：{city} | 精度：{accuracy:.0f}米 | 来源：{source_text}"
        self.location_info_label.setText(info)

        # 更新地图
        self.location_map.update_location(location_dict)

    # ─── 开关逻辑 ─────────────────────────────────────────

    def _on_auto_update_toggled(self, state: int):
        """自动更新开关（持久化 + 启停 QtLocationProvider）"""
        enabled = bool(state)
        loc_cfg = self._config.get("location", {})
        if not isinstance(loc_cfg, dict):
            loc_cfg = {}
        loc_cfg["auto_update"] = enabled
        self._config.set("location", loc_cfg)
        self._config.save()

        for w in QApplication.topLevelWidgets():
            provider = getattr(w, "_location_provider", None)
            if provider:
                if enabled:
                    provider.start()
                else:
                    provider.stop()
                break

    def _on_location_enable_toggled(self, state: int):
        """启用/禁用位置信息"""
        enabled = bool(state)
        loc_cfg = self._config.get("location", {})
        if not isinstance(loc_cfg, dict):
            loc_cfg = {}
        loc_cfg["enabled"] = enabled
        self._config.set("location", loc_cfg)
        self._config.save()

        if not enabled:
            for w in QApplication.topLevelWidgets():
                provider = getattr(w, "_location_provider", None)
                if provider:
                    provider.stop()
                    break
            self.location_info_label.setText("位置信息已禁用")
            self.location_map._show_placeholder("位置信息已禁用")

    def _clear_location_history(self):
        """清除位置历史记录"""
        reply = QMessageBox.question(
            self, "清除历史",
            "确定要清除所有位置历史记录吗？此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            mgr = self._get_location_manager()
            count = mgr.clear_location_history()
            QMessageBox.information(
                self, "清除成功", f"已清除 {count} 条位置历史记录")
            self.location_map._show_placeholder("点击\"刷新位置\"获取当前位置")
            self.location_info_label.setText("位置：已清除历史")
        except Exception as e:
            QMessageBox.warning(self, "清除失败", f"清除历史记录失败: {e}")
