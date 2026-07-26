"""设置面板内容组件 — 主题颜色自定义 + 数据库管理（嵌入 FloatingPanel 使用）"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.core.config import AppConfig
from gui.core.event_bus import event_bus
from gui.widgets.color_picker import ColorPickerPopup


class SettingsPanel(QWidget):
    """设置面板内容 — 主题颜色自定义 + 数据库管理"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = AppConfig()

        colors = self._config.get_all_colors()
        p = self.palette()
        p.setColor(QPalette.Window, QColor(colors['bg_secondary']))
        self.setPalette(p)
        self.setAutoFillBackground(True)

        self._init_ui()
        self._apply_style_override()

        # 监听主题变更
        event_bus.subscribe("theme_changed", self._on_theme_changed)

    def _on_theme_changed(self, _data=None):
        colors = self._config.get_all_colors()
        p = self.palette()
        p.setColor(QPalette.Window, QColor(colors['bg_secondary']))
        self.setPalette(p)
        self.setAutoFillBackground(True)
        self._apply_style_override()

    @staticmethod
    def _settings_qss() -> str:
        """设置面板专用样式：所有文字黑色，下拉框白色背景"""
        return """
            /* 所有文字标签强制黑色 */
            QLabel {
                color: #000000;
            }
            QGroupBox {
                color: #000000;
                font-weight: bold;
            }
            QGroupBox::title {
                color: #000000;
            }
            /* 下拉框白色背景 + 黑色文字 */
            QComboBox {
                background-color: #ffffff;
                color: #000000;
                border: 1px solid #d0d0d0;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                color: #000000;
                selection-background-color: #e8f0fe;
                selection-color: #000000;
            }
            /* 表单布局中的标签 */
            QFormLayout QLabel {
                color: #000000;
            }
        """

    def _apply_style_override(self):
        """应用文字颜色覆盖样式，不改动 QPushButton 等带独立样式的控件"""
        self.setStyleSheet(self._settings_qss())

    def _on_preset_changed(self, index: int):
        preset_id = self._preset_combo.itemData(index)
        if not preset_id or preset_id == self._config.get_selected_preset():
            return
        self._config.apply_preset(preset_id)
        colors = self._config.get_all_colors()
        for child in self.findChildren(QPushButton):
            key = getattr(child, "_config_key", "")
            if key and key in colors:
                child.setStyleSheet(self._btn_style(colors[key]))
                child.setToolTip(colors[key])
        event_bus.publish("theme_changed")

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 16, 24, 16)

        colors = self._config.get_all_colors()

        # ─── 主题预设选择 ───
        preset_group = QGroupBox("主题预设")
        preset_layout = QHBoxLayout(preset_group)
        self._preset_combo = QComboBox()
        self._preset_combo.setMinimumWidth(200)
        for pid, name in AppConfig.get_preset_list():
            self._preset_combo.addItem(name, pid)
        current_preset = self._config.get_selected_preset()
        idx = self._preset_combo.findData(current_preset)
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(QLabel("选择主题："))
        preset_layout.addWidget(self._preset_combo)
        preset_layout.addStretch()
        layout.addWidget(preset_group)

        # ─── 强调色 ───
        accent_group = QGroupBox("强调色")
        accent_layout = QFormLayout(accent_group)
        self._accent_btn = self._color_button(self._config.get_theme("accent_color"), "accent_color")
        self._accent_btn.clicked.connect(lambda: self._pick_color("accent_color", self._accent_btn))
        accent_layout.addRow("主色调", self._accent_btn)
        accent_hover_btn = self._color_button(self._config.get_theme("accent_hover"), "accent_hover")
        accent_hover_btn.clicked.connect(lambda: self._pick_color("accent_hover", accent_hover_btn))
        accent_layout.addRow("悬停色", accent_hover_btn)
        layout.addWidget(accent_group)

        # ─── 聊天区域 ───
        chat_group = QGroupBox("聊天区域")
        chat_layout = QFormLayout(chat_group)
        self._chat_bg_btn = self._color_button(self._config.get_theme("bg_chat"), "bg_chat")
        self._chat_bg_btn.clicked.connect(lambda: self._pick_color("bg_chat", self._chat_bg_btn))
        chat_layout.addRow("聊天背景", self._chat_bg_btn)
        layout.addWidget(chat_group)

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
        layout.addWidget(bubble_group)

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
        layout.addWidget(sidebar_group)

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
        layout.addLayout(btn_layout)

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
        self._backup_btn.clicked.connect(self._on_backup)
        db_layout.addWidget(self._backup_btn)

        self._restore_btn = QPushButton("恢复数据库")
        self._restore_btn.setStyleSheet(btn_style)
        self._restore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._restore_btn.clicked.connect(self._on_restore)
        db_layout.addWidget(self._restore_btn)

        self._clear_btn = QPushButton("清空数据库")
        self._clear_btn.setStyleSheet(danger_btn_style)
        self._clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_btn.clicked.connect(self._on_clear)
        db_layout.addWidget(self._clear_btn)

        layout.addWidget(db_group)

        # ─── Logseq 目录 ───
        logseq_group = QGroupBox("Logseq 知识库")
        logseq_layout = QFormLayout(logseq_group)
        self._logseq_path_label = QLabel(self._get_logseq_path_display())
        self._logseq_path_label.setStyleSheet("color: #555; font-size: 12px;")
        self._logseq_browse_btn = QPushButton("浏览...")
        self._logseq_browse_btn.setStyleSheet(btn_style)
        self._logseq_browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._logseq_browse_btn.clicked.connect(self._on_select_logseq_dir)
        path_row = QHBoxLayout()
        path_row.addWidget(self._logseq_path_label, 1)
        path_row.addWidget(self._logseq_browse_btn)
        logseq_layout.addRow("Pages 目录", path_row)
        layout.addWidget(logseq_group)

        layout.addStretch()

        # 延迟连接 MessageManager 信号
        QTimer.singleShot(0, self._connect_message_manager)

    # ─── Logseq 目录 ────────────────────────────

    def _get_logseq_path_display(self) -> str:
        """从 gui_config.json 读取 Logseq pages 目录，返回显示文本"""
        try:
            cfg_path = Path(__file__).resolve().parent.parent.parent / "gui_config.json"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text("utf-8"))
                path = cfg.get("logseq", {}).get("pages_dir", "")
                return path if path else "（未设置）"
        except Exception:
            pass
        return "（未设置）"

    def _on_select_logseq_dir(self):
        """选择 Logseq pages 目录"""
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择 Logseq pages 目录（包含 Logseq markdown 文件的位置）"
        )
        if not dir_path:
            return

        # 持久化到 gui_config.json
        try:
            cfg_path = Path(__file__).resolve().parent.parent.parent / "gui_config.json"
            cfg = json.loads(cfg_path.read_text("utf-8")) if cfg_path.exists() else {}
            cfg.setdefault("logseq", {})["pages_dir"] = dir_path
            cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            self._logseq_path_label.setText(dir_path)

            # 通知已存在的 LogseqWriter 更新路径
            for w in QApplication.topLevelWidgets():
                if hasattr(w, "_logseq_writer"):
                    w._logseq_writer.set_pages_dir(dir_path)
                    break
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"Logseq 目录配置保存失败: {e}")

    # ─── 数据库管理 ──────────────────────────────

    def _get_manager(self):
        """查找 MainWindow 的 _message_manager"""
        # self.window() 在 FloatingPanel 中返回的是面板自身，不是 MainWindow
        # 遍历所有顶级窗口查找 MainWindow
        from PySide6.QtWidgets import QApplication
        for w in QApplication.topLevelWidgets():
            if hasattr(w, "_message_manager") and w._message_manager is not None:
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

    # ─── 工具方法 ──────────────────────────────

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
