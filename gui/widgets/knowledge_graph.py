"""记忆图谱 — 相似度分段力导向布局

力模型基于余弦相似度分段:
  >= 0.7 : 高度同义 → 强吸引 (弹簧力, 拖拽联动)
  0.4~0.7: 弱相关   → 轻微斥力
  < 0.4  : 几乎无关 → 强斥力 (保证节点不会重叠)

Usage:
    kg = KnowledgeGraph()
    kg.load_data(entries, edges, sim_matrix)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
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

# ─── 画布参数 ─────────────────────────────────
AREA_WIDTH = 1500
AREA_HEIGHT = 1200
NODE_RADIUS = 8
FONT_SIZE = 9
HOVER_THRESHOLD = 150

# ─── 相似度分段阈值 ─────────────────────────
LINK_THRESHOLD = 0.75     # S >= 0.75: 强相关, 聚合引力
REPEL_THRESHOLD = 0.45    # S <= 0.45: 无关, 互斥斥力
# 0.45 < S < 0.75: 弱相关, 自由松弛 (仅防碰撞)

# ─── 物理参数 ─────────────────────────────────
FORCE_SCALE_BASE = 1.0       # 基准力尺度 L
ATTRACT_TARGET_DIST = 35.0   # 强关联平衡距离 D_target (L=1 时的值)
ATTRACT_TARGET_MIN = 25.0    # 平衡距离下限 (力尺度最小时, 防止贴死)
ATTRACT_TARGET_MAX = 120.0   # 平衡距离上限 (力尺度最大时, 防止过散)
REPEL_RADIUS = 120.0         # 无关节点斥力生效半径 R
BASE_MIN_DIST = 20.0         # 全局防重叠最小距离
FREEZE_FRAMES = 50           # 拖拽松手后冻结帧数 (更长, 平滑过渡)
DAMPING = 0.88               # 阻尼 (保留 88% 速度)
MAX_SPEED = 40.0             # 最大单帧速度
CONVERGENCE_ENERGY = 0.15    # 收敛判定 (总动能)
GRAVITY_STRENGTH = 0.002    # 中心重力 (极弱, 仅防飞散)

# ─── 视觉主题 ─────────────────────────────────
BG_COLOR = "#2b2b2b"
NODE_COLOR = "#a0a8b8"
NODE_COLOR_HOVER = "#d0d8e8"
NODE_COLOR_SELECTED = "#ffffff"
EDGE_COLOR = "#606878"
EDGE_HIGHLIGHT = "#ffffff"
TEXT_COLOR = "#d0d8e8"
LINK_COLOR = "#4a9eff"  # 联动跟随连线颜色


def _node_id_for_entry(entry: dict) -> str:
    return f"{entry.get('table', '')}:{entry.get('id', id(entry))}"


# ════════════════════════════════════════════════════════════════
# 物理引擎
# ════════════════════════════════════════════════════════════════

@dataclass
class NodeState:
    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0


class ForceEngine:
    """三层力引擎: 强相关聚合 / 无关互斥 / 弱相关自由松弛

    S >= 0.75: 聚合引力 F = L * S * (D - D_target)
    S <= 0.45: 互斥斥力 F = L * (1-S) * max(0, (R-D)/R)
    0.45 < S < 0.75: 仅防碰撞 (D < base_min_dist 时微弱推开)
    """

    def __init__(self, width: float = AREA_WIDTH, height: float = AREA_HEIGHT):
        self._width = width
        self._height = height
        self._cx = width / 2
        self._cy = height / 2
        self._states: list[NodeState] = []
        self._sim_matrix: list[list[float]] = []
        self._n = 0
        self._force_scale = 1.0
        self._converged = False
        self._total_energy = float("inf")
        self._freeze_counter = 0

    def setup(self, n_nodes: int, sim_matrix: list[list[float]]):
        self._n = n_nodes
        self._sim_matrix = sim_matrix
        self._states = []
        cx, cy = self._cx, self._cy
        for i in range(n_nodes):
            # 所有节点从同一点(画布中心)生成, 位置不再随机散布.
            # 完全重合时节点对的方向向量为零向量(斥力为零), 必须给随机
            # 初速度冲量打破对称, 之后斥力/引力接管 → 从中心自然弹开.
            angle = random.uniform(0, 2 * math.pi)
            speed = random.uniform(1.0, 2.0)
            self._states.append(NodeState(
                x=cx, y=cy,
                vx=speed * math.cos(angle),
                vy=speed * math.sin(angle),
            ))
        self._converged = False
        self._total_energy = float("inf")
        self._freeze_counter = 0

    def set_force_scale(self, scale: float):
        self._force_scale = max(0.1, min(5.0, scale))
        self._converged = False
        self._freeze_counter = 0

    @property
    def converged(self) -> bool:
        return self._converged

    @property
    def total_energy(self) -> float:
        return self._total_energy

    def step(self, dt: float = 1.0) -> list[NodeState]:
        n = self._n
        if n == 0:
            return []
        sim = self._sim_matrix
        L = self._force_scale
        cx, cy = self._cx, self._cy

        # ── 拖拽松手冻结: 这段时间不施加力, 保持位置 ──
        if self._freeze_counter > 0:
            self._freeze_counter -= 1
            if self._freeze_counter <= 0:
                self._converged = False
            return self._states

        fx = [0.0] * n
        fy = [0.0] * n

        # ── 三层作用力 ──
        for i in range(n):
            si = self._states[i]
            sim_i = sim[i]
            for j in range(i + 1, n):
                sj = self._states[j]
                S = sim_i[j]

                dx = sj.x - si.x
                dy = sj.y - si.y
                dist = math.sqrt(dx * dx + dy * dy)
                dist = max(dist, 0.01)
                nx, ny = dx / dist, dy / dist

                if S >= LINK_THRESHOLD:
                    # ── 强相关: 聚合引力 ──
                    # 平衡距离随力尺度 L 缩放: L 大 → 吸引节点保持更远距离,
                    # 避免聚合后贴得太近 (L=1 时 = 35px, 默认行为不变)
                    attract_target = max(ATTRACT_TARGET_MIN,
                                         min(ATTRACT_TARGET_MAX, ATTRACT_TARGET_DIST * L))
                    displacement = dist - attract_target
                    force = L * S * displacement * 0.03
                    fx[i] += force * nx
                    fy[i] += force * ny
                    fx[j] -= force * nx
                    fy[j] -= force * ny

                elif S <= REPEL_THRESHOLD:
                    # ── 无关: 互斥斥力 ──
                    # 斥力半径随力尺度放大 (L=1 时 = REPEL_RADIUS=120, 默认行为不变;
                    # L 大 → 斥力范围广 → 节点散得更开; L 小 → 范围窄 → 聚拢)
                    repel_radius = min(REPEL_RADIUS * L, self._width * 0.5)
                    if dist < repel_radius:
                        ratio = (repel_radius - dist) / repel_radius
                        repel_strength = L * (1.0 - S) * ratio * ratio
                        force = repel_strength * 8.0
                        fx[i] -= force * nx
                        fy[i] -= force * ny
                        fx[j] += force * nx
                        fy[j] += force * ny

                else:
                    # ── 弱相关: 仅全局防碰撞 ──
                    if dist < BASE_MIN_DIST:
                        force = L * 1.0 * (BASE_MIN_DIST - dist) / BASE_MIN_DIST
                        fx[i] -= force * nx
                        fy[i] -= force * ny
                        fx[j] += force * nx
                        fy[j] += force * ny

        # ── 中心重力 (与力尺度 L 成反比) ──
        # L 大 → 斥力强、范围广 + 重力弱 → 节点散得很开;
        # L 小 → 斥力弱、范围窄 + 重力强 → 节点聚向中心.
        # 若重力也同比例缩放 L, 所有力同比例变化, 平衡布局不变 → 力尺度调了没效果.
        k_gravity = GRAVITY_STRENGTH / L
        for i in range(n):
            s = self._states[i]
            fx[i] += k_gravity * (cx - s.x)
            fy[i] += k_gravity * (cy - s.y)

        # ── 积分 ──
        total_ke = 0.0
        for i in range(n):
            s = self._states[i]
            s.vx = (s.vx + fx[i] * dt) * DAMPING
            s.vy = (s.vy + fy[i] * dt) * DAMPING

            speed = math.sqrt(s.vx * s.vx + s.vy * s.vy)
            if speed > MAX_SPEED:
                s.vx = s.vx / speed * MAX_SPEED
                s.vy = s.vy / speed * MAX_SPEED

            s.x += s.vx * dt
            s.y += s.vy * dt

            margin = 30
            if s.x < margin:
                s.x = margin
                s.vx *= -0.5
            elif s.x > self._width - margin:
                s.x = self._width - margin
                s.vx *= -0.5
            if s.y < margin:
                s.y = margin
                s.vy *= -0.5
            elif s.y > self._height - margin:
                s.y = self._height - margin
                s.vy *= -0.5

            total_ke += s.vx * s.vx + s.vy * s.vy

        self._total_energy = total_ke

        if self._total_energy < CONVERGENCE_ENERGY:
            self._converged = True

        return self._states

    def freeze_drag_release(self):
        """拖拽松手: 冻结所有节点速度, 用当前位置作为新起点"""
        self._freeze_counter = FREEZE_FRAMES
        self._converged = False
        # 将所有节点速度清零, 位置设为当前值 (防止弹回)
        for s in self._states:
            s.vx = 0.0
            s.vy = 0.0


# ════════════════════════════════════════════════════════════════

class GraphNode(QGraphicsEllipseItem):
    """知识节点 — 单击显示文字, 双击定位数据源"""

    def __init__(self, entry: dict, radius: int = NODE_RADIUS, degree: int = 0):
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self.entry = entry
        self._radius = radius
        self._degree = degree
        self._is_hovered = False
        self._is_follower = False

        self._base_scale = 1.0 + 0.08 * degree

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setZValue(10)

        self._brush = QBrush(QColor(NODE_COLOR))
        self.setBrush(self._brush)

        self._pen_default = QPen(QColor(NODE_COLOR).darker(150), 1.5)
        self._pen_hover = QPen(QColor(NODE_COLOR_HOVER), 3)
        self._pen_selected = QPen(QColor(NODE_COLOR_SELECTED), 3)
        self._pen_follower = QPen(QColor(LINK_COLOR), 2, Qt.PenStyle.DashLine)
        self.setPen(self._pen_default)

        # 文字标签: 默认隐藏, 选中/单击时显示
        self._label = QGraphicsSimpleTextItem(self)
        self._label.setFont(QFont("Microsoft YaHei", FONT_SIZE))
        text = self._truncate_text(entry.get("content", ""), 15)
        self._label.setText(text)
        self._label.setBrush(QColor(TEXT_COLOR))
        self._label.setPos(-self._label.boundingRect().width() / 2, radius + 4)
        self._label.setVisible(False)

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        """截取前 max_chars 个字符, 超出用省略号"""
        clean = text.replace("\n", " ").strip()
        if len(clean) <= max_chars:
            return clean
        return clean[:max_chars] + "..."

    def show_label(self):
        if self._label is not None:
            try:
                self._label.setVisible(True)
            except RuntimeError:
                self._label = None

    def hide_label(self):
        if self._label is not None:
            try:
                self._label.setVisible(False)
            except RuntimeError:
                self._label = None

    @property
    def node_id(self):
        return _node_id_for_entry(self.entry)

    @property
    def base_scale(self) -> float:
        return self._base_scale

    @property
    def is_follower(self) -> bool:
        return self._is_follower

    def set_follower(self, on: bool):
        self._is_follower = on
        self.update()

    def hoverEnterEvent(self, event):
        self._is_hovered = True
        self.update()
        self._update_neighbor_edges(True)
        content = self.entry.get("content", "")
        if len(content) > 100:
            content = content[:100] + "..."
        QToolTip.showText(event.screenPos(), f"[{self.entry.get('category', '')}]\n{content}")
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._is_hovered = False
        self.update()
        self._update_neighbor_edges(False)
        if not self.isSelected():
            self.setScale(self._base_scale)
        QToolTip.hideText()
        super().hoverLeaveEvent(event)

    def _update_neighbor_edges(self, highlight: bool):
        for edge in self.scene().edges(self):
            edge.set_highlight(highlight)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for edge in self.scene().edges(self):
                edge.adjust()
        elif change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            self.update()
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.update()
            self._update_neighbor_edges(True)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.update()

    def mouseDoubleClickEvent(self, event):
        """双击: 通知视图定位到数据源"""
        self.scene().double_click_node(self)
        super().mouseDoubleClickEvent(event)

    def _current_pen(self) -> QPen:
        """根据当前状态计算正确的 pen — 单一真相源"""
        if self._is_follower:
            return self._pen_follower
        if self.isSelected():
            return self._pen_selected
        if self._is_hovered:
            return self._pen_hover
        return self._pen_default

    def paint(self, painter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        shadow = QColor(0, 0, 0, 60)
        painter.setBrush(shadow)
        painter.drawEllipse(QRectF(-self._radius + 2, -self._radius + 2,
                                   self._radius * 2, self._radius * 2))
        painter.setPen(self._current_pen())
        gradient = QLinearGradient(-self._radius, -self._radius,
                                   self._radius, self._radius)
        base = self._brush.color()
        gradient.setColorAt(0, base.lighter(120))
        gradient.setColorAt(1, base.darker(110))
        painter.setBrush(gradient)
        painter.drawEllipse(self.rect())
        if self.isSelected():
            painter.setPen(QPen(QColor(EDGE_HIGHLIGHT), 2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(self.rect().adjusted(-3, -3, 3, 3))


class GraphEdge(QGraphicsLineItem):
    """关联边 — 统一实线"""

    def __init__(self, source: GraphNode, target: GraphNode, weight: float,
                 start_idx: int = 0, end_idx: int = 0):
        super().__init__()
        self._source = source
        self._target = target
        self._weight = weight
        self._highlighted = False
        self.start_idx = start_idx  # 边两端节点在 entries 中的索引, 供流式显示判断
        self.end_idx = end_idx

        width = max(1.0, weight * 3)
        alpha = max(50, int(weight * 220))
        self._color = QColor(EDGE_COLOR)
        self._color.setAlpha(alpha)
        self._highlight_color = QColor(EDGE_HIGHLIGHT)
        self._pen_width = width

        pen = QPen(self._color, width, Qt.PenStyle.SolidLine)
        self.setPen(pen)
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
            self.setPen(QPen(self._highlight_color, self._pen_width + 1, Qt.PenStyle.SolidLine))
        else:
            self.setPen(QPen(self._color, self._pen_width, Qt.PenStyle.SolidLine))


class GraphScene(QGraphicsScene):
    def edges(self, node: GraphNode | None = None) -> list[GraphEdge]:
        all_edges = [item for item in self.items() if isinstance(item, GraphEdge)]
        if node is None:
            return all_edges
        return [e for e in all_edges if e._source is node or e._target is node]

    def nodes(self) -> list[GraphNode]:
        return [item for item in self.items() if isinstance(item, GraphNode)]

    def node_by_id(self, node_id: str) -> GraphNode | None:
        for n in self.nodes():
            if n.node_id == node_id:
                return n
        return None

    def double_click_node(self, node: GraphNode):
        """双击节点 — 通知 KnowledgeGraph"""
        self.parent()._on_node_double_clicked(node) if self.parent() else None


# ════════════════════════════════════════════════════════════════

class KnowledgeGraph(QGraphicsView):
    """记忆图谱 — 相似度分段力导向布局

    核心特性:
    1. 全相似度对力学: 基于 sim_matrix 计算所有节点对的吸引力/斥力
    2. 拖拽联动: 拖拽节点时, 高相似度(>=0.7)邻居跟随移动
    3. 一级联动: 只传播一级, 不链式传递
    4. 松手聚合: 松开鼠标后, 物理引擎自动平衡
    5. 稳定性: 子步长+阻尼+冻结机制, 无抖动
    """

    node_clicked = Signal(object)
    node_double_clicked = Signal(object)
    force_scale_changed = Signal(float)

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
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(QColor(BG_COLOR))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # 物理引擎
        self._engine = ForceEngine()
        self._force_scale = 1.0

        # 动画
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._physics_tick)

        # 加载动画定时器: 节点依次出现
        self._load_timer = QTimer(self)
        self._load_timer.timeout.connect(self._load_next_node)
        self._load_index = 0
        self._load_nodes: list[GraphNode] = []
        self._load_edges: list[GraphEdge] = []

        # 视图缩放 (Ctrl+滚轮)
        self._zoom = 1.0

        # 拖拽交互
        self._dragging_node: GraphNode | None = None
        self._drag_anchor_pos: QPointF | None = None  # 拖拽起点位置
        self._drag_followers: list[int] = []  # 联动跟随者索引列表
        self._drag_last_pos: QPointF | None = None  # 上一帧拖拽位置
        self._follower_origins: dict[int, QPointF] = {}  # 跟随者初始位置

        # 空格平移
        self._space_pan_active = False
        self._pan_start_pos: QPointF | None = None

        self._scene.selectionChanged.connect(self._on_selection_changed)

    # ─── 数据加载 ─────────────────────────────

    def load_data(
        self,
        entries: list[dict],
        edges: list[dict],
        sim_matrix: list[list[float]] | None = None,
    ):
        """加载数据 — 节点逐个加载, 每加载一个立即启动物理计算

        Args:
            entries: 知识条目
            edges: 高相似度边 (用于显示连线)
            sim_matrix: 全量相似度矩阵 (用于力引擎)
        """
        self._anim_timer.stop()
        self._load_timer.stop()
        self._scene.clear()
        if not entries:
            return

        self._entries = entries
        self._edges_raw = edges

        n = len(entries)

        # 构建相似度矩阵
        if sim_matrix is not None and len(sim_matrix) >= n:
            self._sim_matrix = sim_matrix
        else:
            self._sim_matrix = [[0.3] * n for _ in range(n)]
            for i in range(n):
                self._sim_matrix[i][i] = 1.0
            for e in edges:
                w = e.get("weight", 0.5)
                s, t = e["source"], e["target"]
                if s < n and t < n:
                    self._sim_matrix[s][t] = w
                    self._sim_matrix[t][s] = w

        # 计算度数
        degree_map: dict[str, int] = {}
        for entry in entries:
            degree_map[_node_id_for_entry(entry)] = 0
        for e in edges:
            s, t = e.get("source", -1), e.get("target", -1)
            if 0 <= s < n and 0 <= t < n:
                s_id = _node_id_for_entry(entries[s])
                t_id = _node_id_for_entry(entries[t])
                degree_map[s_id] = degree_map.get(s_id, 0) + 1
                degree_map[t_id] = degree_map.get(t_id, 0) + 1

        # 预创建所有节点 (隐藏, 位置在中心)
        all_nodes: list[GraphNode] = []
        cx, cy = AREA_WIDTH / 2, AREA_HEIGHT / 2
        for entry in entries:
            nid = _node_id_for_entry(entry)
            degree = degree_map.get(nid, 0)
            node = GraphNode(entry, degree=degree)
            node.setScale(0.01)
            node.setOpacity(0.0)
            # 先 addItem 再 setPos, 避免 scene 为 None
            self._scene.addItem(node)
            node.setPos(cx, cy)
            all_nodes.append(node)

        # 预创建所有边 (隐藏)
        display_edges = [e for e in edges if e.get("weight", 0) >= LINK_THRESHOLD]
        all_edges: list[GraphEdge] = []
        for e in display_edges:
            weight = e.get("weight", 0)
            s, t = e["source"], e["target"]
            if s < n and t < n:
                edge = GraphEdge(all_nodes[s], all_nodes[t], weight,
                                 start_idx=s, end_idx=t)
                edge.setOpacity(0.0)
                self._scene.addItem(edge)
                all_edges.append(edge)

        self._graph_nodes = all_nodes
        self._load_edges = all_edges

        # 初始化物理引擎 (全部节点, 但只有已显示的才会物理移动)
        self._engine.setup(n, self._sim_matrix)
        self._engine.set_force_scale(self._force_scale)

        # 重置视图
        self._zoom = 1.0
        self.resetTransform()
        self.centerOn(cx, cy)

        # 重置加载状态
        self._load_index = 0
        self._visible_count = 0

        # 启动物理引擎 (所有节点从中心+随机冲量起步, 边显示边被力推开)
        self._anim_timer.start(16)

        # 启动依次加载动画
        self._load_timer.start(100)  # 每 100ms 显示一个节点

    def _load_next_node(self):
        """依次显示下一个节点, 每加载一个立即让物理引擎参与"""
        if self._load_index >= len(self._graph_nodes):
            self._load_timer.stop()
            # 兜底: 正常流式逻辑已覆盖全部边, 这里仅保险
            for edge in self._load_edges:
                if edge.opacity() < 1.0:
                    edge.setOpacity(1.0)
            return

        node = self._graph_nodes[self._load_index]
        # 所有节点从画布中心(同一点)出现: 重置引擎状态到中心并赋予随机冲量,
        # 物理引擎的斥力/引力下一帧起立刻将其推开 — 从中心弹开的过程全程可见.
        # (未显示节点在引擎中已被演化, 显示时统一拉回中心, 保证"同坐标生成")
        state = self._engine._states[self._load_index]
        cx, cy = AREA_WIDTH / 2, AREA_HEIGHT / 2
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(2.0, 4.0)
        state.x, state.y = cx, cy
        state.vx, state.vy = speed * math.cos(angle), speed * math.sin(angle)
        node.setPos(cx, cy)
        # 弹出动画
        node.setOpacity(1.0)
        node.setScale(node.base_scale)
        self._visible_count += 1

        # 流式显示连线: 边两端节点都已显示时才浮现 (与节点生成节奏同步)
        for edge in self._load_edges:
            if edge.opacity() < 1.0:
                if edge.start_idx < self._visible_count and edge.end_idx < self._visible_count:
                    edge.setOpacity(1.0)

        self._load_index += 1
        if self._load_index > 10:
            self._load_timer.setInterval(50)

    def _physics_tick(self):
        """物理模拟帧 — 所有节点参与物理, 仅可见节点更新 Qt 位置"""
        if not hasattr(self, '_graph_nodes') or not self._graph_nodes:
            return

        # 拖拽时: 把 Qt 拖拽位置同步到引擎状态
        if self._dragging_node is not None:
            drag_idx = self._find_node_index(self._dragging_node)
            if drag_idx >= 0 and drag_idx < len(self._engine._states):
                drag_state = self._engine._states[drag_idx]
                drag_state.x = self._dragging_node.pos().x()
                drag_state.y = self._dragging_node.pos().y()
                drag_state.vx = 0.0
                drag_state.vy = 0.0

        # 所有节点都参与物理 (不锁定任何节点!)
        states = self._engine.step(dt=1.0)
        nodes = self._graph_nodes

        # 仅更新可见节点的 Qt 位置
        for i in range(self._visible_count):
            state = states[i]
            node = nodes[i]
            if self._dragging_node is not None and node is self._dragging_node:
                state.x = node.pos().x()
                state.y = node.pos().y()
                state.vx = 0.0
                state.vy = 0.0
            else:
                node.setPos(state.x, state.y)

        for edge in self._scene.edges():
            edge.adjust()

        if self._dragging_node is not None:
            self._process_drag_follow()
            return

        if self._visible_count >= len(nodes) and self._engine.converged:
            self._anim_timer.stop()

    def _process_drag_follow(self):
        """拖拽联动处理 — 被拖拽节点固定, 跟随者一起移动"""
        if self._dragging_node is None:
            return

        current_pos = self._dragging_node.pos()

        # 联动跟随: 高相似度邻居跟随移动 (一级)
        # 基于拖拽节点相对于锚点的偏移来移动跟随者
        origin = self._drag_anchor_pos
        if origin is None:
            return

        drag_offset = current_pos - origin
        max_offset = 200
        offset_len = math.hypot(drag_offset.x(), drag_offset.y())
        if offset_len > max_offset:
            ratio = max_offset / offset_len
            drag_offset = QPointF(drag_offset.x() * ratio, drag_offset.y() * ratio)

        for idx in self._drag_followers:
            if idx < len(self._graph_nodes):
                node = self._graph_nodes[idx]
                # 跟随者从各自锚点偏移相同量
                follower_origin = self._follower_origins.get(idx, node.pos())
                if idx not in self._follower_origins:
                    self._follower_origins[idx] = node.pos()
                    follower_origin = node.pos()

                new_pos = follower_origin + drag_offset
                node.setPos(new_pos)
                # 同步回物理引擎状态
                if idx < len(self._engine._states):
                    self._engine._states[idx].x = new_pos.x()
                    self._engine._states[idx].y = new_pos.y()
                    self._engine._states[idx].vx = 0.0
                    self._engine._states[idx].vy = 0.0

        # 更新边
        for edge in self._scene.edges():
            edge.adjust()

    def _find_node_index(self, node: GraphNode) -> int:
        for i, n in enumerate(self._graph_nodes):
            if n is node:
                return i
        return -1

    def _get_original_pos(self, idx: int) -> QPointF:
        """获取节点的目标位置 (来自物理引擎)"""
        if idx < len(self._engine._states):
            s = self._engine._states[idx]
            return QPointF(s.x, s.y)
        return QPointF(AREA_WIDTH / 2, AREA_HEIGHT / 2)

    def set_force_scale(self, scale: float):
        self._force_scale = max(0.1, min(5.0, scale))
        self._engine.set_force_scale(self._force_scale)
        self._anim_timer.start(16)
        self.force_scale_changed.emit(self._force_scale)

    # ─── 交互 ─────────────────────────────────

    def _on_selection_changed(self):
        selected = self._scene.selectedItems()
        selected_nodes = [item for item in selected if isinstance(item, GraphNode)]
        selected_ids = {id(n) for n in selected_nodes}

        for node in self._graph_nodes:
            if id(node) in selected_ids:
                node.show_label()
            else:
                node.hide_label()
            # 不需要手动 setPen — paint() 通过 _current_pen() 自动计算

    def _on_node_double_clicked(self, node: GraphNode):
        """双击节点 → 定位到数据源"""
        self.node_double_clicked.emit(node.entry)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pan_active = True
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pan_active = False
            self._pan_start_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            for node in self._graph_nodes:
                node.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._space_pan_active:
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                probe = item
                while probe is not None and not isinstance(probe, GraphNode):
                    probe = probe.parentItem()
                if isinstance(probe, GraphNode):
                    self._dragging_node = probe
                    self._drag_anchor_pos = probe.pos()
                    self._drag_last_pos = probe.pos()
                    dragging_idx = self._find_node_index(probe)
                    if dragging_idx >= 0 and dragging_idx < len(self._sim_matrix):
                        sim_row = self._sim_matrix[dragging_idx]
                        self._drag_followers = []
                        for j in range(len(sim_row)):
                            if j != dragging_idx and sim_row[j] >= LINK_THRESHOLD:
                                self._drag_followers.append(j)
                                if j < len(self._graph_nodes):
                                    self._graph_nodes[j].set_follower(True)
                    super().mousePressEvent(event)
                    return
            self._pan_start_pos = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            for node in self._graph_nodes:
                node.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            event.accept()
            return

        # 检测点击在节点上 → 预设置拖拽联动数据
        item = self.itemAt(event.position().toPoint())
        if item is not None:
            probe = item
            while probe is not None and not isinstance(probe, GraphNode):
                probe = probe.parentItem()
            if isinstance(probe, GraphNode):
                self._dragging_node = probe
                self._drag_anchor_pos = probe.pos()
                self._drag_last_pos = probe.pos()
                self._follower_origins.clear()

                dragging_idx = self._find_node_index(probe)
                if dragging_idx >= 0 and dragging_idx < len(self._sim_matrix):
                    sim_row = self._sim_matrix[dragging_idx]
                    self._drag_followers = []
                    for j in range(len(sim_row)):
                        if j != dragging_idx and sim_row[j] >= LINK_THRESHOLD:
                            self._drag_followers.append(j)
                            if j < len(self._graph_nodes):
                                self._graph_nodes[j].set_follower(True)
                            # 记录跟随者初始位置
                            self._follower_origins[j] = self._graph_nodes[j].pos()

                # 关键: 重启定时器 (收敛后已停止, 拖拽时需要持续物理模拟)
                self._anim_timer.start(16)

                # 关键: 调用 super 让 Qt 启动内置拖拽机制
                super().mousePressEvent(event)
                return

        # 点击空白区域: 清除选中 (在 super 之后, 防止被 Qt 内部逻辑覆盖)
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._scene.clearSelection()
            self._on_selection_changed()

    def mouseMoveEvent(self, event):
        if self._space_pan_active and self._pan_start_pos is not None:
            delta = event.position().toPoint() - self._pan_start_pos
            h_scroll = self.horizontalScrollBar()
            v_scroll = self.verticalScrollBar()
            h_scroll.setValue(h_scroll.value() - delta.x())
            v_scroll.setValue(v_scroll.value() - delta.y())
            self._pan_start_pos = event.position().toPoint()
            event.accept()
            return

        if not event.buttons():
            self._update_hover_scale(event)

        # 拖拽中: 记录当前位置供跟随逻辑使用
        if self._dragging_node is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._drag_last_pos = self._dragging_node.pos()

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pan_start_pos is not None and event.button() == Qt.MouseButton.LeftButton:
            self._pan_start_pos = None
            self.setCursor(
                Qt.CursorShape.OpenHandCursor
                if self._space_pan_active
                else Qt.CursorShape.ArrowCursor
            )
            for node in self._graph_nodes:
                node.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            event.accept()
            return

        if self._dragging_node is not None:
            node = self._dragging_node
            nid = node.node_id

            # 清除跟随者状态
            for idx in self._drag_followers:
                if idx < len(self._graph_nodes):
                    self._graph_nodes[idx].set_follower(False)

            self._dragging_node = None
            self._drag_anchor_pos = None
            self._drag_followers = []
            self._drag_last_pos = None
            self._follower_origins.clear()

            # 同步拖拽节点位置回物理引擎, 冻结后重新平衡
            states = self._engine._states
            for i, n in enumerate(self._graph_nodes):
                if n.node_id == nid and i < len(states):
                    states[i].x = n.pos().x()
                    states[i].y = n.pos().y()
                    states[i].vx = 0.0
                    states[i].vy = 0.0
                    break

            # 同步跟随者位置
            for idx in self._drag_followers:
                if idx < len(self._graph_nodes) and idx < len(states):
                    states[idx].x = self._graph_nodes[idx].pos().x()
                    states[idx].y = self._graph_nodes[idx].pos().y()
                    states[idx].vx = 0.0
                    states[idx].vy = 0.0

            self._engine.freeze_drag_release()
            self._anim_timer.start(16)

        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        for node in self._graph_nodes:
            target = node.base_scale
            if abs(node.scale() - target) > 0.001:
                node.setScale(target)
        super().leaveEvent(event)

    def _update_hover_scale(self, event):
        if not hasattr(self, '_graph_nodes') or not self._graph_nodes:
            return
        scene_pos = self.mapToScene(event.position().toPoint())
        threshold = HOVER_THRESHOLD
        for node in self._graph_nodes:
            dx = node.pos().x() - scene_pos.x()
            dy = node.pos().y() - scene_pos.y()
            dist = math.hypot(dx, dy)
            if dist < threshold:
                t = 1.0 - dist / threshold
                scale = node.base_scale * (1.0 + 0.5 * t)
                node.setScale(scale)
            elif abs(node.scale() - node.base_scale) > 0.001:
                node.setScale(node.base_scale)

    def wheelEvent(self, event):
        """滚轮: 平移画布, Ctrl+滚轮: 视图缩放"""
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            new_zoom = self._zoom * factor
            self._zoom = max(0.2, min(3.0, new_zoom))
            self.scale(factor, factor)
            event.accept()
        else:
            pixel_delta = event.pixelDelta()
            h_scroll = self.horizontalScrollBar()
            v_scroll = self.verticalScrollBar()
            if not pixel_delta.isNull():
                h_scroll.setValue(h_scroll.value() - pixel_delta.x())
                v_scroll.setValue(v_scroll.value() - pixel_delta.y())
            else:
                angle = event.angleDelta()
                h_scroll.setValue(h_scroll.value() - angle.x())
                v_scroll.setValue(v_scroll.value() - angle.y())
            event.accept()

    def mouseDoubleClickEvent(self, event):
        # 只有双击空白区域才重置视图
        item = self.itemAt(event.position().toPoint())
        if item is not None:
            probe = item
            while probe is not None and not isinstance(probe, GraphNode):
                probe = probe.parentItem()
            if isinstance(probe, GraphNode):
                # 双击节点: 不重置视图, 交给节点处理
                super().mouseDoubleClickEvent(event)
                return

        # 走完整 set_force_scale: 同时发信号同步 GUI 滑块, 避免滑块显示与实际不符
        self.set_force_scale(1.0)
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = 1.0
        super().mouseDoubleClickEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        painter.setPen(QPen(QColor(255, 255, 255, 12), 1))
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
