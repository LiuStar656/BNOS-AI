"""性格种子选择对话框 — 首次启动 / 人格格式化后弹出

用户从 5 个预设（默认/温柔型/理性型/毒舌型/活泼型）中选择一个起点，
也可拖动滑块自定义四维向量。选择后写入 personality_seed 表并注入
3 条初始背景记忆（source='seed'）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from gui.core.config import AppConfig
from gui.core.theme_engine import theme_engine

# ─── 路径 ─────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_PATH = str(_PROJECT_ROOT / "nodes" / "shared" / "chatbot.db")
_AAA_DIR = str(_PROJECT_ROOT / "nodes" / "node_python_aaa_cognition")

# 维度中文名
_DIM_LABELS = {
    "warmth": "温暖度",
    "playfulness": "活泼度",
    "directness": "直接度",
    "curiosity": "好奇心",
}
_DIM_ORDER = ["warmth", "playfulness", "directness", "curiosity"]


def _load_db():
    """延迟导入 AAA 节点的 db 模块（避免 GUI 启动时依赖节点目录）"""
    if _AAA_DIR not in sys.path:
        sys.path.insert(0, _AAA_DIR)
    import db
    return db


def has_personality(db_path: str = _DB_PATH,
                    identity_key: str = "gui:default") -> bool:
    """是否已存在性格种子（用于首次启动检测）"""
    try:
        db = _load_db()
        return bool(db.get_personality(db_path, identity_key).get("exists"))
    except Exception:
        return True  # 读取失败时不打扰用户


def apply_personality(db_path: str = _DB_PATH, vector: dict = None,
                      style_description: str = "", preset_name: str = "自定义",
                      identity_key: str = "gui:default") -> bool:
    """保存性格向量 + 写入初始背景记忆（幂等）；保留现有注入开关"""
    try:
        db = _load_db()
        db.ensure(db_path)
        current = db.get_personality(db_path, identity_key)
        db.save_personality(db_path, vector or {}, style_description,
                            preset_name, identity_key,
                            anchor_enabled=current.get("anchor_enabled", True),
                            instruction_enabled=current.get("instruction_enabled", False))
        db.write_seed_background(db_path, identity_key)
        return True
    except Exception:
        return False


class PersonalityDialog(QDialog):
    """性格选择对话框 — 预设卡片 + 四维滑块自定义"""

    def __init__(self, parent_window=None, title="选择阿镜的性格",
                 identity_key: str = "gui:default"):
        super().__init__()
        self._parent_window = parent_window
        self._identity_key = identity_key
        self._config = AppConfig()
        self._current_preset = "默认"
        self._sliders: dict[str, QSlider] = {}
        self._value_labels: dict[str, QLabel] = {}

        try:
            self._db = _load_db()
        except Exception:
            self._db = None

        self._presets = (
            self._db.PERSONALITY_PRESETS if self._db else {}
        )

        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(620, 420)

        self._build_ui()
        self._apply_preset("默认")

    # ─── UI ──────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QWidget()
        container.setStyleSheet(f"""
            QWidget {{ background-color: {theme_engine.get('bg_secondary')};
                      border-radius: 10px; border: 1px solid {theme_engine.get('border_color')}; }}
        """)
        outer.addWidget(container)

        lay = QVBoxLayout(container)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(10)

        # 标题
        title = QLabel("选择阿镜的性格")
        title.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {theme_engine.get('text_primary')};"
                            "background: transparent;")
        lay.addWidget(title)

        subtitle = QLabel("第一次见面，先选一个性格起点。它会随你们的相处自然演化，"
                          "之后也可以在设置里手动微调。")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"font-size: 12px; color: {theme_engine.get('text_secondary')}; background: transparent;")
        lay.addWidget(subtitle)

        # 预设卡片行
        card_row = QHBoxLayout()
        card_row.setSpacing(10)
        self._cards: dict[str, QPushButton] = {}
        for name, data in self._presets.items():
            keywords = self._preset_keywords(name)
            card = QPushButton()
            card.setCheckable(True)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.setFixedHeight(86)
            card.setText(f"{name}\n{keywords}")
            card.setStyleSheet(self._card_qss(False))
            card.clicked.connect(lambda checked, n=name: self._apply_preset(n))
            card_row.addWidget(card, 1)
            self._cards[name] = card
        lay.addLayout(card_row)

        # 分隔
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {theme_engine.get('separator')};")
        lay.addWidget(sep)

        # 四维滑块
        slider_grid = QGridLayout()
        slider_grid.setSpacing(8)
        for i, dim in enumerate(_DIM_ORDER):
            name_label = QLabel(f"{_DIM_LABELS[dim]}：")
            name_label.setStyleSheet(f"font-size: 12px; color: {theme_engine.get('text_primary')};"
                                     "background: transparent;")
            name_label.setFixedWidth(60)
            slider_grid.addWidget(name_label, i, 0)

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100)
            slider.setFixedWidth(320)
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
            slider_grid.addWidget(slider, i, 1)
            self._sliders[dim] = slider

            value_label = QLabel("0.5")
            value_label.setStyleSheet(f"font-size: 12px; color: {theme_engine.get('text_secondary')};"
                                      "background: transparent;")
            value_label.setFixedWidth(40)
            slider_grid.addWidget(value_label, i, 2)
            self._value_labels[dim] = value_label

            slider.valueChanged.connect(
                lambda v, dim=dim: self._on_slider_changed(dim, v))
        lay.addLayout(slider_grid)

        lay.addStretch()

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        skip_btn = QPushButton("稍后再说")
        skip_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {theme_engine.get('bg_primary')}; color: {theme_engine.get('text_secondary')};
                          border: 1px solid {theme_engine.get('border_color')}; border-radius: 4px;
                          padding: 8px 24px; font-size: 13px; }}
            QPushButton:hover {{ background-color: {theme_engine.get('neutral_btn_hover')}; }}
        """)
        skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        skip_btn.clicked.connect(self._on_skip)
        btn_row.addWidget(skip_btn)

        save_btn = QPushButton("开始使用")
        save_btn.setStyleSheet(f"""
            QPushButton {{ background-color: {theme_engine.get('accent_color')}; color: white;
                          border: none; border-radius: 4px;
                          padding: 8px 32px; font-size: 13px; }}
            QPushButton:hover {{ background-color: {theme_engine.get('accent_hover')}; }}
        """)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        lay.addLayout(btn_row)

    @staticmethod
    def _preset_keywords(name: str) -> str:
        """预设的关键词摘要（与方案 §3.1.2 一致）"""
        return {
            "默认": "自然 · 平衡",
            "温柔型": "关心 · 柔和",
            "理性型": "精确 · 简洁",
            "毒舌型": "直接 · 调侃",
            "活泼型": "热情 · 好奇",
        }.get(name, "")

    def _card_qss(self, selected: bool) -> str:
        if selected:
            return f"""
                QPushButton {{
                    background-color: {theme_engine.get('sidebar_active')}; color: {theme_engine.get('accent_color')};
                    border: 2px solid {theme_engine.get('accent_color')}; border-radius: 8px;
                    font-size: 13px; font-weight: bold;
                }}
            """
        return f"""
            QPushButton {{
                background-color: {theme_engine.get('bg_primary')}; color: {theme_engine.get('text_primary')};
                border: 1px solid {theme_engine.get('border_color')}; border-radius: 8px;
                font-size: 13px;
            }}
            QPushButton:hover {{ background-color: {theme_engine.get('card_hover')}; border-color: {theme_engine.get('accent_color')}; }}
        """

    # ─── 交互 ──────────────────────────────────────────

    def _apply_preset(self, name: str):
        """应用预设：高亮卡片 + 同步滑块"""
        self._current_preset = name
        for card_name, card in self._cards.items():
            card.setChecked(card_name == name)
            card.setStyleSheet(self._card_qss(card_name == name))
        data = self._presets.get(name)
        if not data:
            return
        for dim in _DIM_ORDER:
            self._sliders[dim].blockSignals(True)
            self._sliders[dim].setValue(int(float(data.get(dim, 0.5)) * 100))
            self._sliders[dim].blockSignals(False)
            self._value_labels[dim].setText(f"{self._sliders[dim].value() / 100.0:.1f}")

    def _on_slider_changed(self, dim: str, value: int):
        """自定义微调：取消预设选中态，标记为自定义"""
        self._value_labels[dim].setText(f"{value / 100.0:.1f}")
        # 任一滑块被拖动 → 不再是标准预设
        if self._current_preset != "自定义":
            self._current_preset = "自定义"
            for card_name, card in self._cards.items():
                card.setChecked(False)
                card.setStyleSheet(self._card_qss(False))

    def _current_vector(self) -> dict:
        return {dim: self._sliders[dim].value() / 100.0 for dim in _DIM_ORDER}

    def _on_save(self):
        """保存性格种子 + 初始背景记忆"""
        if self._db is None:
            self.accept()
            return
        vector = self._current_vector()
        preset_name = self._current_preset
        # 自定义时沿用最后选择预设的风格描述作为基础
        style = ""
        if preset_name in self._presets:
            style = self._presets[preset_name]["style_description"]
        elif self._presets:
            # 自定义：用"默认"预设的风格描述兜底
            style = self._presets.get("默认", {}).get("style_description", "")

        apply_personality(_DB_PATH, vector, style, preset_name,
                          self._identity_key)
        self.accept()

    def _on_skip(self):
        """跳过：直接关闭，不写入（首次启动 fallback 用默认值）"""
        self.accept()

    # ─── 窗口管理 ──────────────────────────────────────

    def center_on_parent(self):
        parent = self._parent_window
        if parent and parent.isVisible():
            pc = parent.mapToGlobal(parent.rect().center())
            self.move(pc.x() - self.width() // 2, pc.y() - self.height() // 2)
        else:
            from PySide6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                self.move(geo.center().x() - self.width() // 2,
                          geo.center().y() - self.height() // 2)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._on_skip()
