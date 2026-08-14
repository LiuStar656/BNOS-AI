# 数据驱动 UI 布局动态调整方案（待决策）

> 日期：2026-08-14 | 版本：v1.0 | 状态：[PLAN]

## 目录

1. [背景与现状评估](#一背景与现状评估)
2. [目标](#二目标)
3. [方案设计](#三方案设计)
4. [分阶段实施计划](#四分阶段实施计划)
5. [风险评估](#五风险评估)
6. [测试计划](#六测试计划)
7. [影响范围](#七影响范围)

---

## 一、背景与现状评估

### 1.1 用户诉求（2026-08-14 会话）

用户希望 GUI 达到 DeepSeek Harness 的能力：**布局结构可动态调整**——"原本是侧标签栏可以
直接改成顶部标签栏，不需要重启，还可以回退，还要 ui 的颜色、大小、背景等"。
通过**告诉 AI 需求**的方式触发调整（如「换个风格」「把标签栏放上面」）。

### 1.2 当前已具备（上轮完成）

| 能力 | 实现 | 状态 |
|---|---|---|
| 颜色/背景/大小 token 化 | ThemeEngine（`gui/core/theme_engine.py`）token→全局 QSS 唯一生成器 | ✅ |
| 皮肤包 AI 产出 | SkinRegistry（`gui/resources/themes/<skin_id>/`，metadata.json + tokens.json） | ✅ |
| 变更治理（审批/回退） | ProposalStore（`gui/core/proposal_store.py`，skin 类提案 pending→approve→revert） | ✅ |
| AI 工具闭环 | ToolRegistry 25 工具 + ToolBridge 文件通道 + AAA 侧 gui_tools/prompt/main 注入 | ✅ |
| 页面插槽化 | UiRegistry（`page.<id>` 注册，懒加载工厂，Sidebar 与 MainWindow 从注册中心读取） | ✅ |

### 1.3 缺口（本方案目标）

**布局结构硬编码在 MainWindow**：

- [main_window.py](file:///e:/杂项/BNOS_AI_project/gui/main_window.py) `_init_central()`：
  `QVBoxLayout（标题栏 + 内容区）` → `QHBoxLayout（Sidebar + 右区）`，左栏固定竖排
- [sidebar.py](file:///e:/杂项/BNOS_AI_project/gui/widgets/sidebar.py)：`setFixedWidth(56)`，
  竖排图标按钮组，由 `ui_registry.tabs()` 驱动（已数据驱动，但**位置/方向/宽度/显隐硬编码**）
- 页面切换方向依赖 `ui_registry.page_ids()` 索引（滑动动画写死横向）

即：**页面清单已插槽化，但「导航布局」未插槽化**。布局不可配置、不可切换、不可回退。

---

## 二、目标

1. **布局 Schema 化**：主窗口布局（导航位置/方向/宽度、页面显隐与排序、导航外观文本或图标）
   描述为 JSON LayoutSpec，可落盘、可切换、可回退
2. **运行时切换不重启**：LayoutEngine 依 LayoutSpec 重建内容区，页面实例复用（不重建页面栈），
   导航容器按规格重排
3. **AI 可驱动**：新增 `ui.apply_layout` / `ui.list_layouts` 工具，走提案审批闭环
   （用户说需求 → AI 产出 LayoutSpec → 提案卡 → 审批 → 即时生效 → 可回退）
4. **与既有换肤正交**：颜色/大小/背景走 ThemeEngine token；布局走 LayoutEngine Schema，
   二者可独立切换、可组合、同走提案回退
5. **边界诚实**：布局调整 = 导航位置/方向/宽度/页面显隐/顺序 + 窗口默认尺寸；
   不做组件内部重排（如聊天页气泡布局不属于主窗口布局）

---

## 三、方案设计

### 3.1 布局 Schema（LayoutSpec）

```
gui/resources/layouts/<layout_id>/layout.json
```

```jsonc
{
  "id": "top-nav",
  "name": "顶部标签栏",
  "description": "导航置于顶部，横向排列",
  "version": "1.0",
  "layout": {
    "nav_position": "top",          // "left" | "top"
    "nav_width": 56,                // 左栏宽度（nav_position=left 时生效）
    "nav_height": 48,               // 顶栏高度（nav_position=top 时生效）
    "nav_mode": "icon",             // "icon" | "text" | "icon_text"（导航项外观）
    "nav_visible": true,            // 导航栏整体显隐
    "pages": [                      // 页面 id 顺序 + 显隐（缺省=注册顺序全部显示）
      {"id": "chat", "visible": true},
      {"id": "activity", "visible": true}
    ],
    "window_default": {"width": 1200, "height": 800}
  }
}
```

默认布局（内置 `default`）等价于当前硬编码：`nav_position=left, nav_width=56, nav_mode=icon`。

### 3.2 LayoutRegistry（布局注册中心）

仿 SkinRegistry（`gui/core/layout_registry.py`）：

- 扫描 `gui/resources/layouts/`，加载 metadata.json + layout.json（容错：缺文件/坏 JSON 跳过）
- `list_layouts()` / `get(id)` / `has(id)`
- `install(layout_id, name, spec, ...)`：AI 产出落盘入口（安全字符校验同 skin）
- `remove(id)`
- 内置布局在代码内注册（不落盘），用户/AI 布局落盘，同名内置优先（与预设语义一致）

### 3.3 LayoutEngine（布局应用器）

`gui/core/layout_engine.py`：

- `apply(spec, main_window)`：读 LayoutSpec → 重建内容区导航容器 → 重排窗口
- 页面栈 `QStackedWidget` **复用既有实例**（`main_window._pages` 不重建），只重排布局
- 导航容器抽象：抽取「导航视图」接口（NavView），两种实现：
  - `SidebarNav`（左栏竖排，现 Sidebar 改造）
  - `TopNav`（顶栏横排，QTabBar 风格或横排按钮组）
  - 同一数据源 `ui_registry.tabs()` + `LayoutSpec.pages` 过滤/排序
- 切换过程：旧导航容器 `deleteLater()` → 按新 spec 创建新导航 → `setCurrentWidget`
  保持当前页 → 发布 `LAYOUT_CHANGED` 消息（阶段4 模式，组件自查刷新）
- 与主题正交：导航容器样式走 ThemeEngine token（sidebar_bg 等），layout 只控制结构

### 3.4 提案治理复用

扩展 ProposalStore 的 kind：`"skin"`（现有）+ `"layout"`：

- `payload` = `{"layout_id", "spec"}`（新布局）
- `prior` 快照 = 当前生效的 `layout_id`（回退 = 恢复该布局）
- 审批：`layout_registry.install` + `layout_engine.apply` + `event_bus.publish(LAYOUT_CHANGED)`
- 回退：revert 恢复 prior 布局（layout_id 为空 = 内置默认），皮肤与布局互相独立回退

### 3.5 AI 工具接入（ToolRegistry）

新增 2 个工具（并入阶段7 清单，总量 25→27）：

| 工具 | 参数 | 行为 |
|---|---|---|
| `ui.list_layouts` | 无 | 布局清单（id/name/description/当前激活） |
| `ui.apply_layout` | `name`（布局名）/ `spec`（可选 JSON 直接给出） | 生成 layout 提案（走审批，不直接生效） |

AAA 侧无需改动（`gui_tools.py` 已泛化注入工具清单，调用时机说明上轮已放宽）。
用户话术示例：**「把标签栏挪到上面」→ AAA 输出 `ui.apply_layout`（spec 含
nav_position=top）→ 提案卡 → 用户批准 → 顶部标签栏即时生效 → 不满意可回退**。

---

## 四、分阶段实施计划

### Phase 0：布局抽象重构（纯 GUI）

- 抽 NavView 接口；Sidebar 改名为 SidebarNav（竖排实现，行为不变）
- MainWindow `_init_central` 改为读「默认 LayoutSpec」组装（先用内置 default，行为不变）
- 验收：启动与现状无差异（8 套预设视觉回归）

### Phase 1：LayoutRegistry + LayoutEngine

- 新增 layout_registry.py / layout_engine.py / TopNav 实现
- `apply()` 支持 left/top 切换、宽度/高度、页面显隐排序、窗口默认尺寸
- LAYOUT_CHANGED 消息；MainWindow 订阅后重建导航
- 验收：GUI 设置页或调试入口可切换 default ↔ top-nav 布局，不重启、页面状态保留

### Phase 2：提案治理 + 回退

- ProposalStore 支持 kind="layout"；prior 快照与 revert
- 提案页渲染 layout 提案（复用皮肤提案卡片，标题/描述区分）
- 验收：apply → 审批生效 → revert 恢复，先决条件齐全

### Phase 3：AI 工具闭环

- ToolRegistry 注册 ui.list_layouts / ui.apply_layout
- gui_tool_schemas.json 自动包含新工具（to_file 已泛化）
- 验收：AAA 对话「把标签栏放上面」→ 提案 → 批准 → 顶栏生效 → 回退

---

## 五、风险评估

| 风险 | 缓解 |
|---|---|
| 导航重建丢失选中态/状态 | 保留 `_pages` 与当前页引用，重建后 `setCurrentWidget` 恢复；选中态由当前页驱动 |
| 滑动动画依赖横向 page_ids 索引 | 切换方向改为依据 spec 内页面顺序计算；顶栏布局下动画方向按逻辑顺序 |
| 与换肤耦合引入回归 | LayoutEngine 只操作结构，样式仍走 theme_engine；二者独立事件 |
| 页面显隐导致 page_ids 与 tabs 不一致 | LayoutSpec.pages 是**过滤/排序视图**，注册中心仍为全量权威源；缺省全显示 |
| 浮动面板定位依赖 MainWindow | FloatingPanel 以 MainWindow 为 parent 定位，不依赖 Sidebar 布局，不受影响 |
| AI 产出非法 spec | install/apply 前做 Schema 校验（nav_position 枚举、pages 引用存在性、数值边界） |

## 六、测试计划

- 单元：LayoutSpec 校验器（非法值拒绝）；LayoutRegistry 扫描/安装/移除；LayoutEngine 各 spec 输出结构断言
- 集成（offscreen）：default ↔ top-nav 切换后页面实例一致、当前页保持、导航项数量/顺序正确
- 提案：apply layout → approve → revert 状态机与皮肤提案正交
- 端到端：AAA 对话触发 → 提案 → 审批 → 顶栏生效 → 回退；重启后布局持久化
- 回归：8 套预设视觉 + run.bat 启动检测

## 七、影响范围

| 文件 | 改动 |
|---|---|
| `gui/widgets/sidebar.py` | 改造为 SidebarNav（竖排实现），样式逻辑保持 |
| `gui/widgets/top_nav.py` | 新增：顶栏横排导航 |
| `gui/core/layout_registry.py` | 新增：布局注册中心（扫描/安装/移除） |
| `gui/core/layout_engine.py` | 新增：布局应用器（spec→重建导航容器） |
| `gui/core/layout_spec.py` | 新增：LayoutSpec 校验器（枚举/引用/数值边界） |
| `gui/main_window.py` | `_init_central` 数据驱动化；订阅 LAYOUT_CHANGED 重建导航 |
| `gui/core/proposal_store.py` | kind 扩展 "layout" + prior 快照/revert |
| `gui/core/messages.py` | 新增 `LAYOUT_CHANGED` 消息常量 |
| `gui/core/tool_registry.py` | 新增 `ui.list_layouts` / `ui.apply_layout`（工具 25→27） |
| `gui/core/config.py` | 持久化当前 layout_id（重启恢复） |
| `docs/design/[PLAN]-GUI可插拔化与AI操控UI完整方案.md` | P0-1c 布局结构调整项标注完成 |

## 附：与「换肤」的边界

| 维度 | 归属 | 触发 |
|---|---|---|
| 颜色 / 背景 | ThemeEngine token | 皮肤包 / ui.create_skin_proposal |
| 字号 / 控件尺寸 | ThemeEngine token（配合 fit_button_width） | 皮肤包 |
| 导航位置/方向/宽度 | LayoutSpec | 布局包 / ui.apply_layout |
| 页面显隐 / 顺序 | LayoutSpec | 布局包 / ui.apply_layout |
| 窗口默认尺寸 | LayoutSpec.window_default | 布局包 / ui.apply_layout |
