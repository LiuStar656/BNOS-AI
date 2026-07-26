"""知识关联图谱 — 基于力导向布局的 QGraphicsView 可视化组件

Usage:
    kg = KnowledgeGraph()
    kg.load_data(entries, edges, threshold=0.6)
    kg.show()
"""

from __future__ import annotations

import math

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QToolTip,
    QWidget,
)

# ─── 力导向布局参数 ─────────────────────────────────
REPULSION = 8000.0    # 斥力常数
ATTRACTION = 0.01     # 弹簧常数
DAMPING = 0.85        # 阻尼系数
AREA_WIDTH = 800
AREA_HEIGHT = 600
NODE_RADIUS = 20
FONT_SIZE = 9

# ─── 分类颜色 ───────────────────────────────────────
CATEGORY_COLORS: dict[str, str] = {
    "user_facts":          "#4CAF50",
    "background":          "#4CAF50",
    "preference":          "#8BC34A",
    "fixed_cognition":     "#2196F3",
    "self_info":           "#03A9F4",
    "self_cognition":      "#9C27B0",
    "other_cognition":     "#FF9800",
    "feelings":            "#E91E63",
    "event_summary":       "#795548",
    "long_term_memory":    "#607D8B",
}


def _color_for(category: str) -> str:
    return CATEGORY_COLORS.get(category, "#999999")


# ════════════════════════════════════════════════════════════════

class GraphNode(QGraphicsEllipseItem):
    """知识节点 — 圆形+标签"""

    def __init__(self, entry: dict, radius: int = NODE_RADIUS):
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.entry = entry
        self._radius = radius
        self._is_hovered = False

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(10)

        # 填充色
        c = _color_for(entry.get("category", ""))
        self._brush = QBrush(QColor(c))
        self.setBrush(self._brush)

        # 边框
        self._pen_default = QPen(QColor(c).darker(130), 1.5)
        self._pen_hover = QPen(QColor(c).lighter(150), 3)
        self._pen_selected = QPen(QColor("#1a73e8"), 3)
        self.setPen(self._pen_default)

        # 标签文字
        self._label = QGraphicsSimpleTextItem(self)
        self._label.setFont(QFont("Microsoft YaHei", FONT_SIZE))
        text = entry.get("content", "")[:16].replace("\n", " ")
        self._label.setText(text)
        self._label.setBrush(QColor("#333"))
        self._label.setPos(-self._label.boundingRect().width() / 2, radius + 2)

        # 高亮圆环（仅在 hover 时显示）
        self._glow = QGraphicsEllipseItem(-radius - 4, -radius - 4,
                                          radius * 2 + 8, radius * 2 + 8, self)
        self._glow.setPen(QPen(Qt.PenStyle.NoPen))
        self._glow.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self._glow.setZValue(-1)
        self._glow.hide()

    @property
    def node_id(self):
        return f"{self.entry['table']}:{self.entry['id']}"

    def hoverEnterEvent(self, event):
        self._is_hovered = True
        self.setPen(self._pen_hover)
        # 高亮邻居边
        self._update_neighbor_edges(True)
        # 显示工具提示
        content = self.entry.get("content", "")
        if len(content) > 100:
            content = content[:100] + "..."
        QToolTip.showText(
            event.screenPos(),
            f"[{self.entry.get('category', '')}]\n{content}",
            self,
        )
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._is_hovered = False
        if not self.isSelected():
            self.setPen(self._pen_default)
        self._update_neighbor_edges(False)
        QToolTip.hideText()
        super().hoverLeaveEvent(event)

    def _update_neighbor_edges(self, highlight: bool):
        """更新邻居边的样式"""
        for edge in self.scene().edges(self):
            edge.set_highlight(highlight)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            # 移动时更新关联的边
            for edge in self.scene().edges(self):
                edge.adjust()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            # 选中节点时高亮
            self.setPen(self._pen_selected)
            self._update_neighbor_edges(True)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if not self._is_hovered and not self.isSelected():
            self.setPen(self._pen_default)

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # 阴影
        painter.setPen(Qt.PenStyle.NoPen)
        shadow = QColor(0, 0, 0, 40)
        painter.setBrush(shadow)
        painter.drawEllipse(QRectF(-self._radius + 2, -self._radius + 2,
                                   self._radius * 2, self._radius * 2))
        # 本体
        painter.setPen(self.pen())
        gradient = QLinearGradient(-self._radius, -self._radius,
                                   self._radius, self._radius)
        base = self._brush.color()
        gradient.setColorAt(0, base.lighter(130))
        gradient.setColorAt(1, base)
        painter.setBrush(gradient)
        painter.drawEllipse(self.rect())

        # 选中圆圈
        if self.isSelected():
            painter.setPen(QPen(QColor("#1a73e8"), 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(self.rect().adjusted(-3, -3, 3, 3))


class GraphEdge(QGraphicsLineItem):
    """关联边 — 宽度随相似度变化"""

    def __init__(self, source: GraphNode, target: GraphNode, weight: float):
        super().__init__()
        self._source = source
        self._target = target
        self._weight = weight
        self._highlighted = False

        width = max(0.5, weight * 4)
        alpha = max(40, int(weight * 200))
        self._color = QColor(100, 100, 100, alpha)
        self._highlight_color = QColor(26, 115, 232, 200)

        self.setPen(QPen(self._color, width))
        self.setZValue(1)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.adjust()

    def adjust(self):
        if self._source is None or self._target is None:
            return
        self.setLine(
            self._source.pos().x(), self._source.pos().y(),
            self._target.pos().x(), self._target.pos().y(),
        )

    def set_highlight(self, on: bool):
        self._highlighted = on
        if on:
            self.setPen(QPen(self._highlight_color, self._weight * 5 + 1))
        else:
            width = max(0.5, self._weight * 4)
            self.setPen(QPen(self._color, width))


# ════════════════════════════════════════════════════════════════

class GraphScene(QGraphicsScene):
    """图谱场景 — 管理节点和边的图结构"""

    def edges(self, node: GraphNode | None = None) -> list[GraphEdge]:
        """返回场景中所有边，或连接到指定节点的边"""
        all_edges = [item for item in self.items() if isinstance(item, GraphEdge)]
        if node is None:
            return all_edges
        return [
            e for e in all_edges
            if e._source is node or e._target is node
        ]

    def nodes(self) -> list[GraphNode]:
        return [item for item in self.items() if isinstance(item, GraphNode)]

    def node_by_id(self, node_id: str) -> GraphNode | None:
        for n in self.nodes():
            if n.node_id == node_id:
                return n
        return None

    # ─── 力导向布局 ─────────────────────────────

    def run_force_layout(self, iterations: int = 100):
        """力导向布局：斥力(全对) + 弹簧(边)"""
        nodes = self.nodes()
        if len(nodes) < 2:
            return

        # 收集边的连接关系
        edge_pairs = set()
        for e in self.edges():
            edge_pairs.add((id(e._source), id(e._target)))

        positions = {id(n): [n.pos().x(), n.pos().y()] for n in nodes}
        velocities = {id(n): [0.0, 0.0] for n in nodes}

        for iteration in range(iterations):
            temp = max(1.0, 10.0 * (1 - iteration / iterations))
            forces = {id(n): [0.0, 0.0] for n in nodes}

            for i, ni in enumerate(nodes):
                nid_i = id(ni)
                xi, yi = positions[nid_i]
                for j in range(i + 1, len(nodes)):
                    nj = nodes[j]
                    nid_j = id(nj)
                    xj, yj = positions[nid_j]
                    dx = xj - xi
                    dy = yj - yi
                    dist = math.hypot(dx, dy) + 1
                    # 斥力
                    fx = REPULSION * dx / (dist * dist)
                    fy = REPULSION * dy / (dist * dist)
                    forces[nid_i][0] -= fx
                    forces[nid_i][1] -= fy
                    forces[nid_j][0] += fx
                    forces[nid_j][1] += fy

            for edge in self.edges():
                sid = id(edge._source)
                tid = id(edge._target)
                dx = positions[tid][0] - positions[sid][0]
                dy = positions[tid][1] - positions[sid][1]
                dist = math.hypot(dx, dy) + 1
                fx = ATTRACTION * dist * dx / dist
                fy = ATTRACTION * dist * dy / dist
                forces[sid][0] += fx
                forces[sid][1] += fy
                forces[tid][0] -= fx
                forces[tid][1] -= fy

            # 更新位置
            for n in nodes:
                nid = id(n)
                velocities[nid][0] = (velocities[nid][0] + forces[nid][0]) * DAMPING
                velocities[nid][1] = (velocities[nid][1] + forces[nid][1]) * DAMPING
                speed = math.hypot(velocities[nid][0], velocities[nid][1])
                if speed > temp:
                    scale = temp / speed
                    velocities[nid][0] *= scale
                    velocities[nid][1] *= scale
                positions[nid][0] += velocities[nid][0]
                positions[nid][1] += velocities[nid][1]

            # 每 10 次迭代同步一次位置到图形项
            if iteration % 10 == 0:
                for n in nodes:
                    nid = id(n)
                    n.setPos(positions[nid][0], positions[nid][1])

        # 最终同步
        for n in nodes:
            nid = id(n)
            n.setPos(positions[nid][0], positions[nid][1])

        # 更新所有边的位置
        for e in self.edges():
            e.adjust()

    def reset_positions(self):
        """在圆形上初始化节点位置"""
        nodes = self.nodes()
        if not nodes:
            return
        angle_step = 2 * math.pi / len(nodes)
        r = min(AREA_WIDTH, AREA_HEIGHT) * 0.35
        cx, cy = AREA_WIDTH / 2, AREA_HEIGHT / 2
        for i, n in enumerate(nodes):
            angle = i * angle_step
            n.setPos(cx + r * math.cos(angle), cy + r * math.sin(angle))


# ════════════════════════════════════════════════════════════════

class KnowledgeGraph(QGraphicsView):
    """知识关联图谱主控件"""

    node_clicked = Signal(object)  # entry dict

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._scene = GraphScene(self)
        self.setScene(self._scene)
        self.setSceneRect(0, 0, AREA_WIDTH, AREA_HEIGHT)

        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QColor("#f8f9fa"))

        # 缩放状态
        self._zoom = 1.0
        self._min_zoom = 0.2
        self._max_zoom = 3.0

        # 节点点击检测
        self._scene.selectionChanged.connect(self._on_selection_changed)

    # ─── 数据加载 ─────────────────────────────

    def load_data(self, entries: list[dict], edges: list[dict], threshold: float = 0.6):
        """加载知识条目和预计算边，构建图谱。

        Args:
            entries: [{id, table, category, content}, ...]
            edges: [{source, target, weight}, ...] (AAA 预计算)
            threshold: 相似度阈值（过滤低质量边）
        """
        self._scene.clear()
        if not entries or not edges:
            return

        # 保存原始数据供阈值过滤
        self._all_entries = entries
        self._all_edges = edges

        # 创建节点
        nodes: list[GraphNode] = []
        for entry in entries:
            node = GraphNode(entry)
            self._scene.addItem(node)
            nodes.append(node)

        # 按阈值添加边
        for e in edges:
            weight = e.get("weight", 0)
            if weight >= threshold:
                s = e["source"]
                t = e["target"]
                if s < len(nodes) and t < len(nodes):
                    edge = GraphEdge(nodes[s], nodes[t], weight)
                    self._scene.addItem(edge)

        # 布局
        self._scene.reset_positions()
        self._scene.run_force_layout(iterations=80)
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = 1.0

    def rebuild_edges(self, entries: list[dict], edges: list[dict], threshold: float):
        """阈值变化时重建边（无 numpy 依赖）"""
        self._scene.clear()
        if not entries or not edges:
            return

        self._all_entries = entries
        self._all_edges = edges

        nodes: list[GraphNode] = []
        for entry in entries:
            node = GraphNode(entry)
            self._scene.addItem(node)
            nodes.append(node)

        for e in edges:
            weight = e.get("weight", 0)
            if weight >= threshold:
                s = e["source"]
                t = e["target"]
                if s < len(nodes) and t < len(nodes):
                    edge = GraphEdge(nodes[s], nodes[t], weight)
                    self._scene.addItem(edge)

        self._scene.run_force_layout(iterations=30)

    # ─── 交互 ─────────────────────────────────

    def _on_selection_changed(self):
        selected = self._scene.selectedItems()
        for item in selected:
            if isinstance(item, GraphNode):
                self.node_clicked.emit(item.entry)
                return

    def wheelEvent(self, event):
        """滚轮缩放"""
        delta = event.angleDelta().y()
        factor = 1.1 if delta > 0 else 0.9
        new_zoom = self._zoom * factor
        if self._min_zoom <= new_zoom <= self._max_zoom:
            self._zoom = new_zoom
            self.scale(factor, factor)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        """双击重置视图"""
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = 1.0
        super().mouseDoubleClickEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        """绘制网格背景"""
        super().drawBackground(painter, rect)
        painter.setPen(QPen(QColor(0, 0, 0, 12), 1))
        grid_size = 40
        left = int(rect.left()) // grid_size * grid_size
        top = int(rect.top()) // grid_size * grid_size
        x = left
        while x < rect.right():
            painter.drawLine(x, int(rect.top()), x, int(rect.bottom()))
            x += grid_size
        y = top
        while y < rect.bottom():
            painter.drawLine(int(rect.left()), y, int(rect.right()), y)
            y += grid_size
