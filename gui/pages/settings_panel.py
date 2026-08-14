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
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from gui.core.config import AppConfig
from gui.core.event_bus import event_bus
from gui.core.theme_engine import theme_engine
from gui.core.icon_registry import icons
from gui.core.messages import THEME_CHANGED
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
        te = theme_engine
        return f"""
            /* 所有文字标签强制黑色 */
            QLabel {{
                color: {te.get('text_primary')};
            }}
            QGroupBox {{
                color: {te.get('text_primary')};
                font-weight: bold;
            }}
            QGroupBox::title {{
                color: {te.get('text_primary')};
            }}
            /* 下拉框白色背景 + 黑色文字 */
            QComboBox {{
                background-color: {te.get('bg_secondary')};
                color: {te.get('text_primary')};
                border: 1px solid {te.get('border_color')};
                border-radius: 4px;
                padding: 4px 8px;
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: {te.get('bg_secondary')};
                color: {te.get('text_primary')};
                selection-background-color: {te.get('sidebar_active')};
                selection-color: {te.get('text_primary')};
            }}
            /* 表单布局中的标签 */
            QFormLayout QLabel {{
                color: {te.get('text_primary')};
            }}
        """

    def _apply_style_override(self):
        """应用文字颜色覆盖样式，不改动 QPushButton 等带独立样式的控件"""
        self.setStyleSheet(self._settings_qss())

    def _on_theme_selected(self, index: int):
        data = self._preset_combo.itemData(index)
        if not data:
            return
        source, theme_id = data
        if source == "skin":
            if theme_id == self._config.get_selected_skin():
                return
            self._config.apply_skin(theme_id)
        else:
            if theme_id == self._config.get_selected_preset():
                return
            self._config.apply_preset(theme_id)
        colors = self._config.get_all_colors()
        for child in self.findChildren(QPushButton):
            key = getattr(child, "_config_key", "")
            if key and key in colors:
                child.setStyleSheet(self._btn_style(colors[key]))
                child.setToolTip(colors[key])
        event_bus.publish(THEME_CHANGED)

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
        # 内置预设 + 皮肤包平级（阶段5）
        for theme_id, name, source in self._config.get_theme_list():
            self._preset_combo.addItem(name, (source, theme_id))
        # 当前选中项（皮肤包优先，其次预设）
        current_skin = self._config.get_selected_skin()
        idx = self._preset_combo.findData(("skin", current_skin)) if current_skin else -1
        if idx < 0:
            idx = self._preset_combo.findData(("preset", self._config.get_selected_preset()))
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)
        self._preset_combo.currentIndexChanged.connect(self._on_theme_selected)
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
        reset_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {theme_engine.get('bg_primary')}; color: {theme_engine.get('text_primary')};
                border: 1px solid {theme_engine.get('border_color')}; border-radius: 4px;
                padding: 8px 20px; font-size: 14px;
            }}
            QPushButton:hover {{ background-color: {theme_engine.get('neutral_btn_hover')}; }}
        """)
        reset_btn.clicked.connect(self._reset_defaults)
        btn_layout.addStretch()
        btn_layout.addWidget(reset_btn)
        layout.addLayout(btn_layout)

        # ─── 数据库管理 ───
        db_group = QGroupBox("数据库管理")
        db_layout = QVBoxLayout(db_group)
        db_layout.setSpacing(8)

        btn_style = f"""
            QPushButton {{
                background-color: {theme_engine.get('accent_color')}; color: white;
                border: none; border-radius: 4px;
                padding: 8px 16px; font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {theme_engine.get('accent_hover')}; }}
        """
        danger_btn_style = f"""
            QPushButton {{
                background-color: {theme_engine.get('danger_color')}; color: white;
                border: none; border-radius: 4px;
                padding: 8px 16px; font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {theme_engine.get('danger_hover')}; }}
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

        self._format_btn = QPushButton("人格格式化（清空并重来）")
        self._format_btn.setStyleSheet(danger_btn_style)
        self._format_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._format_btn.clicked.connect(self._on_format)
        db_layout.addWidget(self._format_btn)

        layout.addWidget(db_group)

        # ─── 性格参数（v5.1 角色种子）───
        self._add_personality_section(layout, btn_style)

        # ─── 模式切换关键词（P2）───
        self._add_mode_keywords_section(layout, btn_style)

        # ─── Logseq 目录 ───
        logseq_group = QGroupBox("Logseq 记忆库")
        logseq_layout = QFormLayout(logseq_group)
        self._logseq_path_label = QLabel(self._get_logseq_path_display())
        self._logseq_path_label.setStyleSheet(f"color: {theme_engine.get('icon_color')}; font-size: 12px;")
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

        # 延迟加载性格参数（等待节点创建 DB 表）
        QTimer.singleShot(800, self._load_personality_ui)

    # ─── 性格参数（v5.1 角色种子）───────────────────

    # 四维性格中文名
    _PERSONALITY_DIMS = [
        ("warmth", "温暖度"),
        ("playfulness", "活泼度"),
        ("directness", "直接度"),
        ("curiosity", "好奇心"),
    ]

    def _add_personality_section(self, layout, btn_style: str):
        """添加性格参数查看 + 微调滑块区域"""
        group = QGroupBox("性格参数（AI 性格随使用演化）")
        v = QVBoxLayout(group)
        v.setSpacing(8)

        self._personality_info = QLabel("当前预设：加载中...")
        self._personality_info.setStyleSheet(
            f"color: {theme_engine.get('text_primary')}; font-size: 12px; font-weight: bold;")
        v.addWidget(self._personality_info)

        self._personality_sliders: dict[str, QSlider] = {}
        self._personality_values: dict[str, QLabel] = {}
        for dim, name in self._PERSONALITY_DIMS:
            row = QHBoxLayout()
            row.setSpacing(8)
            name_label = QLabel(f"{name}：")
            name_label.setStyleSheet(f"color: {theme_engine.get('text_primary')}; font-size: 12px;")
            name_label.setFixedWidth(60)
            row.addWidget(name_label)

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setFixedWidth(220)
            slider.setStyleSheet(f"""
                QSlider::groove:horizontal {{
                    height: 4px; background: {theme_engine.get('slider_groove')}; border-radius: 2px;
                }}
                QSlider::handle:horizontal {{
                    width: 14px; height: 14px; margin: -5px 0;
                    background: {theme_engine.get('accent_color')}; border-radius: 7px;
                }}
                QSlider::sub-page:horizontal {{
                    background: {theme_engine.get('accent_color')}; border-radius: 2px;
                }}
            """)
            row.addWidget(slider)

            val_label = QLabel("0.5")
            val_label.setStyleSheet(f"color: {theme_engine.get('text_secondary')}; font-size: 12px;")
            val_label.setFixedWidth(40)
            row.addWidget(val_label)

            slider.valueChanged.connect(
                lambda val, d=dim, lb=val_label: lb.setText(f"{val / 100.0:.1f}"))

            row.addStretch()
            v.addLayout(row)
            self._personality_sliders[dim] = slider
            self._personality_values[dim] = val_label

        save_btn = QPushButton("保存性格")
        save_btn.setStyleSheet(btn_style)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save_personality)
        v.addWidget(save_btn)

        layout.addWidget(group)

    # ─── 模式切换关键词（P2）───────────────────

    @staticmethod
    def _aaa_config_path() -> Path:
        """AAA 节点配置路径（node_config.json）"""
        return Path(__file__).resolve().parent.parent.parent \
            / "nodes" / "node_python_aaa_cognition" / "node_config.json"

    def _add_mode_keywords_section(self, layout, btn_style: str):
        """日常/工作模式切换关键词配置（写回 AAA node_config.json）"""
        group = QGroupBox("模式切换关键词")
        v = QVBoxLayout(group)
        v.setSpacing(8)

        tip = QLabel("对话中说出以下关键词即自动切换模式（子串匹配）。多个关键词用逗号分隔。")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {theme_engine.get('text_secondary')}; font-size: 12px;")
        v.addWidget(tip)

        form = QFormLayout()
        form.setSpacing(6)
        self._kw_work_edit = QLineEdit()
        self._kw_work_edit.setStyleSheet(f"""
            QLineEdit {{
                background-color: {theme_engine.get('bg_secondary')};
                color: {theme_engine.get('text_primary')};
                border: 1px solid {theme_engine.get('border_color')};
                border-radius: 4px; padding: 4px 8px;
            }}
        """)
        form.addRow("进入工作模式：", self._kw_work_edit)
        self._kw_daily_edit = QLineEdit()
        self._kw_daily_edit.setStyleSheet(self._kw_work_edit.styleSheet())
        form.addRow("进入日常模式：", self._kw_daily_edit)
        v.addLayout(form)

        save_btn = QPushButton("保存关键词")
        save_btn.setStyleSheet(btn_style)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save_mode_keywords)
        v.addWidget(save_btn)

        layout.addWidget(group)

        # 延迟加载当前关键词（节点配置已存在）
        QTimer.singleShot(0, self._load_mode_keywords)

    def _load_mode_keywords(self):
        """从 AAA node_config.json 读取 mode_keywords 填充输入框"""
        try:
            cfg_path = self._aaa_config_path()
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text("utf-8"))
                kw = cfg.get("mode_keywords") or {}
                self._kw_work_edit.setText(",".join(kw.get("work", []) or []))
                self._kw_daily_edit.setText(",".join(kw.get("daily", []) or []))
        except Exception:
            pass

    def _save_mode_keywords(self):
        """保存关键词到 AAA node_config.json（read-modify-write 保留其余配置）"""
        try:
            cfg_path = self._aaa_config_path()
            cfg = json.loads(cfg_path.read_text("utf-8")) if cfg_path.exists() else {}
            cfg["mode_keywords"] = {
                "work": [w.strip() for w in self._kw_work_edit.text().split(",") if w.strip()],
                "daily": [w.strip() for w in self._kw_daily_edit.text().split(",") if w.strip()],
            }
            cfg_path.write_text(
                json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            QMessageBox.information(self, "保存成功", "模式切换关键词已更新，下次对话生效。")
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"保存关键词失败: {e}")

    def _import_db(self):
        """延迟导入 AAA 节点 db 模块"""
        import sys
        aaa_dir = str(Path(__file__).resolve().parent.parent.parent
                      / "nodes" / "node_python_aaa_cognition")
        if aaa_dir not in sys.path:
            sys.path.insert(0, aaa_dir)
        import db
        return db

    def _load_personality_ui(self):
        """从 DB 读取当前性格向量并同步到滑块"""
        try:
            db = self._import_db()
            db.ensure(self._get_db_path())
            p = db.get_personality(self._get_db_path())
            preset_name = p.get("preset_name", "默认")
            self._personality_info.setText(
                f"当前预设：{preset_name}（参考，会随使用自然演化）")
            for dim, _name in self._PERSONALITY_DIMS:
                val = float(p.get(dim, 0.5))
                slider = self._personality_sliders[dim]
                slider.blockSignals(True)
                slider.setValue(int(val * 100))
                slider.blockSignals(False)
                self._personality_values[dim].setText(f"{val:.1f}")
        except Exception:
            self._personality_info.setText("当前预设：读取失败（节点未就绪）")

    def reload_personality(self):
        """格式化后重新加载性格 UI（供外部调用）"""
        try:
            self._load_personality_ui()
        except Exception:
            pass

    def _save_personality(self):
        """保存滑块调整后的性格向量"""
        try:
            db = self._import_db()
            db.ensure(self._get_db_path())
            current = db.get_personality(self._get_db_path())
            vector = {
                dim: self._personality_sliders[dim].value() / 100.0
                for dim, _name in self._PERSONALITY_DIMS
            }
            preset_name = current.get("preset_name", "默认")
            style = current.get("style_description", "") or (
                db.PERSONALITY_PRESETS.get("默认", {}).get("style_description", ""))
            db.save_personality(self._get_db_path(), vector, style, preset_name,
                                anchor_enabled=current.get("anchor_enabled", True),
                                instruction_enabled=current.get("instruction_enabled", False))
            QMessageBox.information(self, "保存成功", "性格参数已更新，下次对话生效。")
            self._load_personality_ui()
        except Exception as e:
            QMessageBox.warning(self, "保存失败", f"保存性格参数失败: {e}")

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
        if cmd == "format":
            if status == "ok":
                QMessageBox.information(self, "人格格式化完成", message)
                # 重新加载性格参数 UI
                self.reload_personality()
                # 清空聊天 UI 旧气泡
                mw = self._get_main_window()
                if mw is not None:
                    mw.reset_chat_after_format()
                    mw.show_personality_dialog()
            else:
                QMessageBox.warning(self, "操作失败", message)
            return
        if status == "ok":
            QMessageBox.information(self, "操作成功", message)
        else:
            QMessageBox.warning(self, "操作失败", message)

    def _get_main_window(self):
        """查找 MainWindow（含 _message_manager 属性的顶层窗口）"""
        for w in QApplication.topLevelWidgets():
            if hasattr(w, "_message_manager") and w._message_manager is not None:
                return w
        return None

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

    def _on_format(self):
        """人格格式化 = 清空所有数据 + 重置性格 + 重新选择（合并原"清空数据库"功能）"""
        msg = QMessageBox(self)
        msg.setWindowTitle("人格格式化")
        msg.setText(
            f"{icons.get('warn')} 人格格式化\n\n"
            "此操作将清空数据库中的全部数据：\n"
            "· 所有对话记录、记忆、情感与定位历史\n"
            "· AI 的当前性格与固定认知\n\n"
            "她将忘记有关你的一切，从头开始。\n"
            "完成后会重新选择性格种子。\n\n"
            "此操作不可撤销！建议先备份数据库。"
        )
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setStandardButtons(QMessageBox.StandardButton.Cancel)
        accept_btn = msg.addButton("确认格式化", QMessageBox.ButtonRole.DestructiveRole)
        msg.setDefaultButton(QMessageBox.StandardButton.Cancel)
        msg.exec()
        if msg.clickedButton() != accept_btn:
            return
        mm = self._get_manager()
        if mm:
            mm.send_db_command("format")

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
                border: 2px solid {theme_engine.get('border_color')};
                border-radius: 4px;
            }}
            QPushButton:hover {{
                border-color: {theme_engine.get('accent_color')};
            }}
        """

    def _get_db_path(self) -> str:
        """获取共享数据库路径"""
        return str(Path(__file__).resolve().parent.parent.parent
                   / "nodes" / "shared" / "chatbot.db")

