"""知识库面板 — 数据浏览 + 记忆图谱双视图"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
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


# ─── 路径 ─────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_PATH = str(_PROJECT_ROOT / "nodes" / "shared" / "chatbot.db")
_GRAPH_PATH = str(_PROJECT_ROOT / "nodes" / "shared" / "knowledge_graph.json")

# ─── 数据库表分类标签 ─────────────────────────
TABLE_LABELS: dict[str, str] = {
    "all":               "全部",
    "diaries":           "日记",
    "event_summary":     "事件摘要",
    "feelings":          "情感",
    "fixed_cognition":   "固定认知",
    "long_term_memory":  "长期记忆（归档）",
    "mood_trend":        "情感趋势",
    "other_cognition":   "对用户认知",
    "retrieval_log":     "检索日志",
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
            # self_cognition / other_cognition 只显示最新 1 条
            limit = 1 if tname in ("self_cognition", "other_cognition") else 200
            table_rows = conn.execute(
                f"SELECT * FROM [{tname}] ORDER BY id DESC LIMIT {limit}"
            ).fetchall()
            cols = [c[1] for c in conn.execute("PRAGMA table_info([{}])".format(tname)).fetchall()]
            for row in table_rows:
                record = dict(zip(cols, row))
                # 提取主显示内容
                content = (
                    record.get("content")
                    or record.get("summary")
                    or record.get("mood", "") + ": " + record.get("thought", "")
                    or str(record.get("key", "")) + " = " + str(record.get("value", ""))
                    or record.get("dominant_mood", "")
                    or record.get("keywords", "")
                    or ""
                )
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

        self._build_ui()
        self._load_data()

        # 自动刷新（60s，仅检测 mtime，数据未变时跳过）
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._auto_refresh_check)
        self._refresh_timer.start(60000)

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
        """数据浏览视图"""
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        txt = colors["text_primary"]

        # 分类筛选按钮组
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(6)
        self._filter_btns: dict[str, QPushButton] = {}
        # 从实际数据库读取表名，动态生成筛选按钮
        try:
            conn = sqlite3.connect(_DB_PATH)
            db_tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name"
            ).fetchall()]
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
                    background: transparent; border: 1px solid {colors['border_color']};
                    border-radius: 12px; padding: 3px 10px;
                    font-size: 11px; color: {txt};
                }}
                QPushButton:checked {{
                    background: {colors.get('accent_color', '#1a73e8')};
                    color: white; border: none;
                }}
                QPushButton:hover {{
                    background: {colors.get('bg_chat', '#eee')};
                }}
            """)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, c=cat: self._filter_by(c))
            filter_layout.addWidget(btn)
            self._filter_btns[cat] = btn
        # 手动刷新按钮
        refresh_btn = QPushButton("刷新")
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: 1px solid {colors['accent_color']};
                border-radius: 12px; padding: 3px 12px;
                font-size: 11px; color: {colors['accent_color']};
            }}
            QPushButton:hover {{
                background: {colors['accent_color']}; color: white;
            }}
        """)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self._load_data)
        filter_layout.addWidget(refresh_btn)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        # 卡片列表（滚动）
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

        # 控制栏
        control_row = QHBoxLayout()
        control_row.setSpacing(12)

        # ── 力尺度滑块 (控制力导向布局的力度) ──
        slider_label = QLabel("力尺度:")
        slider_label.setStyleSheet(f"font-size: 12px; color: {colors['text_primary']}80;")
        control_row.addWidget(slider_label)

        self._force_slider = QSlider(Qt.Orientation.Horizontal)
        self._force_slider.setRange(10, 500)  # 0.10x ~ 5.00x
        self._force_slider.setValue(100)
        self._force_slider.setFixedWidth(180)
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
        control_row.addWidget(self._force_slider)
        control_row.addWidget(self._force_value)

        control_row.addStretch()

        count_label = QLabel("双击节点定位 · 双击空白重置 | 滚轮平移 | Ctrl+滚轮缩放 | 空格+左键拖拽 | 拖拽节点松手后自动聚合")
        count_label.setStyleSheet(f"font-size: 11px; color: {colors['text_primary']}60;")
        control_row.addWidget(count_label)

        layout.addLayout(control_row)

        # 图谱组件
        self._graph = KnowledgeGraph()
        self._graph.node_double_clicked.connect(self._on_graph_node_double_clicked)
        self._graph.force_scale_changed.connect(self._on_graph_force_scale_changed)
        layout.addWidget(self._graph, 1)

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
        """刷新 UI（需在主线程调用）"""
        if not self._db_entries and not self._graph_entries:
            self._count_label.setText("暂无数据")
            return

        # 构建状态信息
        info_parts = ["{} 条数据".format(len(self._db_entries))]
        if self._graph_entries:
            info_parts.append("{} 个图谱节点".format(len(self._graph_entries)))
            total_edges = sum(
                1 for e in self._graph_edges
                if e.get("weight", 0) >= LINK_THRESHOLD
            )
            info_parts.append("{} 条边".format(total_edges))
        self._count_label.setText(" · ".join(info_parts))

        self._rebuild_cards()
        self._rebuild_graph()

    def _refresh_db_ui(self):
        """仅刷新数据库卡片"""
        if not self._db_entries:
            self._count_label.setText("暂无数据")
            return

        info_parts = ["{} 条数据".format(len(self._db_entries))]
        if self._graph_entries:
            info_parts.append("{} 个图谱节点".format(len(self._graph_entries)))
        self._count_label.setText(" · ".join(info_parts))

        self._rebuild_cards()

        # 如果在图谱 Tab，也需要刷新图谱
        if self._tab_bar.currentIndex() == 1:
            self._rebuild_graph()

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
        if table_name == "all":
            return self._db_entries
        return [e for e in self._db_entries if e.get("table") == table_name]

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
        if index == 1:
            self._rebuild_graph()

    def refresh_theme(self):
        """主题刷新（供外部调用）"""
        pass
