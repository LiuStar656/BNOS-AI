"""设置页 — 主题颜色自定义 + 数据库管理"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.core.config import AppConfig
from gui.core.event_bus import event_bus
from gui.widgets.color_picker import ColorPickerPopup


class SettingsPage(QWidget):
    """设置页 — 主题颜色自定义"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = AppConfig()

        self._init_ui()

        # 监听主题变更，刷新自身背景
        event_bus.subscribe("theme_changed", self._on_theme_changed)

    def _on_theme_changed(self, _data=None):
        colors = self._config.get_all_colors()
        p = self.palette()
        p.setColor(QPalette.Window, QColor(colors['bg_secondary']))
        self.setPalette(p)
        self.setAutoFillBackground(True)

    def _on_preset_changed(self, index: int):
        """主题预设选择变更"""
        preset_id = self._preset_combo.itemData(index)
        if not preset_id or preset_id == self._config.get_selected_preset():
            return
        self._config.apply_preset(preset_id)
        # 刷新所有颜色按钮
        colors = self._config.get_all_colors()
        for child in self.findChildren(QPushButton):
            key = getattr(child, "_config_key", "")
            if key and key in colors:
                child.setStyleSheet(self._btn_style(colors[key]))
                child.setToolTip(colors[key])
        # 广播主题变更事件
        event_bus.publish("theme_changed")

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        colors = AppConfig().get_all_colors()
        p = self.palette()
        p.setColor(QPalette.Window, QColor(colors['bg_secondary']))
        self.setPalette(p)
        self.setAutoFillBackground(True)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background-color: {colors['bg_secondary']}; border: none; }}
        """)

        content = QWidget()
        content.setObjectName("settings_content")
        content.setStyleSheet(f"""
            #settings_content {{ background-color: {colors['bg_secondary']}; }}
        """)
        self._form_layout = QVBoxLayout(content)
        self._form_layout.setSpacing(12)
        self._form_layout.setContentsMargins(24, 16, 24, 16)

        # ─── 主题预设选择 ───
        preset_group = QGroupBox("主题预设")
        preset_layout = QHBoxLayout(preset_group)
        self._preset_combo = QComboBox()
        self._preset_combo.setMinimumWidth(200)
        # 填充预设列表
        for pid, name in AppConfig.get_preset_list():
            self._preset_combo.addItem(name, pid)
        # 选中当前预设
        current_preset = self._config.get_selected_preset()
        idx = self._preset_combo.findData(current_preset)
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(QLabel("选择主题："))
        preset_layout.addWidget(self._preset_combo)
        preset_layout.addStretch()
        self._form_layout.addWidget(preset_group)

        # ─── 强调色 ───
        accent_group = QGroupBox("强调色")
        accent_layout = QFormLayout(accent_group)
        self._accent_btn = self._color_button(self._config.get_theme("accent_color"), "accent_color")
        self._accent_btn.clicked.connect(lambda: self._pick_color("accent_color", self._accent_btn))
        accent_layout.addRow("主色调", self._accent_btn)

        accent_hover_btn = self._color_button(self._config.get_theme("accent_hover"), "accent_hover")
        accent_hover_btn.clicked.connect(lambda: self._pick_color("accent_hover", accent_hover_btn))
        accent_layout.addRow("悬停色", accent_hover_btn)
        self._form_layout.addWidget(accent_group)

        # ─── 聊天区域 ───
        chat_group = QGroupBox("聊天区域")
        chat_layout = QFormLayout(chat_group)
        self._chat_bg_btn = self._color_button(self._config.get_theme("bg_chat"), "bg_chat")
        self._chat_bg_btn.clicked.connect(lambda: self._pick_color("bg_chat", self._chat_bg_btn))
        chat_layout.addRow("聊天背景", self._chat_bg_btn)
        self._form_layout.addWidget(chat_group)

        # ─── 气泡颜色 ───
        bubble_group = QGroupBox("消息气泡")
        bubble_layout = QFormLayout(bubble_group)

        self._bubble_user_btn = self._color_button(self._config.get_theme("bubble_user_bg"), "bubble_user_bg")
        self._bubble_user_btn.clicked.connect(lambda: self._pick_color("bubble_user_bg", self._bubble_user_btn))
        bubble_layout.addRow("用户气泡", self._bubble_user_btn)

        bubble_user_text_btn = self._color_button(self._config.get_theme("bubble_user_text"), "bubble_user_text")
        bubble_user_text_btn.clicked.connect(lambda: self._pick_color("bubble_user_text", bubble_user_text_btn))
        bubble_layout.addRow("用户文字色", bubble_user_text_btn)

        self._bubble_ai_btn = self._color_button(self._config.get_theme("bubble_ai_bg"), "bubble_ai_bg")
        self._bubble_ai_btn.clicked.connect(lambda: self._pick_color("bubble_ai_bg", self._bubble_ai_btn))
        bubble_layout.addRow("AI 气泡", self._bubble_ai_btn)

        bubble_ai_text_btn = self._color_button(self._config.get_theme("bubble_ai_text"), "bubble_ai_text")
        bubble_ai_text_btn.clicked.connect(lambda: self._pick_color("bubble_ai_text", bubble_ai_text_btn))
        bubble_layout.addRow("AI 文字色", bubble_ai_text_btn)
        self._form_layout.addWidget(bubble_group)

        # ─── 侧边栏 ───
        sidebar_group = QGroupBox("侧边栏")
        sidebar_layout = QFormLayout(sidebar_group)

        self._sidebar_bg_btn = self._color_button(self._config.get_theme("sidebar_bg"), "sidebar_bg")
        self._sidebar_bg_btn.clicked.connect(lambda: self._pick_color("sidebar_bg", self._sidebar_bg_btn))
        sidebar_layout.addRow("背景色", self._sidebar_bg_btn)

        sidebar_active_btn = self._color_button(self._config.get_theme("sidebar_active"), "sidebar_active")
        sidebar_active_btn.clicked.connect(lambda: self._pick_color("sidebar_active", sidebar_active_btn))
        sidebar_layout.addRow("选中高亮", sidebar_active_btn)

        sidebar_active_text_btn = self._color_button(self._config.get_theme("sidebar_active_text"), "sidebar_active_text")
        sidebar_active_text_btn.clicked.connect(
            lambda: self._pick_color("sidebar_active_text", sidebar_active_text_btn)
        )
        sidebar_layout.addRow("选中文字色", sidebar_active_text_btn)
        self._form_layout.addWidget(sidebar_group)

        # ─── 操作按钮 ───
        btn_layout = QHBoxLayout()
        reset_btn = QPushButton("恢复默认")
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5; color: #333;
                border: 1px solid #d0d0d0; border-radius: 4px;
                padding: 8px 20px; font-size: 14px;
            }
            QPushButton:hover { background-color: #e8e8e8; }
        """)
        reset_btn.clicked.connect(self._reset_defaults)
        btn_layout.addStretch()
        btn_layout.addWidget(reset_btn)
        self._form_layout.addLayout(btn_layout)

        # ─── 数据库管理 ───
        db_group = QGroupBox("数据库管理")
        db_layout = QVBoxLayout(db_group)
        db_layout.setSpacing(8)

        btn_style = """
            QPushButton {
                background-color: #1a73e8; color: white;
                border: none; border-radius: 4px;
                padding: 8px 16px; font-size: 13px;
            }
            QPushButton:hover { background-color: #1557b0; }
        """
        danger_btn_style = """
            QPushButton {
                background-color: #d32f2f; color: white;
                border: none; border-radius: 4px;
                padding: 8px 16px; font-size: 13px;
            }
            QPushButton:hover { background-color: #b71c1c; }
        """

        self._backup_btn = QPushButton("备份数据库")
        self._backup_btn.setStyleSheet(btn_style)
        self._backup_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._backup_btn.clicked.connect(lambda: self._on_backup())
        db_layout.addWidget(self._backup_btn)

        self._restore_btn = QPushButton("恢复数据库")
        self._restore_btn.setStyleSheet(btn_style)
        self._restore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._restore_btn.clicked.connect(lambda: self._on_restore())
        db_layout.addWidget(self._restore_btn)

        self._clear_btn = QPushButton("清空数据库")
        self._clear_btn.setStyleSheet(danger_btn_style)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(lambda: self._on_clear())
        db_layout.addWidget(self._clear_btn)

        self._form_layout.addWidget(db_group)

        self._form_layout.addStretch()

        scroll.setWidget(content)
        layout.addWidget(scroll)

        # 延迟连接 MessageManager 信号（窗口树可能在 init 时未完整构建）
        QTimer.singleShot(0, self._connect_message_manager)

    # ─── 数据库管理 ──────────────────────────────────

    def _get_manager(self):
        """获取 MessageManager 实例（按需延迟加载）。"""
        w = self.window()
        if w and hasattr(w, "_message_manager"):
            return w._message_manager
        return None

    def _connect_message_manager(self):
        mm = self._get_manager()
        if mm:
            mm.cmd_result_received.connect(self._on_db_result)

    def _on_db_result(self, cmd, status, message):
        if status == "ok":
            QMessageBox.information(self, "操作成功", message)
        else:
            QMessageBox.warning(self, "操作失败", message)

    def _on_backup(self):
        mm = self._get_manager()
        if mm:
            self._backup_btn.setEnabled(False)
            self._backup_btn.setText("正在备份...")
            mm.send_db_command("backup")
            # 5s 保护兜底：结果信号未触发时自动恢复按钮状态
            QTimer.singleShot(5000, self._restore_backup_btn)

    def _restore_backup_btn(self):
        self._backup_btn.setEnabled(True)
        self._backup_btn.setText("备份数据库")

    def _on_restore(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("恢复数据库")
        msg.setText("请选择一个备份文件恢复数据库。\n此操作将覆盖当前数据库，不可撤销。")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setStandardButtons(QMessageBox.StandardButton.Cancel)
        accept_btn = msg.addButton("选择文件", QMessageBox.ButtonRole.AcceptRole)
        msg.exec()
        if msg.clickedButton() != accept_btn:
            return
        backup_path, _ = QFileDialog.getOpenFileName(
            self, "选择备份文件", "", "DB 文件 (*.db);;所有文件 (*)"
        )
        if not backup_path:
            return
        backup_name = os.path.basename(backup_path)
        mm = self._get_manager()
        if mm:
            mm.send_db_command("restore", {"backup_file": backup_name})

    def _on_clear(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("清空数据库")
        msg.setText("确定要清空所有数据吗？\n\n此操作将删除所有对话记录和记忆数据，但保留数据库表结构。\n此操作不可撤销！")
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() == QMessageBox.StandardButton.Yes:
            mm = self._get_manager()
            if mm:
                mm.send_db_command("clear")

    # ─── 工具方法 ──────────────────────────────────

    def _color_button(self, hex_color: str, config_key: str = "") -> QPushButton:
        btn = QPushButton()
        btn.setFixedSize(32, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn._config_key = config_key
        btn.setStyleSheet(self._btn_style(hex_color))
        btn.setToolTip(hex_color)
        return btn

    def _pick_color(self, config_key: str, btn: QPushButton):
        current = QColor(self._config.get_theme(config_key, "#ffffff"))
        color = ColorPickerPopup.get_color(current, self)
        if color:
            hex_color = color.name()
            self._config.set_theme(config_key, hex_color)
            self._config.save()
            btn.setStyleSheet(self._btn_style(hex_color))
            btn.setToolTip(hex_color)
            # 广播主题变更事件，让主窗口立即刷新
            event_bus.publish("theme_changed")

    def _reset_defaults(self):
        defaults = AppConfig().config["theme"]
        self._config.apply_theme(defaults)
        for child in self.findChildren(QPushButton):
            key = getattr(child, "_config_key", "")
            if key and key in defaults:
                child.setStyleSheet(self._btn_style(defaults[key]))
                child.setToolTip(defaults[key])
        event_bus.publish("theme_changed")

    @staticmethod
    def _btn_style(hex_color: str) -> str:
        return f"""
            QPushButton {{
                background-color: {hex_color};
                border: 2px solid #d0d0d0;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                border-color: #1a73e8;
            }}
        """
