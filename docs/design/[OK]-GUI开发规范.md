# BNOS AI GUI 开发规范

> 日期：2026-08-14 | 版本：v1.0 | 状态：[OK]
>
> 本规范是 GUI 层的"开发规范文件"，面向**人 + AI**：告诉 Agent 改 GUI 时要遵守什么。
> 对应 DSH 的 `AGENTS.md + web-styling.md + config-catalog.md` 三层体系。
> 工程层（AGENTS）→ 二；样式层（web-styling）→ 三；配置层（config-catalog）→ 四。

## 目录

1. [设计哲学](#一设计哲学)
2. [GUI 工程规范](#二gui-工程规范)
3. [GUI 样式规范](#三gui-样式规范)
4. [GUI 配置规范](#四gui-配置规范)
5. [AI 操控 GUI 的规则](#五ai-操控-gui-的规则)
6. [审查清单](#六审查清单)

---

## 一、设计哲学

| 原则 | 含义 | 违反示例 |
|------|------|----------|
| **Token 优先** | 所有颜色经 `theme_engine.get(key)` / `get_all_colors()` 取色，不写裸色值 | 组件里写死 `#95ec69` |
| **插槽组装** | 页面经 `ui_registry` 注册（`page.<id>` 插槽 + 工厂），主窗口只消费插槽 | main_window 直接 import 页面类 |
| **消息协作** | 组件间运行时协作走 `event_bus` 消息（消息名在 `messages.py` 单一事实源），不互相 import 私有方法 | 页面 A 直接调页面 B 的 `_xxx()` |
| **单一数据源** | 页面元信息在 `ui_registry`；主题色在 `gui_config.json` + 预设/皮肤包；工具清单在 `tool_registry` | 侧边栏再手写一份页面列表 |
| **AI 同通道** | AI 操控 GUI 与组件协作走同一条消息/工具通道 | 为 AI 单独开一套私有接口 |

---

## 二、GUI 工程规范

### 2.1 目录结构

```
gui/
├── main.py               # 启动入口（QApplication + MainWindow）
├── main_window.py        # 主窗口：消费 ui_registry 插槽组装页面
├── requirements.txt
├── README.md             # 模块索引（指向本规范）
├── core/                 # 核心基础设施（不依赖具体页面）
│   ├── config.py         # AppConfig：主题/配置持久化（gui_config.json）
│   ├── theme_engine.py   # 主题引擎：token → 全局 QSS 唯一生成 + 统一取色
│   ├── event_bus.py      # EventBus：组件间消息发布订阅
│   ├── messages.py       # 消息协议（单一事实源，禁直接造字符串）
│   ├── state.py          # AppState：跨页面共享状态
│   ├── ui_registry.py    # UI 插槽注册中心（页面注册/懒加载/冲突即设计）
│   ├── icon_registry.py  # 图标注册（Codicon）
│   ├── skin_registry.py  # 皮肤包注册（与内置预设平级）
│   ├── proposal_store.py # 提案（AI 破坏性变更审批）
│   ├── tool_registry.py  # AI 操控工具注册（22 工具）
│   ├── tool_bridge.py    # 工具桥：GUI ↔ AAA 节点文件通道
│   ├── workflow_store.py # 流程库（dsh 执行类步骤节点直连）
│   ├── message_manager.py# 消息收发：gui_input/gui_reply 轮询
│   ├── logger.py         # 日志
│   └── location_provider.py # 定位
├── pages/                # 页面（插槽工厂，见 2.3）
│   ├── chat_page.py      # 聊天（微信风气泡）
│   ├── settings_panel.py # 设置面板
│   ├── dsh_manage_page.py
│   └── ...               # 每个页面一个文件，经 ui_registry 注册
├── widgets/              # 业务组件（可被多个页面复用）
│   ├── chat_bubble.py    # 聊天气泡
│   ├── sidebar.py        # 侧边栏
│   ├── chat_input.py     # 输入框
│   └── ...
├── dialogs/              # 对话框
└── resources/            # 静态资源（icons/theme.py 兼容层）
```

### 2.2 核心模块职责

| 模块 | 职责 | 其他代码怎么用 |
|------|------|----------------|
| `AppConfig` | 主题色/窗口几何持久化（单例） | `from gui.core.config import AppConfig; config.get_all_colors()` |
| `theme_engine` | 统一取色 + 生成全局 QSS | `theme_engine.get("key")` / `theme_engine.apply_global(widget)` |
| `event_bus` | 消息发布订阅 | `event_bus.publish(THEME_CHANGED, data)`；页面 `on_change(...)` 订阅 |
| `messages` | 消息名常量 | **只 import 常量，禁止拼字符串** |
| `ui_registry` | 页面插槽注册/解析 | 新页面 → 在 `_register_builtin` 注册（注册顺序=侧边栏顺序） |
| `layout_spec` | 布局 Schema（LayoutSpec）校验 | 改布局结构 → `spec.errors()` 校验非法值 |
| `layout_registry` | 布局包注册中心（内置 default + 扫描落盘） | 新布局 → 落盘 `gui/resources/layouts/<id>/layout.json` 或 `install()` |
| `layout_engine` | 布局应用器（spec → 重建导航容器，不重启、页面复用） | 切换布局 → `event_bus.publish(LAYOUT_REQUEST, layout_id)` 或提案审批 |
| `tool_registry` | AI 工具注册 | 新增 AI 能力 → 注册 `ui.` 前缀工具 |
| `message_manager` | GUI↔AAA 消息（gui_input/gui_reply） | 发消息 → `message_manager.send_text(...)` |
| `workflow_store` | 流程执行；dsh.* 步骤直连 node_dsh 节点 | 流程步骤的 tool 名 + args |

### 2.3 页面注册规则

- 新页面 = `gui/pages/xxx_page.py` 一个文件，**必须**在 `ui_registry._register_builtin()` 注册：
  ```python
  self.register("page.xxx", XxxPage, meta={"icon": "icon", "page_id": "xxx", "title": "XXX"})
  ```
- 插槽命名 `page.<page_id>`；`meta` 的 icon/page_id/title 是侧边栏与主窗口的**唯一数据源**
- 注册顺序即侧边栏/页面切换顺序；同插槽重复注册默认抛 `SlotConflictError`（冲突即设计），覆盖需 `replace=True`
- 页面工厂懒加载：`resolve()` 时实例化；页面构造函数不应做重 IO

### 2.4 消息协议（messages.py）

| 消息 | 含义 | data |
|------|------|------|
| `THEME_CHANGED` | 主题变更 → 组件自查换肤 | — |
| `PAGE_ACTIVATED` | 页面被激活 | page_id |
| `DATA_REFRESH_REQUESTED` | 数据刷新请求（AI 操控入口） | 页面 id 或 None=当前页 |
| `NAVIGATE_REQUEST` | 页面导航（AI 操控入口） | page_id |
| `LAYOUT_REQUEST` | 布局应用请求（设置面板/AI 工具入口） | layout_id |
| `LAYOUT_CHANGED` | 布局已变更 → 组件自查刷新 | layout_id |
| `AI_EVENT` | AI 实时事件推送 | {"type","text","ts"} |

规则：组件对外只订阅关心的消息；调用方只 `publish`，不 import 对方内部方法。

### 2.5 GUI ↔ 节点通信协议（文件通道）

| 文件 | 方向 | 内容 |
|------|------|------|
| `nodes/shared/gui_input.json` | GUI → AAA | 用户输入（含 request_id） |
| `nodes/shared/gui_reply.json` | AAA → GUI | reply 输出（含 request_id，MessageManager 轮询 mtime+md5 判新） |
| `nodes/shared/mode.json` | 双向 | `{"mode": "daily"|"work"}`（日常/工作模式，原子写） |
| `nodes/shared/dsh_task_in.json` | → node_dsh | DSH 任务（data_type=dsh_task, task_id） |
| `nodes/node_dsh/output.json` | ← node_dsh | DSH 结果（task_id 精确匹配） |
| `nodes/shared/dsh_question_in.json` | node_dsh → GUI | DSH 提问（headless provider 写入，qid 批次） |
| `nodes/shared/dsh_answer_out.json` | GUI → node_dsh | 用户回答（qid 精确匹配，options 按钮 + 自由输入） |
| `nodes/shared/node_activity.json` | AAA/LLM/DSH → GUI | 任务活动状态 `{"stage","text","ts","request_id?"}`（各节点阶段原子写，GUI 等待气泡轮询实时文案，超时可定位卡点；DSH 执行阶段 text 为实时输出——headless runner 经 session/event 把回合开始/工具调用/中间文本逐段写入，GUI 显示后随最终回复关闭） |

规则：
- 写共享文件一律**原子写**（tmp + replace），避免并发写撕裂
- 结果判定用 `request_id` / `task_id` 精确匹配，不读"最近一次"；活动状态文件仅作**展示**（最近一次即可，不作结果判定）
- 节点文件属 BNOS 层，GUI 只读写协议文件，不直接调用节点内部模块

### 2.6 布局调整

布局完整契约（LayoutSpec 全字段/校验/切换语义/提案回退）见
[数据驱动UI布局动态调整方案](./[OK]-数据驱动UI布局动态调整方案.md)。此处为改布局时的强制项：

- **唯一事实源**：布局 = `gui/resources/layouts/<id>/layout.json` 的 LayoutSpec；改动必须落盘或 `layout_registry.install()`，禁止在 main_window 硬编码布局结构
- **pages 是过滤/排序视图**：`spec.pages` 只控制显示顺序与显隐，`ui_registry` 注册中心仍是全量权威源，禁止删注册
- **切换不重建页面**：`layout_engine.apply()` 复用页面实例（QStackedWidget 不重建），只重建导航容器，页面状态必须保留
- **走提案审批**：AI 布局变更（`ui.apply_layout` / 新布局包）生成 `kind="layout"` 提案，审批后才 apply；回退恢复 prior 布局
- **不拉扯窗口**：`window_default` 仅作 spec 记录/新装默认，切换布局不强制改变用户当前窗口尺寸
- **与换肤正交**：布局只操作结构（导航位置/方向/宽度/显隐/顺序），颜色/大小走 theme_engine token；二者独立切换、独立回退

---

## 三、GUI 样式规范

### 3.1 主题 Token 体系

- **内置 8 套预设**（`AppConfig.THEME_PRESETS`）：default_light/dark/amoled/macos/koyu/ubuntu/neon/gri；`mode` 字段区分明暗
- **皮肤包**（`skin_registry`）：与内置预设平级，`selected_skin` 启用后增量覆盖 token
- **兜底表**（`theme_engine._TOKEN_DEFAULTS`）：旧预设未定义的新 token 在此给默认值，保证换肤不崩
- **全局 QSS**（`theme_engine.generate_global_qss()`）：由 token 生成，`apply_global` 应用后 Qt 级联即时生效（无需重启）

### 3.2 取色规则（Token 优先）

- 一律 `theme_engine.get("token_key")` 或 `config.get_all_colors()` 取色
- **禁止**在组件里写裸色值（如 `#f2f3f5`、`#4f8cff`）
- 新增语义色：先在 `_TOKEN_DEFAULTS` 给兜底，再在预设/皮肤包补值
- 常用 token：`accent_color`/`accent_hover`/`bg_primary`/`bg_secondary`/`bg_chat`/`text_primary`/`text_secondary`/`border_color`/`bubble_user_bg`/`bubble_user_text`/`bubble_ai_bg`/`bubble_ai_text`/`sidebar_*`/`toast_*`/`success_color`/`danger_color`/`status_ok`/`status_warn`/`status_error`/`disabled_bg`/`icon_color`/`icon_muted`/`list_selected_bg`/`card_hover`/`separator` 等
- 现状治理：部分组件仍存在硬编码色（chat_page 模式按钮、settings_panel 输入框等），改动时应顺手收口到 token

### 3.3 组件规则

- **全局控件**（按钮/输入框/滚动条/树/下拉/对话框等）由全局 QSS 统一负责，页面不重复写
- **页面局部样式**：用 `theme_engine.get(key)` 语义色拼 QSS 字符串（如 mode 按钮、卡片 hover）
- **右键菜单**：必须 `QMenu(self)` 用父组件初始化继承主题；**禁止**自定义 stylesheet 的 QMenu()
- **对话框/MessageBox**：颜色走全局 QSS，禁止局部硬编码
- **图标**：统一从 `icon_registry` / Codicon 取，禁止内置图片文件散落

### 3.4 聊天 UI 规范（微信风）

- 气泡对齐：用户消息**右对齐绿底**（`bubble_user_bg`），AI 消息**左对齐白底**（`bubble_ai_bg`）
- 气泡宽度：**自适应字符数**（不占满整行、不固定死宽）
- 堆叠方向：消息从**下往上**堆叠，最新在底部，滚动条跟随
- 实现位于 `widgets/chat_bubble.py` + `pages/chat_page.py`，改动气泡外观必须保留以上三点

### 3.5 按钮规范

- 文本按钮统一用 `gui/core/utils/widget_utils.py::fit_button_width()`：只设 `minimumWidth`，保留 sizeHint 自适应
- **禁止** `setFixedWidth` 文本按钮（字体/DPI 放大后文字溢出）
- 禁用态：`QPushButton:disabled` 已由全局 QSS 覆盖（disabled_bg），页面不重复写

### 3.6 换肤闭环

- 换肤 = `AppConfig.apply_preset/apply_skin` → 持久化 → `event_bus.publish(THEME_CHANGED)` → 组件自查刷新
- 组件收到 THEME_CHANGED 后：重新 `theme_engine.get()` 拼局部样式 + `apply_global` 级联
- 新组件必须订阅 THEME_CHANGED（或由全局 QSS 覆盖），否则换肤后残留旧色

---

## 四、GUI 配置规范

### 4.1 gui_config.json（项目根）

```jsonc
{
  "selected_preset": "default_light",   // 当前预设 id（与 selected_skin 互斥）
  "selected_skin": null,                // 当前皮肤包 id（可选）
  "theme": { "mode": "light", "accent_color": "#1a73e8", ... }, // token 字典
  "window": { "geometry": {"x":100,"y":100,"width":900,"height":680} },
  // 第三方写入的未知键原样保留（live2d_overlay 等）
}
```

- 读写唯一入口 `AppConfig`；写入走 `save()`（tmp+rename 原子写）
- `load()` 对未知键**保留**（不覆盖第三方扩展），对已知键做 dict 深度合并

### 4.2 节点配置（nodes/*/node_config.json）

- 各节点配置归**节点自己**（随节点走），GUI 设置面板经 read-modify-write 修改时保留其余键
- 例：AAA 的 `mode_keywords`（模式切换关键词）、`retrieval_gate` 等；由 `config.load_config()` 读取

### 4.3 共享协议文件（nodes/shared/）

- `gui_input.json` / `gui_reply.json` / `mode.json` / `dsh_task_in.json` / `dsh_question_in.json` / `dsh_answer_out.json` 为运行时协议文件，**不入库、不手改**，只经各模块原子读写
- 新增共享协议：先写方案文档 + 两侧读写方，再落 `nodes/shared/`，并同步更新本规范 2.5

### 4.4 工具清单（nodes/shared/gui_tool_schemas.json）

- 运行时由 `tool_registry.to_file()` 重新生成（启动时），**不手改**
- 工具数变化后如需一致性，跑一次 `to_file` 刷新

---

## 五、AI 操控 GUI 的规则

AI（AAA 节点）通过 22 个 `ui.*` 工具操控 GUI，规则：

1. **工具命名**：`ui.<verb>_<noun>`；GUI 管理类工具（预设/皮肤/导航/刷新）保留在工具桥；`dsh.*` 执行类**不走 GUI 工具桥**（直连 node_dsh 节点通道，见 [AAA直连DSH节点与模式切换方案](./[OK]-AAA直连DSH节点与模式切换方案.md)）
2. **破坏性变更**（覆盖预设、改配置等）走 `proposal_store` 提案机制，审批后才生效；导航/刷新/查询直发消息不改内部状态
3. **AI 改 GUI 代码**的强制项：
   - 新页面走 `ui_registry` 注册，禁在 main_window 硬编码
   - 颜色走 `theme_engine.get()`，禁裸色值
   - 消息用 `messages.py` 常量，禁拼字符串
   - 文本按钮用 `fit_button_width`，禁 `setFixedWidth`
   - 右键菜单用 `QMenu(self)`，禁自定义 stylesheet
   - 共享文件原子写，结果用 request_id/task_id 匹配
4. **AI 改完自检**：跑一遍本规范"六、审查清单"

---

## 六、审查清单

改 GUI（人或 AI）提交前逐项勾选：

- [ ] 颜色全部来自 `theme_engine.get()` / `get_all_colors()`，无裸色值
- [ ] 新页面已在 `ui_registry._register_builtin()` 注册（含 meta），main_window 无新硬编码
- [ ] 组件间协作走 event_bus + messages.py 常量，无互相 import 私有方法
- [ ] 文本按钮用 `fit_button_width`，无新增 `setFixedWidth`
- [ ] 右键菜单用父组件初始化，无自定义 stylesheet
- [ ] 聊天 UI 保持微信风（用户右绿 / AI 左白 / 宽度自适应 / 下往上堆叠）
- [ ] 订阅了 THEME_CHANGED（或由全局 QSS 覆盖），换肤不残留旧色
- [ ] 共享文件原子写；结果用 request_id/task_id 匹配
- [ ] 配置读写走 AppConfig/节点 config，未知键保留；不手改 nodes/shared/*.json 运行时文件
