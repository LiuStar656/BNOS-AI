# GUI 重建设计方案

> 日期：2026-07-24 | 版本：v2.0 | 状态：[WIP]

## 目录

- [一、背景与现状评估](#一背景与现状评估)
- [二、目标](#二目标)
- [三、方案设计](#三方案设计)
  - [3.1 整体布局](#31-整体布局)
  - [3.2 色彩方案](#32-色彩方案)
  - [3.3 模块文件结构](#33-模块文件结构)
  - [3.4 核心组件设计](#34-核心组件设计)
    - [3.4.1 MainWindow](#341-mainwindow)
    - [3.4.2 Sidebar](#342-sidebar)
    - [3.4.3 ChatBubble](#343-chatbubble)
    - [3.4.4 StatusBar](#344-statusbar)
  - [3.5 聊天页（ChatPage）](#35-聊天页chatpage)
  - [3.6 其他标签页](#36-其他标签页)
  - [3.7 数据流架构](#37-数据流架构)
  - [3.8 状态管理](#38-状态管理)
  - [3.9 输入状态机](#39-输入状态机)
  - [3.10 组件交互时序](#310-组件交互时序)
- [四、分阶段实施计划](#四分阶段实施计划)
  - [Phase 0 — 核心框架](#phase-0--核心框架)
  - [Phase 1 — 功能增强](#phase-1--功能增强)
  - [Phase 2 — 完善](#phase-2--完善)
- [五、风险与注意事项](#五风险与注意事项)

---

## 一、背景与现状评估

### 当前状态

当前 BNOS_AI_project 的 GUI（`gui/main.py`，约 420 行）是一个极简的 PySide6 聊天窗口：

- 单页面布局，无功能分区
- 消息气泡样式简陋，居中显示
- 未实现发送状态锁，可在上次处理完成前再次输入
- 无多页面/标签页支持
- 无 Live2D 预览、节点管理、MCP 管理等功能入口
- 配色与样式接近编辑器风格，不符合聊天应用预期

### 问题汇总

| 问题 | 影响 |
|------|------|
| 消息气泡居中而非左右对齐 | 不符合 QQ/微信用户习惯，阅读体验差 |
| 无发送状态锁 | 连续发送导致阻塞或重复处理 |
| 无多标签页架构 | 无法扩展 Live2D/节点管理/MCP 等功能 |
| 编辑器风格过重 | 用户期望明亮聊天风格而非深色编辑器 |
| UI 过于简陋 | 缺乏状态栏、加载指示等基本交互反馈 |
| 组件散落主文件 | 所有逻辑写在单个 main.py 中，难以维护 |

---

## 二、目标

1. 重新设计 GUI 架构，采用**左侧标签栏 + 内容区**的浏览器式布局
2. 消息气泡改为**用户靠右（绿色底）/ AI 靠左（白色底）** 的 QQ/微信风格
3. 实现**发送状态锁**，防止未处理完时重复输入
4. 预留多页面扩展能力：聊天、Live2D、节点管理、MCP 管理、设置
5. 采用**明亮/浅色主题**，符合聊天应用视觉风格
6. 代码中不使用 emoji（以 codicon 图标替代）
7. 按模块拆分组件，每个子目录有 README.md，遵循 BNOS 项目文件组织规范

---

## 三、方案设计

### 3.1 整体布局

```
+------------------------------------------------------------------+
|  +--+-----------------------------------------------------------+ |
|  |  |  [BNOS AI]                      - 口 x                    | |
|  |  +-----------------------------------------------------------+ |
|  |  |                                                             | |
|  |  |  内容区 (QStackedWidget)                                    | |
|  |  |  +------------------------------------------------------+  | |
|  |  |  |  AI 气泡（靠左，白色底 + 阴影）                       |  | |
|  |  |  +------------------------------------------------------+  | |
|  |  |                                                             | |
|  |  |           +--------------------------------------------+  | |
|  |  |           | 用户气泡（靠右，绿色底 #95ec69）           |  | |
|  |  |           +--------------------------------------------+  | |
|  |  |                                                             | |
|  |  +-----------------------------------------------------------+ |
|  |  |  输入区域 (QLineEdit + [发送] 按钮)                        | |
|  |  +-----------------------------------------------------------+ |
|  |  |  状态栏: 在线 | 模型: xxx                                  | |
|  +--+-----------------------------------------------------------+ |
|  |                                                                 |
|  +-- 左侧标签栏 (固定宽 56px, 竖排图标)                            |
+------------------------------------------------------------------+
```

- **左侧标签栏**：固定宽度 56px，竖排 QPushButton + codicon 图标
- **内容区**：QStackedWidget 切换不同页面，默认显示聊天页
- **底部状态栏**：全局状态显示，跨页面保持

### 3.2 色彩方案

| 元素 | 颜色值 | 说明 |
|------|--------|------|
| 窗口背景 | `#f5f5f5` | 浅灰 |
| 侧边栏 | `#ffffff` | 白色 |
| 选中标签态 | `#e8f0fe` (底) / `#1a73e8` (图标) | 浅蓝选中 |
| 聊天区背景 | `#f0f2f5` | 浅灰 |
| AI 气泡 | `#ffffff` + 阴影 `rgba(0,0,0,0.08)` | 靠左 |
| 用户气泡 | `#95ec69` | 靠右，微信绿 |
| 输入框 | `#ffffff` | 白色 |
| 发送按钮 | `#1a73e8` | 蓝色 |
| 状态栏文字 | `#666666` | 灰色 |

### 3.3 模块文件结构

```
gui/
 ├── main.py                          # 入口：创建 QApplication + MainWindow
 ├── main_window.py                   # 主窗口：Sidebar + QStackedWidget 组合
 │
 ├── core/                            # 核心基础设施
 │   ├── __init__.py
 │   ├── state.py                     # 全局状态管理（Singleton）
 │   ├── event_bus.py                 # 组件间信号/槽解耦
 │   ├── message_manager.py           # 消息收发管理（轮询 + 状态锁）
 │   └── README.md
 │
 ├── widgets/                         # 可复用 UI 组件
 │   ├── __init__.py
 │   ├── sidebar.py                   # 左侧标签栏
 │   ├── chat_bubble.py               # 消息气泡组件
 │   ├── status_bar.py                # 底部状态栏
 │   └── README.md
 │
 ├── pages/                           # 标签页（每个页面对应一个标签）
 │   ├── __init__.py
 │   ├── chat_page.py                 # 聊天页（默认页）
 │   ├── live2d_page.py               # Live2D 预览（占位）
 │   ├── node_page.py                 # 节点管理仪表盘
 │   ├── mcp_page.py                  # MCP 工具管理
 │   ├── settings_page.py             # 设置页
 │   └── README.md
 │
 ├── resources/                       # 静态资源
 │   ├── __init__.py
 │   ├── theme.py                     # 明亮主题 QSS
 │   ├── icons/
 │   │   ├── codicon.py               # codicon 字体加载与图标映射
 │   │   └── Codicon.ttf              # 图标字体文件
 │   └── README.md
 │
 └── dialogs/                         # 独立对话框
     ├── __init__.py
     ├── log_viewer.py                # 实时日志查看器
     └── README.md
```

**模块职责与依赖关系**：

```
main.py
  └── main_window.py
        ├── core/state.py              ← 全局状态
        ├── core/event_bus.py          ← 组件通信
        ├── core/message_manager.py    ← 数据收发
        ├── widgets/sidebar.py         ← 标签切换
        ├── widgets/status_bar.py      ← 状态显示
        └── pages/chat_page.py         ← 聊天界面
              ├── widgets/chat_bubble.py
              ├── widgets/status_bar.py
              └── resources/theme.py
```

**禁止跨层依赖**：
- `widgets/` 不能 import `pages/` 中的模块
- `pages/` 可以 import `widgets/` 和 `core/`
- `core/` 不能 import `widgets/` 或 `pages/`
- 所有组件通过 `event_bus.py` 间接通信，避免直接信号/槽耦合

### 3.4 核心组件设计

#### 3.4.1 MainWindow

```
class MainWindow(QMainWindow):
    """主窗口 — 左侧 Sidebar + 右侧 QStackedWidget + 顶部标题栏"""

    COMPONENTS:
        - sidebar: Sidebar              # 左侧标签栏
        - stack: QStackedWidget         # 页面容器
        - pages: dict[str, QWidget]     # 页面索引 {"chat": ChatPage, ...}

    FLOW:
        1. __init__() 创建布局、实例化所有页面
        2. 连接 sidebar.page_changed 信号到 stack.setCurrentIndex()
        3. 默认显示 chat_page
```

#### 3.4.2 Sidebar

```
class Sidebar(QWidget):
    """左侧标签栏 — 竖排图标按钮，点击切换页面"""

    SIGNALS:
        page_changed(str)    # 发射 page_id

    ATTRIBUTES:
        TABS: list[tuple] = [
            ("chat",     "chat",      "聊天"),
            ("live2d",   "live2d",    "Live2D"),
            ("node",     "node",      "节点管理"),
            ("mcp",      "mcp",       "MCP 管理"),
            ("settings", "settings",  "设置"),
        ]
        # 格式: (codicon_name, page_id, tooltip)

    METHODS:
        + set_active(page_id: str)      # 设置选中标签

    INTERNAL:
        - _btn_group: QButtonGroup      # 单选互斥
        - _create_btn(icon_name, tooltip) -> QPushButton
```

#### 3.4.3 ChatBubble

```
class ChatBubble(QWidget):
    """消息气泡组件 — 左右对齐，自适应宽度"""

    PARAMS:
        text: str        # 消息文本
        role: str        # "user" | "ai"
        time: str        # 时间戳（可选）

    LAYOUT:
        user:  [stretch] [bubble: green bg (#95ec69)] [avatar(预留)]
        ai:    [avatar(预留)] [bubble: white bg + shadow] [stretch]

    METHODS:
        + set_text(text: str)           # 更新文本
        + append_text(text: str)        # 追加文本（流式输出用）
```

#### 3.4.4 StatusBar

```
class StatusBar(QWidget):
    """底部状态栏 — 全局状态显示"""

    DISPLAY:
        - 引擎状态: 在线 / 离线 / 启动中
        - 当前模型: 通义千问 / GPT-4o / ...
        - 节点数量: 在线 N / 总共 M

    METHODS:
        + update_engine_status(status: str)
        + update_model(name: str)
        + update_nodes(online: int, total: int)
```

### 3.5 聊天页（ChatPage）

```
class ChatPage(QWidget):
    """聊天页 — 消息列表 + 输入框 + 发送按钮"""

    COMPONENTS:
        - scroll_area: QScrollArea      # 消息列表容器
        - message_layout: QVBoxLayout   # 消息气泡排列
        - input_box: QLineEdit          # 文本输入框
        - send_btn: QPushButton         # 发送按钮

    STATE:
        - _state: "idle" | "sending"    # 发送状态锁
        - _timeout_timer: QTimer        # 超时恢复

    METHODS:
        + append_message(text, role)    # 添加消息气泡
        + clear_messages()              # 清空聊天记录
        - _send_message()               # 发送文本
        - _on_reply_received(text)      # 收到回复
```

**发送状态锁逻辑**：

```
IDLE ──点击发送──> SENDING
                     │  (禁用输入框 + 按钮)
                     │
              轮询到AI回复
              ──或─→ 超时(60s)
                     │
                     v
                   IDLE
                   (恢复输入框 + 按钮)
```

### 3.6 其他标签页

| 页面 | 类名 | 说明 | 初始内容 |
|------|------|------|----------|
| 聊天 | `ChatPage` | 默认页，消息 + 输入 | 全功能聊天界面 |
| Live2D | `Live2DPage` | 角色预览 | 居中占位文字 "Live2D 预览（待集成）" |
| 节点管理 | `NodePage` | 节点状态仪表盘 | 从 gui_status.json 读取并显示节点列表 |
| MCP 管理 | `MCPPage` | MCP 工具管理 | 居中占位文字 "MCP 管理（待开发）" |
| 设置 | `SettingsPage` | 配置管理 | 模型选择下拉框 + API Key 输入 |

### 3.7 数据流架构

GUI 与后端的通信沿用现有文件协议，不引入新 IPC 机制：

```
┌──────────────────────────────────────────────────────────────────┐
│  GUI 层                                                            │
│                                                                    │
│  ChatPage ──写入──> gui_input.json ──> gui_adapter 节点 ──> ...     │
│                                                                    │
│  ChatPage <──轮询── output.json (aaa_cognition 的产出)              │
│                                                                    │
│  NodePage <──轮询── gui_status.json (各节点状态)                    │
│                                                                    │
│  SettingsPage ──写入──> node_config.json (修改配置)                 │
└──────────────────────────────────────────────────────────────────────┘
```

**写入路径**（用户输入）：
```
[输入框] → ChatPage._send_message()
         → json.dump → shared/gui_input.json
         → gui_adapter listener 检测到 → 转发到 user_input → ...
```

**读取路径**（AI 回复）：
```
[MessageManager 轮询] → 读取 aaa_cognition/output.json
                      → 解析 data_type == "reply"
                      → ChatPage.append_message(text, "ai")
```

**状态读取路径**：
```
[NodePage 轮询] → 读取 shared/gui_status.json
                → 解析 nodes 列表 → 更新 UI 树
```

### 3.8 状态管理

使用集中式状态管理器（Singleton 模式），替代组件间直接传参：

```
class AppState(metaclass=Singleton):
    """全局应用状态"""

    ATTRIBUTES:
        engine_status: str = "offline"       # offline | starting | online | error
        current_model: str = ""              # 当前使用的模型
        nodes: dict[str, NodeState] = {}     # 节点状态快照
        send_state: str = "idle"             # idle | sending

    SIGNALS (通过 EventBus):
        engine_status_changed(str)
        model_changed(str)
        nodes_updated(dict)
        send_state_changed(str)
```

```
class Singleton(ABCMeta):
    """确保整个应用只有一个状态实例"""
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]
```

### 3.9 输入状态机

```
                   ┌──────────┐
         点击发送  │          │  超时(60s) / 收到回复
    ┌────────────>│ SENDING  │────────────┐
    │             │          │            │
    │             └──────────┘            │
    │                                      │
    │                                      │
    │  ┌──────────┐                        │
    └──│          │<───────────────────────┘
       │  IDLE    │
       │          │
       └──────────┘
```

| 状态 | 输入框 | 发送按钮 | 占位文字 |
|------|--------|----------|----------|
| IDLE | 可用 | 可用 | "输入消息..." |
| SENDING | 禁用 | 禁用 | "发送中..." |

### 3.10 组件交互时序

```
用户输入文本
    │
    v
ChatPage._send_message()
    │
    ├── 1. 检查 send_state == "idle"? 否则忽略
    ├── 2. 设置 send_state = "sending"
    ├── 3. 禁用输入框/按钮
    ├── 4. json.dump → gui_input.json
    │
    v
[等待后端处理]
    │
    v
MessageManager._poll_reply() (每 500ms)
    │
    ├── 1. 读取 aaa_cognition/output.json
    ├── 2. 检查 mtime/size/哈希是否有变化
    ├── 3. 解析 data_type == "reply"
    ├── 4. 发射 reply_received(text) 信号
    │
    v
ChatPage._on_reply_received(text)
    │
    ├── 1. append_message(text, "ai")
    ├── 2. 设置 send_state = "idle"
    ├── 3. 恢复输入框/按钮
    └── 4. 清除超时计时器
```

---

## 四、分阶段实施计划

### Phase 0 — 核心框架

目标：可用的聊天界面，替换现有 main.py。

**文件创建顺序**：

```
Step 1: gui/resources/         — 主题 QSS + codicon 图标
         gui/core/             — state.py, event_bus.py, message_manager.py
Step 2: gui/widgets/          — sidebar.py, chat_bubble.py, status_bar.py
Step 3: gui/main_window.py    — 主窗口框架
Step 4: gui/pages/            — chat_page.py 全功能 + 其他页面占位
Step 5: gui/main.py           — 新入口
```

**交付标准**：
- 左侧 5 个标签页可切换
- 聊天页正确显示消息气泡（用户靠右绿底，AI 靠左白底）
- 发送状态锁生效，无法重复发送
- AI 回复正常显示
- 明亮主题完整

### Phase 1 — 功能增强

- 实现 SettingsPage（模型选择、API Key 配置）
- 实现 NodePage（从 gui_status.json 读取并显示节点状态仪表盘）
- 实现 Live2DPage（占位视图 + 后续集成准备）
- 实现 StatusBar（显示引擎/节点/模型状态）
- 集成 Toast 通知系统

### Phase 2 — 完善

- 实现 MCPPage（MCP 工具列表 + 开关控制）
- 实现 LogViewer 对话框（复用原 BNOS 组件）
- 消息历史记录管理（本地存储 + 加载）
- 对话导出/导入
- 主题切换（预留）

---

## 五、风险与注意事项

| 风险 | 应对 |
|------|------|
| 发送状态锁可能超时 | 设置 60s 超时 Timer，超时自动恢复 IDLE |
| Live2D 集成复杂度未知 | Phase 1 先放占位图，后续单独评估集成方案 |
| codicon.ttf 文件兼容性 | 使用 QFontDatabase.addApplicationFont() 加载，备选回退字符 |
| 页面间轮询冲突 | MessageManager 独立运行，不受页面切换影响 |
| 与现有 gui/main.py 冲突 | 新架构独立目录，旧文件保留为 `gui/legacy_main.py` 作为参考 |
| 模块循环依赖 | 严格遵守依赖方向：core → widgets → pages → main_window |

> 本文档遵循 [BNOS 开发规范](../../节点开发规范.md) 的设计方案模板。
