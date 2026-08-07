# [PLAN] 记忆图谱时间区间筛选功能方案

> 日期：2026-08-07 | 版本：v1.0 | 状态：[PLAN]
> 关联文档：[OK]-记忆图谱增量改造方案.md

---

## 目录

- [一、背景与需求](#一背景与需求)
- [二、现有架构分析](#二现有架构分析)
- [三、功能设计](#三功能设计)
- [四、技术实现方案](#四技术实现方案)
- [五、实施计划](#五实施计划)
- [六、风险评估](#六风险评估)
- [七、测试计划](#七测试计划)
- [八、增强功能建议](#八增强功能建议)

---

## 一、背景与需求

### 1.1 功能定位

为 BNOS AI 的记忆图谱增加**时间区间筛选**功能，允许用户按时间段过滤显示记忆节点。

### 1.2 用户场景

| 场景 | 当前痛点 | 期望效果 |
|------|---------|---------|
| 用户想找上周的讨论 | 在全量图谱中难以定位 | 一键筛选"近7天"，只显示上周的记忆 |
| 用户想对比特定时段 | 需要手动翻日志 | 输入自定义时间范围，精确查看该时段 |
| 图谱节点过多 | 视觉混乱，难以阅读 | 通过时间筛选缩小范围，聚焦关注的内容 |

### 1.3 核心价值

1. **提升图谱可用性**：减少视觉干扰，快速定位目标记忆
2. **增强记忆检索能力**：时间维度是记忆的重要索引
3. **为未来功能铺路**：时间渐变着色、时间轴视图等扩展功能的基础

---

## 二、现有架构分析

### 2.1 数据结构

#### 2.1.1 数据库表结构

所有主要数据表均包含 `created_at` 字段：

```sql
-- long_term_memory 表
CREATE TABLE long_term_memory (
    id INTEGER PRIMARY KEY,
    content TEXT,
    identity_key TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),  -- 时间戳
    -- ... 其他字段
);

-- user_messages 表
CREATE TABLE user_messages (
    id INTEGER PRIMARY KEY,
    role TEXT,
    content TEXT,
    identity_key TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),  -- 时间戳
    -- ... 其他字段
);

-- diaries 表
CREATE TABLE diaries (
    id INTEGER PRIMARY KEY,
    content TEXT,
    identity_key TEXT,
    created_at TEXT DEFAULT (datetime('now','localtime')),  -- 时间戳
    -- ... 其他字段
);
```

#### 2.1.2 图谱数据结构

```python
# knowledge_panel.py 中的 _read_db() 函数
def _read_db() -> list[dict]:
    """读取数据库，返回条目列表"""
    rows.append({
        "table": tname,
        "id": record.get("id", 0),
        "content": str(content)[:500],
        "created_at": record.get("created_at", ""),  # ← 时间戳已存在
        "extra": _format_extra(tname, record),
    })
    return rows
```

#### 2.1.3 图谱加载流程

```
_read_db() → _load_data() → KnowledgeGraph.load_data(entries, edges, sim_matrix)
                                        ↓
                                  当前无时间过滤，加载全部数据
```

### 2.2 关键代码文件

| 文件 | 职责 | 需改动部分 |
|------|------|-----------|
| `gui/widgets/knowledge_panel.py` | 面板控制器，数据加载与筛选 | 添加时间筛选 UI、过滤逻辑 |
| `gui/widgets/knowledge_graph.py` | 图谱渲染器 | 无需改动（已支持动态加载） |

### 2.3 技术可行性评估

| 评估项 | 分析 | 结论 |
|--------|------|------|
| 数据层 | ✅ 所有表已有 `created_at` 字段 | 无需改动 |
| UI 控件 | ✅ PySide6 支持 QPushButton、QDateEdit | 现成可用 |
| 过滤逻辑 | ✅ 纯 Python 列表操作 | 无算法复杂度 |
| 图谱重建 | ✅ `load_data()` 已支持重新加载 | 已有基础 |

**结论**：技术可行性极高，无技术障碍。

---

## 三、功能设计

### 3.1 功能清单

| 功能 | 优先级 | 说明 |
|------|:------:|------|
| 快捷时间筛选按钮 | P0 | 全部/今天/近7天/近30天 |
| 筛选结果实时显示 | P0 | 选择后立即更新图谱 |
| 节点数量显示 | P0 | 底部状态栏显示筛选结果统计 |
| 自定义时间范围 | P1 | 支持手动选择起止日期 |
| 时间渐变着色（可选） | P2 | 根据时间远近给节点着色 |

### 3.2 UI 设计

#### 3.2.1 快捷筛选界面

```
┌─────────────────────────────────────────────────────────────┐
│  记忆图谱                              力尺度: ━━●━━ 1.00x   │
├─────────────────────────────────────────────────────────────┤
│  时间筛选: [全部●] [今天] [近7天] [近30天] [自定义▼]         │
│                                                              │
│  ┌─ 可视化区域 ──────────────────────────────────────────┐  │
│  │                                                       │  │
│  │          记忆图谱节点 (按时间筛选后显示)               │  │
│  │                                                       │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
│  显示: 156 个节点 | 来源: long_term_memory(80) | user_messages(50) | diaries(26) │
└─────────────────────────────────────────────────────────────┘
```

#### 3.2.2 自定义时间范围界面

```
┌─────────────────────────────────────────────────────────────┐
│  记忆图谱                              力尺度: ━━●━━ 1.00x   │
├─────────────────────────────────────────────────────────────┤
│  时间筛选: [全部] [今天] [近7天] [近30天] [自定义●]         │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  自定义时间范围:                                       │  │
│  │  从: [2026-08-01] 📅   到: [2026-08-07] 📅           │  │
│  │                              [应用]  [重置]            │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌─ 可视化区域 ──────────────────────────────────────────┐  │
│  │                                                       │  │
│  │          记忆图谱节点 (时间范围: 08-01 ~ 08-07)       │  │
│  │                                                       │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
│  显示: 45 个节点 | 筛选自: 2026-08-01 ~ 2026-08-07         │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 交互流程

#### 3.3.1 快捷筛选

```
用户点击 [近7天]
    ↓
代码计算时间范围：now - 7 days 至 now
    ↓
过滤 entries：只保留 created_at 在范围内的记录
    ↓
重映射 edges：重新计算索引、删除无效边
    ↓
重建 sim_matrix：基于新的 entries 和 edges
    ↓
调用 graph.load_data() 重新加载
    ↓
图谱平滑过渡到新布局
```

#### 3.3.2 自定义范围筛选

```
用户点击 [自定义] → 展开日期选择器
    ↓
用户选择起止日期 → 点击 [应用]
    ↓
验证日期范围有效性（起始日期 ≤ 结束日期）
    ↓
执行与快捷筛选相同的过滤流程
```

### 3.4 边界处理

| 场景 | 处理方式 |
|------|---------|
| 节点数量 < 5 | 显示提示"所选时间范围内节点过少，建议扩大时间范围" |
| 节点数量 > 500 | 显示警告"节点过多可能影响性能，建议缩小时间范围" |
| 时间范围无效 | 显示错误提示 |
| created_at 为空 | 默认排除该记录，不参与图谱显示 |
| created_at 格式异常 | 尝试多种格式解析，失败则排除 |

---

## 四、技术实现方案

### 4.1 文件改动清单

| 文件 | 改动类型 | 改动说明 |
|------|---------|---------|
| `gui/widgets/knowledge_panel.py` | 修改 | 添加时间筛选 UI、过滤逻辑、图谱重建 |

### 4.2 核心代码实现

#### 4.2.1 新增 UI 控件（在 `_build_graph_view` 方法中）

```python
def _build_graph_view(self, container, colors):
    """知识图谱视图 — 添加时间筛选控件"""
    
    # ... 现有代码 (力尺度滑块等) ...
    
    # ── 新增：时间筛选控件 ──
    time_filter_row = QHBoxLayout()
    time_filter_row.setSpacing(6)
    
    time_label = QLabel("时间筛选:")
    time_label.setStyleSheet(f"font-size: 12px; color: {colors['text_primary']}80;")
    time_filter_row.addWidget(time_label)
    
    # 快捷选项按钮
    self._time_btns = {}
    self._current_time_filter = "all"  # 当前选中的筛选方式
    
    for label, key in [("全部", "all"), ("今天", "today"), 
                        ("近7天", "7d"), ("近30天", "30d")]:
        btn = QPushButton(label)
        btn.setCheckable(True)
        btn.setChecked(key == "all")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: 1px solid {colors['border_color']};
                border-radius: 12px; padding: 3px 10px;
                font-size: 11px; color: {colors['text_primary']};
            }}
            QPushButton:checked {{
                background: {colors.get('accent_color', '#1a73e8')};
                color: white; border: none;
            }}
            QPushButton:hover {{
                background: {colors.get('bg_chat', '#eee')};
            }}
        """)
        btn.clicked.connect(lambda checked, k=key: self._filter_by_time(k))
        time_filter_row.addWidget(btn)
        self._time_btns[key] = btn
    
    # 自定义范围按钮
    self._custom_btn = QPushButton("自定义 ▾")
    self._custom_btn.setCheckable(True)
    self._custom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    self._custom_btn.setStyleSheet(...)  # 同上
    self._custom_btn.clicked.connect(self._toggle_custom_range)
    time_filter_row.addWidget(self._custom_btn)
    
    time_filter_row.addStretch()
    layout.addLayout(time_filter_row)
    
    # ── 新增：自定义时间范围 UI（默认隐藏）──
    self._custom_range_widget = QWidget()
    custom_layout = QHBoxLayout(self._custom_range_widget)
    custom_layout.setContentsMargins(0, 4, 0, 4)
    
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
    
    apply_btn = QPushButton("应用")
    apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    apply_btn.setStyleSheet(...)  # accent_color 样式
    apply_btn.clicked.connect(self._apply_custom_range)
    custom_layout.addWidget(apply_btn)
    
    reset_btn = QPushButton("重置")
    reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    reset_btn.setStyleSheet(...)  # 透明边框样式
    reset_btn.clicked.connect(self._reset_time_filter)
    custom_layout.addWidget(reset_btn)
    
    custom_layout.addStretch()
    self._custom_range_widget.hide()
    layout.addWidget(self._custom_range_widget)
    
    # ... 现有代码 (图谱视图、底部状态栏等) ...
```

#### 4.2.2 新增过滤逻辑

```python
def _filter_by_time(self, time_key: str):
    """按时间筛选节点（快捷方式）"""
    import datetime
    
    # 切换按钮状态
    self._current_time_filter = time_key
    self._custom_range_widget.hide()
    self._custom_btn.setChecked(False)
    self._update_time_btn_styles()
    
    # 计算时间范围
    now = datetime.datetime.now()
    if time_key == "all":
        start_date, end_date = None, None
    elif time_key == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = now
    elif time_key == "7d":
        start_date = now - datetime.timedelta(days=7)
        end_date = now
    elif time_key == "30d":
        start_date = now - datetime.timedelta(days=30)
        end_date = now
    
    # 执行过滤
    self._apply_time_filter(start_date, end_date)

def _toggle_custom_range(self):
    """切换自定义时间范围 UI 显示"""
    show = self._custom_btn.isChecked()
    self._custom_range_widget.setVisible(show)
    if show:
        self._current_time_filter = "custom"
        self._update_time_btn_styles()
    else:
        self._reset_time_filter()

def _apply_custom_range(self):
    """应用自定义时间范围"""
    from PySide6.QtCore import QDate
    import datetime
    
    start_qdate = self._date_from.date()
    end_qdate = self._date_to.date()
    
    if start_qdate > end_qdate:
        # 日期范围无效
        self._count_label.setText("⚠ 错误: 起始日期不能晚于结束日期")
        return
    
    start_date = datetime.datetime(
        start_qdate.year(), start_qdate.month(), start_qdate.day()
    )
    end_date = datetime.datetime(
        end_qdate.year(), end_qdate.month(), end_qdate.day(), 23, 59, 59
    )
    
    self._apply_time_filter(start_date, end_date)

def _reset_time_filter(self):
    """重置时间筛选"""
    self._date_from.setDate(QDate.currentDate().addDays(-7))
    self._date_to.setDate(QDate.currentDate())
    self._filter_by_time("all")

def _update_time_btn_styles(self):
    """更新时间筛选按钮样式"""
    for key, btn in self._time_btns.items():
        btn.setChecked(key == self._current_time_filter)

def _apply_time_filter(self, start_date: datetime.datetime | None, 
                        end_date: datetime.datetime | None):
    """执行时间过滤"""
    import datetime
    
    # 1. 过滤 entries
    filtered_entries = []
    for entry in self._graph_entries:
        created_at = entry.get("created_at", "")
        if not created_at:
            if start_date and end_date:
                continue  # 有时间范围时排除无时间戳的记录
            else:
                filtered_entries.append(entry)  # 全部模式保留
                continue
        
        # 解析时间戳
        parsed_date = self._parse_datetime(created_at)
        if parsed_date is None:
            if start_date and end_date:
                continue
            else:
                filtered_entries.append(entry)
                continue
        
        # 检查是否在范围内
        if start_date and end_date:
            if start_date <= parsed_date <= end_date:
                filtered_entries.append(entry)
        else:
            filtered_entries.append(entry)
    
    # 2. 重建图谱
    self._rebuild_graph_with_filter(filtered_entries, start_date, end_date)

def _parse_datetime(self, date_str: str) -> datetime.datetime | None:
    """解析时间字符串，支持多种格式"""
    import datetime
    
    # 尝试多种格式
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d",
    ]
    
    for fmt in formats:
        try:
            return datetime.datetime.strptime(date_str[:len(fmt)+1].strip(), fmt)
        except ValueError:
            continue
    
    return None  # 所有格式都失败

def _rebuild_graph_with_filter(self, filtered_entries: list[dict], 
                                start_date: datetime.datetime | None,
                                end_date: datetime.datetime | None):
    """根据过滤后的 entries 重建图谱"""
    
    if not filtered_entries:
        self._count_label.setText("⚠ 所选时间范围内无记忆节点")
        self._graph.load_data([], [])
        return
    
    # 记录节点在原 entries 中的索引
    id_to_index = {}
    for i, entry in enumerate(self._graph_entries):
        node_id = _node_id_for_entry(entry)
        id_to_index[node_id] = i
    
    # 记录节点在 filtered_entries 中的新索引
    new_id_to_index = {}
    for i, entry in enumerate(filtered_entries):
        node_id = _node_id_for_entry(entry)
        new_id_to_index[node_id] = i
    
    # 1. 过滤 edges 并重新映射索引
    filtered_edges = []
    for edge in self._graph_edges:
        source_idx = edge["source"]
        target_idx = edge["target"]
        
        # 获取源和目标的 entry
        if source_idx >= len(self._graph_entries):
            continue
        if target_idx >= len(self._graph_entries):
            continue
        
        source_entry = self._graph_entries[source_idx]
        target_entry = self._graph_entries[target_idx]
        
        source_id = _node_id_for_entry(source_entry)
        target_id = _node_id_for_entry(target_entry)
        
        # 检查源和目标是否都在过滤后的 entries 中
        if source_id not in new_id_to_index or target_id not in new_id_to_index:
            continue
        
        # 重新映射索引
        new_source = new_id_to_index[source_id]
        new_target = new_id_to_index[target_id]
        
        filtered_edges.append({
            "source": new_source,
            "target": new_target,
            "weight": edge["weight"]
        })
    
    # 2. 重建相似度矩阵
    n = len(filtered_entries)
    new_sim_matrix = [[0.3] * n for _ in range(n)]
    for i in range(n):
        new_sim_matrix[i][i] = 1.0
    for edge in filtered_edges:
        s, t = edge["source"], edge["target"]
        w = edge["weight"]
        if s < n and t < n:
            new_sim_matrix[s][t] = w
            new_sim_matrix[t][s] = w
    
    # 3. 重新加载图谱
    self._graph.load_data(filtered_entries, filtered_edges, new_sim_matrix)
    
    # 4. 更新底部状态栏
    self._update_status_bar(filtered_entries, start_date, end_date)

def _update_status_bar(self, filtered_entries: list[dict],
                        start_date: datetime.datetime | None,
                        end_date: datetime.datetime | None):
    """更新底部状态栏"""
    
    # 统计各表节点数
    table_counts = {}
    for entry in filtered_entries:
        table = entry.get("table", "unknown")
        table_counts[table] = table_counts.get(table, 0) + 1
    
    # 构建统计文本
    stats_parts = [f"{table}({count})" 
                   for table, count in sorted(table_counts.items(), key=lambda x: -x[1])]
    
    # 构建时间范围文本
    if start_date and end_date:
        time_range = f"筛选自: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}"
    else:
        time_range = "全部时间"
    
    # 显示节点数
    total = len(filtered_entries)
    node_info = f"显示: {total} 个节点"
    if total > 0:
        node_info += f" | 来源: {', '.join(stats_parts[:3])}"
    
    self._count_label.setText(f"{node_info} | {time_range}")
```

### 4.3 与现有代码的集成点

```python
# 在 KnowledgePanel.__init__ 中添加
def __init__(self, parent=None):
    # ... 现有代码 ...
    
    # 新增：防抖定时器（避免频繁重建图谱）
    self._filter_debounce_timer = QTimer(self)
    self._filter_debounce_timer.setSingleShot(True)
    self._filter_debounce_timer.timeout.connect(
        lambda: self._apply_time_filter(
            getattr(self, '_pending_start', None),
            getattr(self, '_pending_end', None)
        )
    )
    
    # 新增：当前时间筛选状态
    self._current_time_filter = "all"
    self._pending_start = None
    self._pending_end = None
```

### 4.4 性能优化

```python
def _apply_time_filter(self, start_date, end_date):
    """执行时间过滤（带防抖）"""
    
    # 保存待执行的筛选参数
    self._pending_start = start_date
    self._pending_end = end_date
    
    # 启动防抖定时器（300ms）
    self._filter_debounce_timer.start(300)
```

---

## 五、实施计划

### 5.1 Phase 1：基础功能（4 小时）

| 任务 | 工时 | 交付标准 |
|------|------|---------|
| 添加时间筛选 UI 控件 | 1h | 快捷按钮正常显示 |
| 实现快捷筛选逻辑 | 1.5h | 全部/今天/近7天/近30天筛选正常 |
| 实现图谱重建逻辑 | 1h | 筛选后图谱正确加载 |
| 更新底部状态栏 | 0.5h | 显示节点数和时间范围 |

### 5.2 Phase 2：增强功能（3 小时）

| 任务 | 工时 | 交付标准 |
|------|------|---------|
| 添加自定义时间范围 UI | 1h | 日期选择器正常显示 |
| 实现自定义筛选逻辑 | 1.5h | 自定义时间范围筛选正常 |
| 添加边界处理 | 0.5h | 无效日期范围提示 |

### 5.3 Phase 3：优化与测试（2 小时）

| 任务 | 工时 | 交付标准 |
|------|------|---------|
| 添加防抖处理 | 0.5h | 快速切换筛选不卡顿 |
| 全功能测试 | 1h | 所有筛选场景正常 |
| 边界测试 | 0.5h | 空数据、少数据、多数据场景正常 |

### 5.4 总工时

**总计：约 9 小时（1 个工作日）**

---

## 六、风险评估

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| **时间格式不一致** | 部分记录无法解析 | 中 | 多格式容错解析，失败则排除 |
| **筛选后节点过少** | 图谱无意义 | 低 | 显示提示，建议扩大范围 |
| **筛选后节点过多** | 性能下降 | 低 | 显示警告，建议缩小范围 |
| **频繁切换导致卡顿** | 用户体验差 | 低 | 300ms 防抖处理 |
| **边界映射错误** | 图谱边错位 | 低 | 严格的索引重映射逻辑 |

---

## 七、测试计划

### 7.1 功能测试

| 测试场景 | 测试步骤 | 预期结果 |
|---------|---------|---------|
| 全部显示 | 点击 [全部] | 显示所有节点 |
| 今天筛选 | 点击 [今天] | 只显示今天的节点 |
| 近7天筛选 | 点击 [近7天] | 只显示近7天的节点 |
| 近30天筛选 | 点击 [近30天] | 只显示近30天的节点 |
| 自定义范围 | 选择起止日期 → 点击 [应用] | 显示指定时间范围内的节点 |
| 重置筛选 | 点击 [重置] | 恢复全部显示 |
| 状态栏显示 | 选择任意筛选 | 底部显示节点数和时间范围 |

### 7.2 边界测试

| 测试场景 | 测试步骤 | 预期结果 |
|---------|---------|---------|
| 空数据范围 | 选择无数据的时间段 | 显示"无记忆节点"提示 |
| 数据过少 | 选择只有2-3个节点的时间段 | 正常显示，图谱布局不报错 |
| 日期格式异常 | 存在 created_at 为空的记录 | 自动排除，不影响其他记录 |
| 无效日期范围 | 起始日期 > 结束日期 | 显示错误提示 |

### 7.3 性能测试

| 测试场景 | 测试步骤 | 预期结果 |
|---------|---------|---------|
| 快速切换 | 连续快速点击不同时间筛选 | 不卡顿，300ms 防抖生效 |
| 大数据量 | 节点数量 > 500 | 筛选后图谱正常加载 |
| 频繁刷新 | 多次点击筛选按钮 | 不产生性能问题 |

---

## 八、增强功能建议

### 8.1 Phase 2+：时间渐变着色

**功能**：根据节点的时间戳，用颜色深浅表示时间远近。

```python
def _apply_time_color(node, created_at: str, now: datetime):
    """根据时间戳给节点着色"""
    import datetime
    
    dt = self._parse_datetime(created_at)
    if dt is None:
        return
    
    days_ago = (now - dt).days
    
    if days_ago <= 1:
        # 近1天: 亮蓝色
        node.setBrush(QBrush(QColor("#4a9eff")))
    elif days_ago <= 7:
        # 近7天: 中等蓝色
        node.setBrush(QBrush(QColor("#3a7ecc")))
    elif days_ago <= 30:
        # 近30天: 深蓝色
        node.setBrush(QBrush(QColor("#2a5e99")))
    else:
        # 更早: 灰色
        node.setBrush(QBrush(QColor("#a0a8b8")))
```

### 8.2 Phase 3：时间轴视图

**功能**：将图谱切换为时间轴模式，节点按时间顺序排列。

```
    08-01  ─●──●─●──
    08-02  ─●──────
    08-03  ─●──●──●─●──
    08-04  ─●─●──────●─
    ...
```

### 8.3 Phase 3：时间分布统计

**功能**：显示各时间段的记忆数量分布柱状图。

```
记忆时间分布 (近30天):
 08-01 ██████ 12条
 08-02 ████   8条
 08-03 ██████ 15条
 08-04 ███    6条
 ...
```

---

## 附录

### A. 数据库时间字段格式

所有表的 `created_at` 字段格式为 SQLite 默认格式：

```
YYYY-MM-DD HH:MM:SS
示例: 2026-08-07 14:30:00
```

### B. 相关代码文件

| 文件路径 | 说明 |
|---------|------|
| `gui/widgets/knowledge_panel.py` | 本方案主要改动文件 |
| `gui/widgets/knowledge_graph.py` | 图谱渲染器（无需改动） |
| `nodes/shared/chatbot.db` | 数据库（无需改动） |

### C. 相关文档

| 文档 | 说明 |
|------|------|
| `[OK]-记忆图谱增量改造方案.md` | 记忆图谱基础改造方案 |
| `[PLAN]-AI世界感知记忆系统设计方案.md` | 记忆系统设计方案 |

---

*本方案基于 BNOS AI 现有记忆图谱架构设计，旨在通过最小改动实现时间区间筛选功能，提升图谱的实用性和用户体验。*
