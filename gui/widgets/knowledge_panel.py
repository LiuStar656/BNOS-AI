"""知识库面板 — 数据浏览 + 记忆图谱双视图 + 时间区间筛选"""

from __future__ import annotations

import datetime
import json
import sqlite3
import threading
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from gui.core.config import AppConfig
from gui.widgets.knowledge_graph import KnowledgeGraph, _node_id_for_entry, LINK_THRESHOLD
from gui.widgets.mood_chart import MoodChartWidget


# ─── 路径 ─────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_PATH = str(_PROJECT_ROOT / "nodes" / "shared" / "chatbot.db")
_GRAPH_PATH = str(_PROJECT_ROOT / "nodes" / "shared" / "knowledge_graph.json")

# 不参与知识面板展示的表（目前无；location_history 已纳入展示）
_IGNORED_TABLES: set[str] = set()

# ─── 数据库表分类标签 ─────────────────────────
TABLE_LABELS: dict[str, str] = {
    "all":               "全部",
    "diaries":           "日记",
    "event_summary":     "事件摘要",
    "feelings":          "想法",
    "fixed_cognition":   "固定认知",
    "location_history":  "定位历史",
    "long_term_memory":  "长期记忆（归档）",
    "mood_trend":        "情感趋势",
    "mood_value":        "情绪值",
    "other_cognition":   "对用户认知",
    "personality_seed":  "性格种子",
    "self_cognition":    "自我认知",
    "self_info":         "自我信息",
    "user_facts":        "记忆归档",
    "user_messages":     "对话记录",
}


def _read_db() -> list[dict]:
    """直接从 SQLite 数据库读取所有表的数据"""
    conn = sqlite3.connect(_DB_PATH)
    rows = []
    try:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name"
        ).fetchall()
        for (tname,) in tables:
            # 跳过非记忆表（目前为空；location_history 已纳入展示）
            if tname in _IGNORED_TABLES:
                continue
            cols = [c[1] for c in conn.execute("PRAGMA table_info([{}])".format(tname)).fetchall()]
            # 跳过既无 id 列也无 identity_key 列的表
            if "id" not in cols and "identity_key" not in cols:
                continue
            # self_cognition / other_cognition 只显示最新 1 条
            limit = 1 if tname in ("self_cognition", "other_cognition") else 200
            if "id" in cols:
                table_rows = conn.execute(
                    f"SELECT * FROM [{tname}] ORDER BY id DESC LIMIT {limit}"
                ).fetchall()
            else:
                # 无 id 列的表（如 personality_seed 主键为 identity_key）
                table_rows = conn.execute(
                    f"SELECT * FROM [{tname}] LIMIT {limit}"
                ).fetchall()
            for row in table_rows:
                record = dict(zip(cols, row))
                # 提取主显示内容
                if tname == "location_history":
                    # 定位历史表无 content 字段，直接走专门格式化
                    # （避免通用提取把 mood+thought 拼成 ":" 占位）
                    content = _format_location_content(record)
                elif tname == "personality_seed":
                    # 角色种子表：字段均为数值/描述，无 content 字段
                    content = _format_personality_seed(record)
                else:
                    content = (
                        record.get("content")
                        or record.get("summary")
                        or _format_mood_thought(record)
                        or str(record.get("key", "")) + " = " + str(record.get("value", ""))
                        or record.get("dominant_mood", "")
                        or record.get("keywords", "")
                        or ""
                    )
                # v1.6: JSON 包装的消息（如 {"data_type":"text","content":"..."}）
                # 解析出真实内容；content 为空则整条跳过（旧版误存过空 JSON）
                if isinstance(content, str) and content.lstrip().startswith("{"):
                    try:
                        inner = json.loads(content)
                        if isinstance(inner, dict) and "content" in inner:
                            content = inner.get("content") or ""
                    except Exception:
                        pass
                if record.get("mood_value") is not None:
                    # 情绪值记录：心情 + 数值 + 调整量
                    src_mood = record.get("source_mood") or "情绪"
                    adjust = float(record.get("adjustment", 0) or 0)
                    content = (f"{src_mood} {float(record['mood_value']):+.2f}"
                               f"（调整 {adjust:+.2f}）")
                if record.get("period"):
                    content = f"[{record['period']}] {record.get('dominant_mood', '')} ({record.get('avg_mood_value', '')})"
                if record.get("keywords"):
                    content = f"{record['keywords']} → {record.get('result_count', 0)} 条结果"
                if not content or (isinstance(content, str) and not content.strip()):
                    continue
                rows.append({
                    "table": tname,
                    "id": record.get("id", 0),
                    "content": str(content)[:500],
                    "created_at": record.get("created_at", ""),
                    "extra": _format_extra(tname, record),
                })
    finally:
        conn.close()
    return rows


def _format_mood_thought(record: dict) -> str:
    """心情+想法安全拼接：任一段为空时只显示有内容的一段，避免 "开心:" 或 ":" 占位"""
    mood = (record.get("mood") or "").strip()
    thought = (record.get("thought") or "").strip()
    if mood and thought:
        return f"{mood}: {thought}"
    if mood:
        return mood
    if thought:
        return thought
    return ""


def _format_personality_seed(record: dict) -> str:
    """角色种子记录的可读内容（preset 名 + 风格描述 + 各维度数值）"""
    preset = (record.get("preset_name") or "").strip()
    style = (record.get("style_description") or "").strip()
    parts = []
    if preset:
        parts.append(preset)
    if style:
        parts.append(style)
    dims = []
    for k, label in (("warmth", "温暖"), ("playfulness", "俏皮"),
                     ("directness", "直率"), ("curiosity", "好奇")):
        v = record.get(k)
        if v is not None and str(v) not in ("", "None", "null", "0"):
            dims.append(f"{label}{v}")
    if dims:
        parts.append("，".join(dims))
    if not parts:
        ik = record.get("identity_key") or ""
        parts.append(f"角色种子（{ik}，未配置具体参数）")
    return " | ".join(parts)


def _format_location_content(record: dict) -> str:
    """定位历史记录的可读内容（街道/城市/精度/来源）"""
    parts = []
    if record.get("street"):
        parts.append(str(record["street"]))
    if record.get("district"):
        parts.append(str(record["district"]))
    city = record.get("city") or ""
    region = record.get("region") or ""
    if city:
        parts.append(str(city))
    if region:
        parts.append(str(region))
    if not parts:
        lat = record.get("latitude")
        lng = record.get("longitude")
        if lat is not None and lng is not None:
            parts.append(f"坐标 {float(lng):.4f}°E, {float(lat):.4f}°N")
    base = "，".join(parts) if parts else "未知位置"

    extra_parts = []
    acc = record.get("accuracy")
    if acc:
        extra_parts.append(f"精度 {float(acc):.0f}m")
    src = record.get("source")
    src_map = {
        "qt_gps": "GPS卫星", "qt_wifi": "Wi-Fi定位", "qt_cell": "基站定位",
        "qt_unknown": "系统定位", "ip": "IP定位", "cache": "缓存",
    }
    if src:
        extra_parts.append(src_map.get(src, src))
    if extra_parts:
        base += "（" + "，".join(extra_parts) + "）"
    return base


def _format_extra(table: str, record: dict) -> str:
    """提取额外信息（分类、角色、来源等）"""
    parts = []
    for key in ("category", "role", "source", "mood", "key"):
        val = record.get(key)
        if val:
            parts.append("{}={}".format(key, val))
    return " | ".join(parts) if parts else ""


def _read_graph() -> dict | None:
    """读取 knowledge_graph.json（AAA 预计算的图谱数据）"""
    p = Path(_GRAPH_PATH)
    if not p.exists() or p.stat().st_size == 0:
        return None
    try:
        data = json.loads(p.read_text("utf-8"))
        return {
            "entries": data.get("entries", []),
            "edges": data.get("edges", []),
        }
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════

class KnowledgePanel(QWidget):
    """知识库面板内容 — 数据浏览 + 记忆图谱双视图"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = AppConfig()
        colors = self._config.get_all_colors()
        p = self.palette()
        p.setColor(QPalette.Window, QColor(colors["bg_secondary"]))
        self.setPalette(p)
        self.setAutoFillBackground(True)

        self._db_entries: list[dict] = []
        self._graph_entries: list[dict] = []
        self._graph_edges: list[dict] = []
        self._graph_sim_matrix: list[list[float]] | None = None

        # 缓存检测：记录文件 mtime，避免重复加载
        self._graph_file_mtime: float = 0.0

        # v1.0: 时间筛选状态
        self._current_time_filter: str = "all"
        self._time_start: datetime.datetime | None = None
        self._time_end: datetime.datetime | None = None
        self._pending_time_start: datetime.datetime | None = None
        self._pending_time_end: datetime.datetime | None = None

        self._build_ui()
        self._load_data()

        # 自动刷新（10s，仅检测 mtime；情绪曲线 Tab 激活时额外刷新情绪数据）
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._auto_refresh_check)
        self._refresh_timer.start(10000)

        # v1.0: 防抖定时器（避免频繁重建图谱）
        self._filter_debounce_timer = QTimer(self)
        self._filter_debounce_timer.setSingleShot(True)
        self._filter_debounce_timer.timeout.connect(self._exec_pending_time_filter)

    def _build_ui(self):
        colors = self._config.get_all_colors()
        bg = colors["bg_secondary"]
        txt = colors["text_primary"]
        border = colors["border_color"]

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ─── Tab 栏 ──────────────────────────
        self._tab_bar = QTabBar()
        self._tab_bar.addTab("数据浏览")
        self._tab_bar.addTab("记忆图谱")
        self._tab_bar.addTab("情绪曲线")
        self._tab_bar.setStyleSheet(f"""
            QTabBar {{
                background: {bg};
                border: none;
                padding: 0;
            }}
            QTabBar::tab {{
                padding: 8px 20px;
                font-size: 13px;
                color: {txt}80;
                border: none;
                border-bottom: 2px solid transparent;
                background: transparent;
            }}
            QTabBar::tab:selected {{
                color: {txt};
                border-bottom: 2px solid {colors.get('accent_color', '#1a73e8')};
            }}
            QTabBar::tab:hover {{
                color: {txt};
            }}
        """)
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        main_layout.addWidget(self._tab_bar)

        # ─── 内容容器（QStackedWidget 的平替） ──
        self._content_stack = QWidget()
        self._content_layout = QVBoxLayout(self._content_stack)
        self._content_layout.setContentsMargins(12, 8, 12, 8)
        self._content_layout.setSpacing(8)

        # 视图 A: 卡片列表
        self._list_view = QWidget()
        self._build_list_view(self._list_view, colors)
        self._content_layout.addWidget(self._list_view)

        # 视图 B: 图谱（默认隐藏）
        self._graph_view = QWidget()
        self._build_graph_view(self._graph_view, colors)
        self._graph_view.hide()
        self._content_layout.addWidget(self._graph_view)

        # 视图 C: 情绪曲线（v2.0，默认隐藏）
        self._mood_view = QWidget()
        self._build_mood_view(self._mood_view, colors)
        self._mood_view.hide()
        self._content_layout.addWidget(self._mood_view)

        main_layout.addWidget(self._content_stack, 1)

        # ─── 底部信息栏 ───────────────────────
        bottom_bar = QWidget()
        bottom_bar.setStyleSheet(f"""
            background: {bg}; border-top: 1px solid {border}; padding: 4px;
        """)
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(12, 4, 12, 4)

        self._count_label = QLabel("加载中...")
        self._count_label.setStyleSheet(f"font-size: 12px; color: {txt}90;")
        bottom_layout.addWidget(self._count_label)

        bottom_layout.addStretch()

        refresh_btn = QPushButton("刷新")
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: {colors.get('accent_color', '#1a73e8')};
                border: none; border-radius: 4px; padding: 4px 14px;
                font-size: 12px; color: white;
            }}
            QPushButton:hover {{
                background: {colors.get('select_bg', '#1557b0')};
            }}
        """)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self._load_data)
        bottom_layout.addWidget(refresh_btn)

        main_layout.addWidget(bottom_bar)

    def _build_list_view(self, container, colors):
        """数据浏览视图（v1.5: 分类按钮左侧竖排）"""
        # 整体横向：左侧分类栏 + 右侧卡片列表
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        txt = colors["text_primary"]

        # ── 左侧分类栏（竖排，固定宽度）──
        side_bar = QWidget()
        side_bar.setFixedWidth(96)
        side_bar.setStyleSheet(
            f"background: {colors['bg_primary']};"
            f"border: 1px solid {colors['border_color']};"
            "border-radius: 6px;")
        side_layout = QVBoxLayout(side_bar)
        side_layout.setContentsMargins(6, 8, 6, 8)
        side_layout.setSpacing(4)

        self._filter_btns: dict[str, QPushButton] = {}
        # 从实际数据库读取表名，动态生成筛选按钮
        try:
            conn = sqlite3.connect(_DB_PATH)
            db_tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name"
            ).fetchall()]
            # 过滤非记忆表 + 无 id/identity_key 列的表（与 _read_db 保持一致）
            filtered = []
            for tname in db_tables:
                if tname in _IGNORED_TABLES:
                    continue
                cols = [c[1] for c in conn.execute(
                    f"PRAGMA table_info([{tname}])").fetchall()]
                if "id" in cols or "identity_key" in cols:
                    filtered.append(tname)
            db_tables = filtered
            conn.close()
        except Exception:
            db_tables = []
        categories = ["all"] + db_tables
        for cat in categories:
            btn = QPushButton(TABLE_LABELS.get(cat, cat))
            btn.setCheckable(True)
            btn.setChecked(cat == "all")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; border: none;
                    border-radius: 4px; padding: 6px 4px;
                    font-size: 12px; color: {txt};
                    text-align: left;
                }}
                QPushButton:checked {{
                    background: {colors.get('accent_color', '#1a73e8')};
                    color: white;
                }}
                QPushButton:hover {{
                    background: {colors.get('bg_chat', '#eee')};
                }}
            """)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, c=cat: self._filter_by(c))
            side_layout.addWidget(btn)
            self._filter_btns[cat] = btn

        side_layout.addStretch()

        # 手动刷新按钮（左侧底部）
        refresh_btn = QPushButton("刷新")
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: 1px solid {colors['accent_color']};
                border-radius: 4px; padding: 4px 8px;
                font-size: 12px; color: {colors['accent_color']};
            }}
            QPushButton:hover {{
                background: {colors['accent_color']}; color: white;
            }}
        """)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self._load_data)
        side_layout.addWidget(refresh_btn)

        layout.addWidget(side_bar)

        # ── 右侧卡片列表（滚动）──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollArea > QWidget > QWidget { background: transparent; }
        """)
        self._card_container = QWidget()
        self._card_layout = QVBoxLayout(self._card_container)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(6)
        self._card_layout.addStretch()
        scroll.setWidget(self._card_container)
        layout.addWidget(scroll, 1)

    def _build_graph_view(self, container, colors):
        """知识图谱视图"""
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # v1.0: ── 时间筛选控件 ──
        time_filter_row = QHBoxLayout()
        time_filter_row.setSpacing(6)

        time_label = QLabel("时间筛选:")
        time_label.setStyleSheet(f"font-size: 12px; color: {colors['text_primary']}80;")
        time_filter_row.addWidget(time_label)

        # 快捷选项按钮
        self._time_btns: dict[str, QPushButton] = {}
        for label, key in [("全部", "all"), ("今天", "today"),
                           ("近7天", "7d"), ("近30天", "30d")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(self._filter_btn_qss(colors))
            btn.clicked.connect(lambda checked, k=key: self._filter_by_time(k))
            time_filter_row.addWidget(btn)
            self._time_btns[key] = btn

        # 自定义范围按钮
        self._custom_btn = QPushButton("自定义 ▾")
        self._custom_btn.setCheckable(True)
        self._custom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._custom_btn.setStyleSheet(self._filter_btn_qss(colors))
        self._custom_btn.clicked.connect(self._toggle_custom_range)
        time_filter_row.addWidget(self._custom_btn)

        time_filter_row.addSpacing(12)

        # ── 力尺度滑块 (控制力导向布局的力度) ──
        slider_label = QLabel("力尺度:")
        slider_label.setStyleSheet(f"font-size: 12px; color: {colors['text_primary']}80;")
        time_filter_row.addWidget(slider_label)

        self._force_slider = QSlider(Qt.Orientation.Horizontal)
        self._force_slider.setRange(10, 500)  # 0.10x ~ 5.00x
        self._force_slider.setValue(100)
        self._force_slider.setFixedWidth(140)
        self._force_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 4px; background: {colors['border_color']};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                width: 14px; height: 14px; margin: -5px 0;
                background: {colors.get('accent_color', '#1a73e8')};
                border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {colors.get('accent_color', '#1a73e8')};
                border-radius: 2px;
            }}
        """)
        self._force_value = QLabel("1.00x")
        self._force_value.setStyleSheet(f"font-size: 12px; color: {colors['text_primary']};")
        self._force_slider.valueChanged.connect(self._on_force_changed)
        time_filter_row.addWidget(self._force_slider)
        time_filter_row.addWidget(self._force_value)

        time_filter_row.addStretch()
        layout.addLayout(time_filter_row)

        # v1.0: ── 自定义时间范围 UI（默认隐藏）──
        self._custom_range_widget = QWidget()
        custom_layout = QHBoxLayout(self._custom_range_widget)
        custom_layout.setContentsMargins(0, 2, 0, 4)
        custom_layout.setSpacing(8)

        custom_layout.addWidget(QLabel("从:"))
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDisplayFormat("yyyy-MM-dd")
        self._date_from.setDate(QDate.currentDate().addDays(-7))
        custom_layout.addWidget(self._date_from)

        custom_layout.addWidget(QLabel("到:"))
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDisplayFormat("yyyy-MM-dd")
        self._date_to.setDate(QDate.currentDate())
        custom_layout.addWidget(self._date_to)

        accent = colors.get("accent_color", "#1a73e8")
        apply_btn = QPushButton("应用")
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(f"""
            QPushButton {{
                background: {accent}; color: white;
                border: none; border-radius: 12px;
                padding: 3px 14px; font-size: 11px;
            }}
            QPushButton:hover {{ background: {colors.get('select_bg', '#1557b0')}; }}
        """)
        apply_btn.clicked.connect(self._apply_custom_range)
        custom_layout.addWidget(apply_btn)

        reset_btn = QPushButton("重置")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setStyleSheet(self._filter_btn_qss(colors))
        reset_btn.clicked.connect(self._reset_time_filter)
        custom_layout.addWidget(reset_btn)

        custom_layout.addStretch()
        self._custom_range_widget.hide()
        layout.addWidget(self._custom_range_widget)

        # 图谱组件
        self._graph = KnowledgeGraph()
        self._graph.node_double_clicked.connect(self._on_graph_node_double_clicked)
        self._graph.force_scale_changed.connect(self._on_graph_force_scale_changed)
        layout.addWidget(self._graph, 1)

    def _build_mood_view(self, container, colors):
        """情绪曲线视图（v2.0）"""
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        txt = colors["text_primary"]
        accent = colors.get("accent_color", "#1a73e8")

        # ── 顶部工具行：标题 + 范围切换按钮 + 导出 ──
        tool_row = QHBoxLayout()
        tool_row.setSpacing(6)

        title_label = QLabel("情绪趋势")
        title_label.setStyleSheet(f"font-size: 13px; font-weight: bold; color: {txt};")
        tool_row.addWidget(title_label)

        tool_row.addSpacing(10)

        # 范围切换按钮
        self._mood_btns: dict[str, QPushButton] = {}
        for label, key in [("最近50次", "50"), ("最近7天", "7d"),
                           ("最近30天", "30d"), ("全部", "all")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == "50")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(self._filter_btn_qss(colors))
            btn.clicked.connect(lambda checked, k=key: self._on_mood_mode_clicked(k))
            tool_row.addWidget(btn)
            self._mood_btns[key] = btn

        tool_row.addStretch()

        # 导出 PNG 按钮
        export_btn = QPushButton("导出 PNG")
        export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        export_btn.setStyleSheet(self._filter_btn_qss(colors))
        export_btn.clicked.connect(self._on_mood_export)
        tool_row.addWidget(export_btn)

        # 刷新按钮
        mood_refresh_btn = QPushButton("刷新")
        mood_refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mood_refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: {accent}; color: white;
                border: none; border-radius: 12px;
                padding: 3px 14px; font-size: 11px;
            }}
            QPushButton:hover {{ background: {colors.get('select_bg', '#1557b0')}; }}
        """)
        mood_refresh_btn.clicked.connect(self._reload_mood_chart)
        tool_row.addWidget(mood_refresh_btn)

        layout.addLayout(tool_row)

        # ── 图表组件 ──
        self._mood_chart = MoodChartWidget()
        layout.addWidget(self._mood_chart, 1)

    def _reload_mood_chart(self):
        """重新加载情绪曲线数据（主线程调用）"""
        if hasattr(self, "_mood_chart"):
            self._mood_chart.load_data(_DB_PATH, identity_key="gui:default")

    def _on_mood_mode_clicked(self, mode: str):
        """情绪曲线范围切换"""
        for key, btn in self._mood_btns.items():
            btn.setChecked(key == mode)
        if hasattr(self, "_mood_chart"):
            self._mood_chart.set_mode(mode)

    def _on_mood_export(self):
        """导出情绪曲线 PNG"""
        if hasattr(self, "_mood_chart"):
            self._mood_chart._on_export()

    @staticmethod
    def _filter_btn_qss(colors: dict) -> str:
        """筛选按钮统一 QSS"""
        accent = colors.get("accent_color", "#1a73e8")
        select_bg = colors.get("select_bg", "#1557b0")
        bg_chat = colors.get("bg_chat", "#eee")
        border = colors.get("border_color", "#d0d0d0")
        txt = colors.get("text_primary", "#333")
        return f"""
            QPushButton {{
                background: transparent; border: 1px solid {border};
                border-radius: 12px; padding: 3px 10px;
                font-size: 11px; color: {txt};
            }}
            QPushButton:checked {{
                background: {accent}; color: white; border: none;
            }}
            QPushButton:hover:!checked {{ background: {bg_chat}; }}
            QPushButton:pressed {{ background: {select_bg}; color: white; }}
        """

    # ─── 数据加载 ─────────────────────────────

    def _auto_refresh_check(self):
        """自动刷新检查：仅检测 mtime，数据未变时跳过"""
        try:
            p = Path(_GRAPH_PATH)
            if p.exists():
                current_mtime = p.stat().st_mtime
                if current_mtime != self._graph_file_mtime:
                    # 文件已更新，重新加载
                    self._load_data(force=True)
            # 情绪曲线 Tab 激活时刷新情绪数据（mood_value 每次对话都会写入）
            if hasattr(self, "_tab_bar") and self._tab_bar.currentIndex() == 2:
                self._reload_mood_chart()
        except Exception:
            pass

    def _load_data(self, force: bool = False):
        """异步加载数据库数据和图谱数据

        Args:
            force: 强制加载（忽略缓存检测）
        """
        # 缓存检测
        if not force:
            try:
                p = Path(_GRAPH_PATH)
                if p.exists():
                    current_mtime = p.stat().st_mtime
                    if current_mtime == self._graph_file_mtime:
                        # 图谱文件未变，仅更新数据库卡片
                        self._load_db_only()
                        return
            except Exception:
                pass

        def _load():
            self._db_entries = _read_db()
            graph = _read_graph()
            if graph:
                self._graph_entries = graph["entries"]
                self._graph_edges = graph["edges"]
                # 解析相似度矩阵 (扁平化 → 2D)
                sim_flat = graph.get("sim_matrix")
                if sim_flat:
                    n = len(self._graph_entries)
                    self._graph_sim_matrix = [
                        [float(sim_flat[i * n + j]) for j in range(n)]
                        for i in range(n)
                    ]
                else:
                    self._graph_sim_matrix = None
                try:
                    p = Path(_GRAPH_PATH)
                    if p.exists():
                        self._graph_file_mtime = p.stat().st_mtime
                except Exception:
                    pass

        threading.Thread(target=_load, daemon=True).start()
        QTimer.singleShot(300, self._refresh_ui)

    def _load_db_only(self):
        """仅加载数据库卡片（图谱数据不变时）"""
        def _load():
            self._db_entries = _read_db()
        threading.Thread(target=_load, daemon=True).start()
        QTimer.singleShot(300, self._refresh_db_ui)

    def _refresh_ui(self):
        """刷新 UI（需在主线程调用） — v1.0: 刷新后自动应用时间筛选"""
        if not self._db_entries and not self._graph_entries:
            self._count_label.setText("暂无数据")
            return

        # v1.0: 若有活跃的时间筛选，走时间过滤流程（否则保持全量）
        if self._time_start is not None and self._time_end is not None:
            self._exec_pending_time_filter_impl(self._time_start, self._time_end)
            return

        # 全量模式：默认统计 + 重建
        info_parts = ["{} 条数据".format(len(self._db_entries))]
        if self._graph_entries:
            info_parts.append("{} 个图谱节点".format(len(self._graph_entries)))
            total_edges = sum(
                1 for e in self._graph_edges
                if e.get("weight", 0) >= LINK_THRESHOLD
            )
            info_parts.append("{} 条边".format(total_edges))
        self._count_label.setText(" · ".join(info_parts) + " | 全部时间")

        self._rebuild_cards()
        self._rebuild_graph()

    def _refresh_db_ui(self):
        """仅刷新数据库卡片 — v1.0: 刷新后自动应用时间筛选"""
        if not self._db_entries:
            self._count_label.setText("暂无数据")
            return

        # v1.0: 若有活跃时间筛选 + 处于图谱 Tab → 重建带时间筛选的图谱
        if self._time_start is not None and self._time_end is not None:
            self._rebuild_cards()  # _filter_entries 会自动应用时间
            if self._tab_bar.currentIndex() == 1:
                self._rebuild_graph_with_filter(self._time_start, self._time_end)
            else:
                self._refresh_status_bar_with_time()
            return

        info_parts = ["{} 条数据".format(len(self._db_entries))]
        if self._graph_entries:
            info_parts.append("{} 个图谱节点".format(len(self._graph_entries)))
        self._count_label.setText(" · ".join(info_parts) + " | 全部时间")

        self._rebuild_cards()

        # 如果在图谱 Tab，也需要刷新图谱
        if self._tab_bar.currentIndex() == 1:
            self._rebuild_graph()

    def _refresh_status_bar_with_time(self):
        """仅刷新状态栏（不重建图谱），用于活跃时间筛选状态下的数据刷新"""
        # 估算图谱 entries 过滤后的数量
        if self._time_start and self._time_end:
            graph_filtered = [
                e for e in self._graph_entries
                if self._entry_in_time_range(e, self._time_start, self._time_end)
            ]
            self._update_status_bar(
                graph_filtered, self._time_start, self._time_end, "")
        else:
            self._update_status_bar(
                self._graph_entries, None, None, "")

    def _rebuild_cards(self):
        """重建数据浏览卡片"""
        # 清除旧卡片
        while self._card_layout.count() > 0:
            item = self._card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._card_layout.addStretch()

        current_filter = getattr(self, "_current_filter", "all")
        filtered = self._filter_entries(current_filter)

        for entry in filtered:
            card = self._create_card(entry)
            # 插入到 stretch 之前
            self._card_layout.insertWidget(self._card_layout.count() - 1, card)

    def _create_card(self, entry: dict) -> QWidget:
        """创建单条数据卡片"""
        colors = self._config.get_all_colors()
        table = entry.get("table", "")
        label = TABLE_LABELS.get(table, table)
        content = entry.get("content", "")
        extra = entry.get("extra", "")
        created_at = entry.get("created_at", "")
        if len(content) > 120:
            display_content = content[:120] + "..."
        else:
            display_content = content

        card = QWidget()
        card.setProperty("entry_id", _node_id_for_entry(entry))
        card.setStyleSheet(f"""
            QWidget {{
                background: {colors['bg_primary']};
                border: 1px solid {colors['border_color']};
                border-radius: 6px;
            }}
            QWidget#highlight {{
                border: 2px solid {colors.get('accent_color', '#1a73e8')};
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(4)

        cat_label = QLabel(label)
        cat_label.setStyleSheet(f"""
            font-size: 10px; color: {colors.get('accent_color', '#1a73e8')};
            font-weight: bold; border: none; background: transparent;
        """)
        card_layout.addWidget(cat_label)

        content_label = QLabel(display_content)
        content_label.setWordWrap(True)
        content_label.setStyleSheet(f"""
            font-size: 12px; color: {colors['text_primary']};
            border: none; background: transparent;
        """)
        card_layout.addWidget(content_label)

        # 底部：附加信息 + 时间
        if extra or created_at:
            info = "  ·  ".join(filter(None, [extra, created_at]))
            extra_label = QLabel(info)
            extra_label.setStyleSheet(f"""
                font-size: 10px; color: {colors['text_primary']}60;
                border: none; background: transparent;
            """)
            card_layout.addWidget(extra_label)

        return card

    def _filter_entries(self, table_name: str) -> list[dict]:
        """v1.0: 表筛选 + 时间筛选组合过滤"""
        # 1. 表过滤
        if table_name == "all":
            entries = list(self._db_entries)
        else:
            entries = [e for e in self._db_entries if e.get("table") == table_name]

        # 2. 时间过滤（仅当设置了时间范围时）
        if self._time_start is not None and self._time_end is not None:
            entries = [
                e for e in entries
                if self._entry_in_time_range(e, self._time_start, self._time_end)
            ]
        return entries

    def _filter_by(self, table_name: str):
        self._current_filter = table_name
        for cat, btn in self._filter_btns.items():
            btn.setChecked(cat == table_name)
        self._rebuild_cards()

    # ─── 图谱交互 ─────────────────────────────

    def _rebuild_graph(self):
        """重建图谱视图"""
        if self._graph_entries and self._graph_edges:
            self._graph.load_data(
                self._graph_entries, self._graph_edges,
                sim_matrix=self._graph_sim_matrix,
            )

    def _on_force_changed(self, value: int):
        """力尺度滑块变化时调整力的大小"""
        force = value / 100.0
        self._force_value.setText(f"{force:.2f}x")
        self._graph.set_force_scale(force)

    def _on_graph_force_scale_changed(self, scale: float):
        """图谱内部（Ctrl+滚轮）改变力尺度时同步滑块"""
        self._force_value.setText(f"{scale:.2f}x")
        self._force_slider.blockSignals(True)
        self._force_slider.setValue(int(scale * 100))
        self._force_slider.blockSignals(False)

    def _on_graph_node_double_clicked(self, entry: dict):
        """双击图谱节点 → 定位到数据源卡片位置"""
        table = entry.get("table", "")
        self._filter_by(table)
        self._tab_bar.setCurrentIndex(0)

        # 查找对应卡片并滚动定位
        target_id = _node_id_for_entry(entry)
        scroll_area = self._list_view.findChild(QScrollArea)
        if scroll_area is None:
            # 遍历列表视图寻找滚动区域
            for child in self._list_view.findChildren(QScrollArea):
                scroll_area = child
                break

        if scroll_area is not None:
            # 清除之前的高亮
            for i in range(self._card_layout.count()):
                item = self._card_layout.itemAt(i)
                if item and item.widget():
                    item.widget().setObjectName("")

            # 找到目标卡片
            for i in range(self._card_layout.count()):
                item = self._card_layout.itemAt(i)
                if item and item.widget():
                    card = item.widget()
                    if card.property("entry_id") == target_id:
                        card.setObjectName("highlight")
                        card.style().unpolish(card)
                        card.style().polish(card)
                        # 滚动到该卡片
                        scroll_area.ensureWidgetVisible(card, 50, 50)
                        break

    # ─── Tab 切换 ─────────────────────────────

    def _on_tab_changed(self, index: int):
        self._list_view.setVisible(index == 0)
        self._graph_view.setVisible(index == 1)
        self._mood_view.setVisible(index == 2)
        if index == 1:
            self._rebuild_graph()
        elif index == 2:
            # 切换 Tab 到"情绪曲线"时自动刷新
            self._reload_mood_chart()

    def refresh_theme(self):
        """主题刷新（供外部调用）"""
        pass

    # ════════════════════════════════════════════════════════════════
    #  v1.0: 时间区间筛选功能
    # ════════════════════════════════════════════════════════════════

    # ─── 快捷筛选入口 ──────────────────────────────────────

    def _filter_by_time(self, time_key: str):
        """按时间筛选（快捷方式）"""
        self._current_time_filter = time_key
        # 收起自定义 UI
        if hasattr(self, "_custom_range_widget"):
            self._custom_range_widget.hide()
        if hasattr(self, "_custom_btn"):
            self._custom_btn.setChecked(False)
        self._update_time_btn_styles()

        now = datetime.datetime.now()
        if time_key == "all":
            start, end = None, None
        elif time_key == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now
        elif time_key == "7d":
            start = now - datetime.timedelta(days=7)
            end = now
        elif time_key == "30d":
            start = now - datetime.timedelta(days=30)
            end = now
        else:
            start, end = None, None

        self._apply_time_filter(start, end)

    # ─── 自定义范围 UI ─────────────────────────────────────

    def _toggle_custom_range(self):
        show = self._custom_btn.isChecked()
        self._custom_range_widget.setVisible(show)
        if show:
            self._current_time_filter = "custom"
            self._update_time_btn_styles()
        else:
            self._reset_time_filter()

    def _apply_custom_range(self):
        start_qdate = self._date_from.date()
        end_qdate = self._date_to.date()
        if start_qdate > end_qdate:
            self._count_label.setText("⚠ 错误: 起始日期不能晚于结束日期")
            return
        start = datetime.datetime(
            start_qdate.year(), start_qdate.month(), start_qdate.day())
        end = datetime.datetime(
            end_qdate.year(), end_qdate.month(), end_qdate.day(), 23, 59, 59)
        self._apply_time_filter(start, end)

    def _reset_time_filter(self):
        if hasattr(self, "_date_from"):
            self._date_from.setDate(QDate.currentDate().addDays(-7))
        if hasattr(self, "_date_to"):
            self._date_to.setDate(QDate.currentDate())
        self._filter_by_time("all")

    def _update_time_btn_styles(self):
        for key, btn in self._time_btns.items():
            btn.setChecked(key == self._current_time_filter)

    # ─── 防抖执行 ──────────────────────────────────────────

    def _apply_time_filter(self, start, end):
        """执行时间过滤（带 250ms 防抖）"""
        self._pending_time_start = start
        self._pending_time_end = end
        self._filter_debounce_timer.start(250)

    def _exec_pending_time_filter(self):
        """防抖后实际执行的过滤逻辑"""
        start = self._pending_time_start
        end = self._pending_time_end
        self._time_start = start
        self._time_end = end
        self._exec_pending_time_filter_impl(start, end)

    def _exec_pending_time_filter_impl(self, start, end):
        """v1.0: 防抖后/数据刷新后共用的过滤逻辑实现"""
        # 数据浏览视图：刷新卡片
        self._rebuild_cards()

        # 图谱视图：重建 filtered entries / edges / sim_matrix
        if self._tab_bar.currentIndex() == 1:
            self._rebuild_graph_with_filter(start, end)
        else:
            # 不在图谱 Tab 时也刷新状态栏
            self._refresh_status_bar_with_time()

    # ─── 时间工具函数 ──────────────────────────────────────

    @staticmethod
    def _parse_datetime(date_str) -> datetime.datetime | None:
        """容错解析 created_at 字符串"""
        if not date_str:
            return None
        s = str(date_str).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
                    "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
            try:
                # 截取到 fmt 所需长度，避免尾部分秒字符不同
                head = s[:len(fmt) + 2].rstrip()
                return datetime.datetime.strptime(head, fmt)
            except ValueError:
                continue
        return None

    def _entry_in_time_range(self, entry: dict,
                             start: datetime.datetime,
                             end: datetime.datetime) -> bool:
        """单条条目是否在时间范围内（全模式无时间戳默认保留，有筛选默认排除）"""
        dt = self._parse_datetime(entry.get("created_at", ""))
        if dt is None:
            return start is None  # 时间格式异常：筛选时排除，all 模式保留
        return start <= dt <= end

    # ─── 图谱重建（时间过滤后） ────────────────────────────

    def _rebuild_graph_with_filter(self, start, end):
        """重建图谱视图（按时间过滤）"""
        # 1. entries 时间过滤
        if start is None or end is None:
            filtered_entries = list(self._graph_entries)
        else:
            filtered_entries = [
                e for e in self._graph_entries
                if self._entry_in_time_range(e, start, end)
            ]

        # 空结果处理
        if not filtered_entries:
            if start and end:
                msg = f"⚠ 所选时间范围（{start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}）内无记忆节点，建议扩大范围"
            else:
                msg = "暂无数据"
            self._count_label.setText(msg)
            self._graph.load_data([], [])
            return

        # 2. edges 索引重映射
        old_id_to_idx = {}
        for i, entry in enumerate(self._graph_entries):
            old_id_to_idx[_node_id_for_entry(entry)] = i

        new_id_to_idx = {}
        for i, entry in enumerate(filtered_entries):
            new_id_to_idx[_node_id_for_entry(entry)] = i

        filtered_edges = []
        for edge in self._graph_edges:
            s_old = edge.get("source", -1)
            t_old = edge.get("target", -1)
            if s_old < 0 or s_old >= len(self._graph_entries):
                continue
            if t_old < 0 or t_old >= len(self._graph_entries):
                continue
            s_entry = self._graph_entries[s_old]
            t_entry = self._graph_entries[t_old]
            s_id = _node_id_for_entry(s_entry)
            t_id = _node_id_for_entry(t_entry)
            if s_id not in new_id_to_idx or t_id not in new_id_to_idx:
                continue
            filtered_edges.append({
                "source": new_id_to_idx[s_id],
                "target": new_id_to_idx[t_id],
                "weight": edge.get("weight", 0),
            })

        # 3. sim_matrix 重建
        n = len(filtered_entries)
        if self._graph_sim_matrix is not None:
            new_sim = [[0.0] * n for _ in range(n)]
            for i in range(n):
                new_sim[i][i] = 1.0
            for edge in filtered_edges:
                s, t = edge["source"], edge["target"]
                w = edge["weight"]
                if 0 <= s < n and 0 <= t < n:
                    new_sim[s][t] = w
                    new_sim[t][s] = w
        else:
            new_sim = None

        # 4. 重新加载
        self._graph.load_data(filtered_entries, filtered_edges, sim_matrix=new_sim)

        # 5. 边界提示 + 更新状态栏
        if len(filtered_entries) < 5:
            tip = "⚠ 节点过少，建议扩大时间范围 | "
        elif len(filtered_entries) > 500:
            tip = "⚠ 节点较多，建议缩小时间范围 | "
        else:
            tip = ""
        self._update_status_bar(filtered_entries, start, end, tip)

    # ─── 状态栏更新 ──────────────────────────────────────

    def _update_status_bar(self, graph_entries, start, end, prefix: str = ""):
        """更新底部状态栏：显示节点数 / 表来源统计 / 时间范围"""
        # 表来源统计（图谱 entries）
        table_counts: dict[str, int] = {}
        for entry in graph_entries:
            table = entry.get("table", "unknown")
            table_counts[table] = table_counts.get(table, 0) + 1
        stats_parts = [
            f"{table}({count})" for table, count in
            sorted(table_counts.items(), key=lambda x: -x[1])
        ]

        # 时间范围文本
        if start and end:
            time_range = (f"筛选自: {start.strftime('%Y-%m-%d')} ~ "
                          f"{end.strftime('%Y-%m-%d')}")
        else:
            time_range = "全部时间"

        total = len(graph_entries)
        node_info = f"显示: {total} 个节点"
        if total > 0 and stats_parts:
            node_info += f" | 来源: {', '.join(stats_parts[:3])}"

        # 数据浏览卡片数量（应用时间 + 表筛选后）
        current_filter = getattr(self, "_current_filter", "all")
        cards = self._filter_entries(current_filter)
        card_info = f" · {len(cards)} 条卡片数据"

        self._count_label.setText(
            f"{prefix}{node_info}{card_info} | {time_range}")
