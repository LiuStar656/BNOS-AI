# 图谱交互优化方案

> 日期：2026-08-07 | 版本：v1.0 | 状态：[PLAN]

## 一、优化目标

1. **画布可移动**：支持鼠标拖拽平移画布
2. **节点默认缩小**：减小节点基础尺寸，让图谱更紧凑
3. **鼠标靠近放大**：光标靠近节点时自动放大（最大 1.5 倍）

---

## 二、需求分析

### 2.1 当前状态

| 功能 | 状态 | 说明 |
|------|:----:|------|
| 画布缩放 | ✅ 已实现 | 滚轮缩放 (0.2x-3.0x) |
| 画布移动 | ❌ 未实现 | 只能缩放，不能平移 |
| 节点尺寸 | ❌ 固定 | 半径 12px 固定 |
| 悬停放大 | ❌ 未实现 | 无交互反馈 |

### 2.2 目标行为

#### 画布移动

```
用户：按住鼠标左键 + 拖拽
效果：画布跟随鼠标移动（平移视口）
约束：不与节点拖拽冲突（需区分点击和拖拽）
```

#### 节点默认尺寸

```
当前半径：12px
优化后：8px（缩小 33%）
视觉效果：更紧凑，能展示更多节点
```

#### 鼠标靠近放大

```
触发条件：光标与节点距离 < 200px（视图坐标）
放大公式：
  scale = 1.0 + 0.5 * (1 - dist / threshold)
  
  dist = 0px   → scale = 1.5 (最大，比最小大50%)
  dist = 100px → scale = 1.25
  dist = 200px → scale = 1.0 (恢复原始)

性能优化：
  - 距离阈值过滤（只计算光标附近节点）
  - QGraphicsItem 原生 setScale()，无重绘开销
```

---

## 三、实现方案

### 3.1 画布移动

**文件**：`knowledge_graph.py`

**改动**：

```python
class KnowledgeGraph(QGraphicsView):
    def __init__(self, ...):
        # 当前已设置：
        # self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        
        # 需添加：
        # self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
```

**注意**：当前 `ScrollHandDrag` 模式可能与节点拖拽冲突。需改为自定义实现：

```python
class KnowledgeGraph(QGraphicsView):
    def __init__(self, ...):
        # 改为 NoDrag，自定义拖拽逻辑
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._pan_start = None
        self._is_panning = False
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._pan_start = event.position().toPoint()
            self._is_panning = False
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        if self._pan_start is not None:
            delta = event.position().toPoint() - self._pan_start
            if delta.manhattanLength() > 5:  # 移动超过5像素判定为拖拽
                self._is_panning = True
                self._pan_start = event.position().toPoint()
                self.horizontalScrollBar().setValue(
                    self.horizontalScrollBar().value() - delta.x()
                )
                self.verticalScrollBar().setValue(
                    self.verticalScrollBar().value() - delta.y()
                )
        super().mouseMoveEvent(event)
    
    def mouseReleaseEvent(self, event):
        self._pan_start = None
        super().mouseReleaseEvent(event)
```

### 3.2 节点默认缩小

**文件**：`knowledge_graph.py`

**改动**：

```python
# 当前
NODE_RADIUS = 12

# 改为
NODE_RADIUS = 8
```

### 3.3 鼠标靠近放大

**文件**：`knowledge_graph.py`

**改动**：

```python
class KnowledgeGraph(QGraphicsView):
    HOVER_THRESHOLD = 200  # 视图坐标，像素
    
    def mouseMoveEvent(self, event):
        # ... 画布拖拽逻辑 ...
        
        # 新增：悬停放大
        scene_pos = self.mapToScene(event.position().toPoint())
        zoom = self._zoom
        threshold = self.HOVER_THRESHOLD / zoom  # 转换为场景坐标
        
        for node in self._scene.nodes():
            dx = node.pos().x() - scene_pos.x()
            dy = node.pos().y() - scene_pos.y()
            dist = math.hypot(dx, dy)
            
            if dist < threshold:
                # 距离越近，缩放越大
                scale = 1.0 + 0.5 * (1 - dist / threshold)
                node.setScale(scale)
            elif node.scale() != 1.0:
                # 恢复原始大小
                node.setScale(1.0)
    
    def leaveEvent(self, event):
        """鼠标离开时恢复所有节点"""
        for node in self._scene.nodes():
            node.setScale(1.0)
        super().leaveEvent(event)
```

---

## 四、改动清单

### 4.1 knowledge_graph.py

| 改动 | 类型 | 说明 |
|------|------|------|
| `NODE_RADIUS` | 🟡 常量 | 12 → 8 |
| `__init__()` | 🟡 修改 | 拖拽模式改为 NoDrag，添加滚动条策略 |
| 新增 `mousePressEvent()` | 🟢 新增 | 记录拖拽起点 |
| 新增 `mouseMoveEvent()` | 🟢 新增 | 画布平移 + 悬停放大 |
| 新增 `mouseReleaseEvent()` | 🟢 新增 | 结束拖拽 |
| 新增 `leaveEvent()` | 🟢 新增 | 鼠标离开恢复节点大小 |
| 新增 `HOVER_THRESHOLD` | 🟢 常量 | 悬停检测距离（200px） |

---

## 五、性能分析

### 5.1 计算量

| 操作 | 计算量 | 耗时估算 |
|------|:------:|:--------:|
| 画布平移 | 无 | 0ms |
| 悬停距离计算 | O(N) | N=200: <0.01ms<br>N=1000: <0.05ms |
| 节点缩放 | O(悬停节点数) | 无开销（QGraphicsItem 原生） |

### 5.2 帧率影响

| 节点数 | 预期帧率 | 影响 |
|:------:|:--------:|:----:|
| 200 | 60 FPS | 无感 |
| 1000 | 60 FPS | 无感 |
| 5000 | 55-60 FPS | 轻微 |

---

## 六、交互冲突解决

### 6.1 画布拖拽 vs 节点拖拽

```
判定逻辑：
  鼠标按下 → 记录起点
  
  移动时检查：
    移动距离 > 5px → 判定为画布拖拽
    移动距离 <= 5px → 判定为节点点击/拖拽
```

### 6.2 画布拖拽 vs 节点选中

```
判定逻辑：
  画布拖拽开始 → 设置 _is_panning = True
  释放时检查 _is_panning:
    True → 不触发选中事件
    False → 正常触发选中事件
```

---

## 七、测试要点

| 测试项 | 预期结果 |
|--------|---------|
| 画布拖拽 | 按住左键拖拽，画布跟随移动 |
| 节点缩放 | 默认较小，鼠标靠近时放大 |
| 节点点击 | 点击节点能选中并显示详情 |
| 节点拖拽 | 拖拽节点能改变位置 |
| 滚轮缩放 | 保持原有缩放功能 |
| 缩放+平移 | 缩放后拖拽平移正常 |
| 离开恢复 | 鼠标离开图谱区域，节点恢复原始大小 |

---

*本方案实现图谱画布平移、节点缩放和悬停放大三项交互优化，性能消耗极低，适用于当前 200+ 节点规模。*
