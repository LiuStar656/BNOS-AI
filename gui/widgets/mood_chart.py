"""情绪曲线图组件 — QPainter 自绘折线图（零额外依赖，v2.0）

数据源：`mood_value` 表（逐次情绪记录）。
- X 轴：时间（最近 50 次 / 最近 7 天 / 最近 30 天 / 全部）
- Y 轴：情绪值 [-1.0, 1.0]
- 正面区域半透明绿色填充，负面区域半透明红色填充
- y=0 虚线基准线
- 鼠标悬停显示详情（时间、情绪值、心情描述）
- 滚轮切换时间范围，右键导出 PNG
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QMenu, QWidget

from gui.core.config import AppConfig


class MoodChartWidget(QWidget):
    """情绪曲线图组件（QPainter 自绘，零依赖）"""

    # 时间范围模式 → 显示标签
    MODES: dict[str, str] = {
        "50": "最近 50 次",
        "7d": "最近 7 天",
        "30d": "最近 30 天",
        "all": "全部",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = AppConfig()
        self._mood_data: list[dict] = []  # [{mood_value, source_mood, created_at}]
        self._mode = "50"
        self._hover_index: int | None = None
        self._db_path: str = ""
        self._identity_key: str = "gui:default"

        self.setMinimumHeight(240)
        self.setMouseTracking(True)  # 悬停检测

    # ─── 公共 API ──────────────────────────────────────────

    def load_data(self, db_path: str, identity_key: str = "gui:default",
                  mode: str | None = None) -> None:
        """从 DB 加载情绪数据并刷新绘制"""
        if mode:
            self._mode = mode
        self._db_path = db_path
        self._identity_key = identity_key
        self._mood_data = self._fetch(db_path, identity_key, self._mode)
        self._hover_index = None
        self.update()

    def set_mode(self, mode: str) -> None:
        """切换时间范围模式并刷新"""
        if mode not in self.MODES:
            return
        self._mode = mode
        if self._db_path:
            self._mood_data = self._fetch(self._db_path, self._identity_key, mode)
            self._hover_index = None
            self.update()

    def current_mode(self) -> str:
        return self._mode

    def export_png(self, path: str) -> None:
        """导出当前图表为 PNG"""
        self.grab().save(path)

    # ─── 数据读取 ──────────────────────────────────────────

    @staticmethod
    def _fetch(db_path: str, identity_key: str, mode: str) -> list[dict]:
        """从 mood_value 表读取情绪记录（时间升序）"""
        try:
            conn = sqlite3.connect(db_path)
            try:
                if mode == "50":
                    rows = conn.execute(
                        "SELECT mood_value, source_mood, created_at FROM mood_value "
                        "WHERE identity_key=? ORDER BY id DESC LIMIT 50",
                        (identity_key,),
                    ).fetchall()
                    rows = list(reversed(rows))
                elif mode == "7d":
                    rows = conn.execute(
                        "SELECT mood_value, source_mood, created_at FROM mood_value "
                        "WHERE identity_key=? AND created_at >= datetime('now','localtime','-7 days') "
                        "ORDER BY id ASC",
                        (identity_key,),
                    ).fetchall()
                elif mode == "30d":
                    rows = conn.execute(
                        "SELECT mood_value, source_mood, created_at FROM mood_value "
                        "WHERE identity_key=? AND created_at >= datetime('now','localtime','-30 days') "
                        "ORDER BY id ASC",
                        (identity_key,),
                    ).fetchall()
                else:  # all
                    rows = conn.execute(
                        "SELECT mood_value, source_mood, created_at FROM mood_value "
                        "WHERE identity_key=? ORDER BY id ASC",
                        (identity_key,),
                    ).fetchall()
            finally:
                conn.close()
            return [
                {"mood_value": float(r[0]), "source_mood": r[1] or "", "created_at": r[2] or ""}
                for r in rows
            ]
        except Exception:
            return []

    # ─── 绘制 ──────────────────────────────────────────────

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self._mood_data:
            self._draw_empty(painter)
            return

        rect = self.rect().adjusted(8, 8, -8, -8)
        # 图表区域：左侧留 Y 轴标签，底部留 X 轴标签
        chart = QRectF(rect.left() + 46, rect.top() + 14,
                       rect.width() - 46 - 12, rect.height() - 14 - 30)

        colors = self._config.get_all_colors()
        txt_color = QColor(colors.get("text_primary", "#333333"))
        grid_color = QColor(colors.get("border_color", "#d0d0d0"))
        grid_color.setAlpha(120)

        painter.setFont(QFont("Microsoft YaHei", 8))

        self._draw_grid(painter, chart, rect, txt_color, grid_color)
        self._draw_area_fill(painter, chart)
        self._draw_mood_line(painter, chart, txt_color)
        self._draw_baseline(painter, chart, grid_color)
        self._draw_axis_labels(painter, chart, rect, txt_color)
        self._draw_hover(painter, chart, txt_color)

    def _draw_empty(self, painter: QPainter):
        """无数据时的空状态提示"""
        colors = self._config.get_all_colors()
        txt = QColor(colors.get("text_primary", "#333333"))
        txt.setAlpha(140)
        painter.setFont(QFont("Microsoft YaHei", 10))
        painter.setPen(txt)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                         "暂无情绪记录\n（AI 开始对话后自动生成）")

    def _draw_grid(self, painter: QPainter, chart: QRectF, rect: QRectF,
                   txt_color: QColor, grid_color: QColor):
        """绘制水平网格线 + Y 轴刻度标签"""
        for i in range(5):  # -1.0, -0.5, 0.0, 0.5, 1.0
            y_val = 1.0 - i * 0.5
            y = chart.top() + chart.height() * (i / 4)
            painter.setPen(QPen(grid_color, 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(chart.left(), y), QPointF(chart.right(), y))
            painter.setPen(txt_color)
            painter.drawText(QRectF(rect.left(), y - 8, 42, 16),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                             f"{y_val:.1f}")

    def _xy(self, idx: int, chart: QRectF) -> QPointF:
        """数据点索引 → 像素坐标"""
        n = len(self._mood_data)
        x = chart.center().x() if n == 1 else chart.left() + chart.width() * idx / (n - 1)
        val = max(-1.0, min(1.0, self._mood_data[idx]["mood_value"]))
        y = chart.top() + chart.height() * (1.0 - (val + 1.0) / 2.0)
        return QPointF(x, y)

    def _zero_y(self, chart: QRectF) -> float:
        """情绪值 0 对应的像素 Y 坐标"""
        return chart.top() + chart.height() * 0.5

    def _draw_area_fill(self, painter: QPainter, chart: QRectF):
        """绘制正面（绿）/ 负面（红）半透明面积填充"""
        n = len(self._mood_data)
        if n == 0:
            return
        zero_y = self._zero_y(chart)

        # 拆分成正面/负面多边形顶点序列（跨越 0 线时插入交点）
        pos_pts: list[QPointF] = []
        neg_pts: list[QPointF] = []

        def _interpolate(p1: QPointF, v1: float, p2: QPointF, v2: float) -> QPointF:
            """返回折线段与 y=0 线的交点"""
            if v2 == v1:
                return QPointF(p2.x(), zero_y)
            t = (0.0 - v1) / (v2 - v1)
            return QPointF(p1.x() + (p2.x() - p1.x()) * t, zero_y)

        for i in range(n):
            v = max(-1.0, min(1.0, self._mood_data[i]["mood_value"]))
            p = self._xy(i, chart)
            if i == 0:
                (pos_pts if v >= 0 else neg_pts).append(p)
                continue
            v_prev = max(-1.0, min(1.0, self._mood_data[i - 1]["mood_value"]))
            p_prev = self._xy(i - 1, chart)
            if (v_prev >= 0) != (v >= 0):
                inter = _interpolate(p_prev, v_prev, p, v)
                pos_pts.append(inter)
                neg_pts.append(inter)
            (pos_pts if v >= 0 else neg_pts).append(p)

        green = QColor("#4caf50")
        red = QColor("#f44336")
        painter.setPen(Qt.PenStyle.NoPen)
        for pts, color in ((pos_pts, green), (neg_pts, red)):
            if not pts:
                continue
            poly = QPolygonF(pts)
            poly.append(QPointF(pts[-1].x(), zero_y))
            poly.append(QPointF(pts[0].x(), zero_y))
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 36))
            painter.drawPolygon(poly)

    def _draw_mood_line(self, painter: QPainter, chart: QRectF, txt_color: QColor):
        """绘制情绪折线 + 数据点"""
        n = len(self._mood_data)
        path = QPainterPath()
        for i in range(n):
            p = self._xy(i, chart)
            if i == 0:
                path.moveTo(p)
            else:
                path.lineTo(p)
        accent = QColor(self._config.get_all_colors().get("accent_color", "#1a73e8"))
        painter.setPen(QPen(accent, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        # 数据点
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            p = self._xy(i, chart)
            painter.setBrush(accent)
            painter.drawEllipse(p, 2.5, 2.5)

    def _draw_baseline(self, painter: QPainter, chart: QRectF, grid_color: QColor):
        """绘制 y=0 虚线基准线"""
        zero_y = self._zero_y(chart)
        painter.setPen(QPen(grid_color, 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(chart.left(), zero_y), QPointF(chart.right(), zero_y))

    def _draw_axis_labels(self, painter: QPainter, chart: QRectF, rect: QRectF,
                          txt_color: QColor):
        """绘制 X 轴时间标签（首/中/尾）"""
        n = len(self._mood_data)
        painter.setPen(txt_color)
        painter.setFont(QFont("Microsoft YaHei", 8))
        if n == 1:
            labels = [(0, self._mood_data[0]["created_at"])]
        else:
            labels = [
                (0, self._mood_data[0]["created_at"]),
                (n // 2, self._mood_data[n // 2]["created_at"]),
                (n - 1, self._mood_data[-1]["created_at"]),
            ]
        for idx, ts in labels:
            ts_str = self._fmt_time(ts)
            x = chart.left() + chart.width() * idx / (n - 1)
            align = Qt.AlignmentFlag.AlignHCenter
            if idx == 0:
                align |= Qt.AlignmentFlag.AlignLeft
            elif idx == n - 1:
                align |= Qt.AlignmentFlag.AlignRight
            painter.drawText(
                QRectF(x - 50, chart.bottom() + 6, 100, 18), align, ts_str)

        # 底部模式说明
        painter.setPen(txt_color)
        painter.setFont(QFont("Microsoft YaHei", 8))
        painter.drawText(
            rect, Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight,
            f"当前范围: {self.MODES.get(self._mode, self._mode)}")

    def _draw_hover(self, painter: QPainter, chart: QRectF, txt_color: QColor):
        """绘制悬停数据点详情"""
        if self._hover_index is None:
            return
        idx = self._hover_index
        if idx < 0 or idx >= len(self._mood_data):
            return
        item = self._mood_data[idx]
        p = self._xy(idx, chart)
        accent = QColor(self._config.get_all_colors().get("accent_color", "#1a73e8"))
        # 高亮数据点
        painter.setPen(QPen(accent, 2))
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(p, 4, 4)

        # 详情框
        val = item["mood_value"]
        lines = [
            self._fmt_time(item["created_at"]),
            f"情绪值: {val:+.2f}",
        ]
        if item["source_mood"]:
            lines.append(f"心情: {item['source_mood']}")
        width = max(painter.fontMetrics().horizontalAdvance(l) for l in lines) + 16
        height = len(lines) * 16 + 10
        box_x = p.x() + 12
        if box_x + width > self.width() - 8:
            box_x = p.x() - 12 - width
        box_y = p.y() - height / 2
        box_y = max(4, min(box_y, self.height() - height - 4))
        box_rect = QRectF(box_x, box_y, width, height)

        painter.setPen(QPen(QColor("#d0d0d0"), 1))
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawRoundedRect(box_rect, 4, 4)
        painter.setPen(txt_color)
        painter.setFont(QFont("Microsoft YaHei", 8))
        for i, line in enumerate(lines):
            painter.drawText(
                QRectF(box_x + 8, box_y + 5 + i * 16, width - 16, 16),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, line)

    @staticmethod
    def _fmt_time(ts: str) -> str:
        """格式化时间为 MM-DD HH:MM，解析失败原样返回"""
        if not ts:
            return "--"
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                    "%Y/%m/%d %H:%M:%S"):
            try:
                return datetime.strptime(str(ts)[:len(fmt)].strip(), fmt).strftime("%m-%d %H:%M")
            except ValueError:
                continue
        return str(ts)[:16]

    # ─── 交互 ──────────────────────────────────────────────

    def mouseMoveEvent(self, event):
        """悬停检测：找到最近的数据点"""
        if not self._mood_data:
            return
        rect = self.rect().adjusted(8, 8, -8, -8)
        chart = QRectF(rect.left() + 46, rect.top() + 14,
                       rect.width() - 46 - 12, rect.height() - 14 - 30)
        n = len(self._mood_data)
        x = event.position().x()
        if x < chart.left() or x > chart.right():
            self._set_hover(None)
            return
        idx = round((x - chart.left()) / chart.width() * (n - 1))
        idx = max(0, min(n - 1, idx))
        self._set_hover(idx)

    def leaveEvent(self, event):
        self._set_hover(None)
        super().leaveEvent(event)

    def _set_hover(self, idx: int | None):
        if idx != self._hover_index:
            self._hover_index = idx
            self.update()

    def wheelEvent(self, event):
        """滚轮切换时间范围（向上更精细，向下更宏观）"""
        order = ["50", "7d", "30d", "all"]
        cur = order.index(self._mode) if self._mode in order else 0
        if event.angleDelta().y() > 0:
            nxt = max(0, cur - 1)
        else:
            nxt = min(len(order) - 1, cur + 1)
        if nxt != cur:
            self.set_mode(order[nxt])

    def contextMenuEvent(self, event):
        """右键菜单：切换范围 / 导出 PNG"""
        menu = QMenu(self)
        for key, label in self.MODES.items():
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(key == self._mode)
            act.triggered.connect(lambda checked=False, k=key: self.set_mode(k))
        menu.addSeparator()
        export_act = menu.addAction("导出 PNG...")
        export_act.triggered.connect(self._on_export)
        menu.exec(event.globalPos())

    def _on_export(self):
        """导出 PNG（打开保存对话框）"""
        from PySide6.QtWidgets import QFileDialog
        from datetime import datetime
        default_name = f"情绪曲线_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出情绪曲线", default_name, "PNG 图片 (*.png)")
        if path:
            self.export_png(path)
