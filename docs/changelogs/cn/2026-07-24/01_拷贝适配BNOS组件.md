# 01 从 BNOS 参考项目拷贝并适配可复用 UI 组件

---

## 摘要

- **核心改动**：参考 `referencees/BNOS---Bionic-Neural-Network-Visual-Orchestration-Platform-main` 项目的 UI 架构，将其中通用、可复用的组件拷贝到本项目的 `gui/core/` 下，并进行主题适配和依赖清理
- **根因**：BNOS 参考项目包含成熟的桌面端 UI 基础设施（对话框系统、Toast 通知、线程池、快捷键管理等），直接复用可避免重复造轮子，同时保持架构一致性
- **影响**：新增 3 个模块共 9 个文件，GUI 层现在拥有完整的基础设施套件

---

## 详细说明

### 一、问题描述

本项目的 GUI 前端（`gui/`）此前仅有核心的事件总线、状态管理和消息轮询组件，缺少通用的 UI 工具类（对话框、文件操作、日志查看）、通知系统（Toast）和系统基础设施（线程池、快捷键管理）。需要从成熟的 BNOS 参考项目中借鉴和复用这些组件。

### 二、方案设计

#### 1. 模块划分

| 模块 | 目录 | 包含文件 | 职责 |
|------|------|----------|------|
| 工具类 | `gui/core/utils/` | `dialog_utils.py` `file_utils.py` `log_viewer.py` | 通用 UI 工具函数 |
| 通知系统 | `gui/core/toast/` | `toast_notification.py` `toast_queue_manager.py` | 右上角自动消失的通知弹窗 |
| 系统基础设施 | `gui/core/system/` | `thread_pool.py` `shortcut_manager.py` | 跨组件系统服务 |

#### 2. 适配策略

拷贝后的适配工作集中在以下方面：

- **主题转换**：BNOS 使用深色主题（`#1e1e1e` 背景、`#cccccc` 文字），本项目改为明亮主题（`#ffffff` 背景、`#333333` 文字、`#1a73e8` 主色调）
- **依赖清理**：移除 BNOS 特定模块引用（`ui.core.i18n`、`ui.core.logger`），改为内联实现或直接移除
- **功能裁剪**：移除与 BNOS 特有功能绑定的代码（如画布 dock 定位、节点路径查找等）
- **快捷键重置**：将快捷键默认值改为适配聊天场景（`Ctrl+Enter` 发送、`Ctrl+N` 新对话等）

#### 3. 各文件适配详情

##### `dialog_utils.py`
- 保留 `ThemedDialogBase` 基类（frameless 窗口 + 半透明背景 + 自绘标题栏）
- 保留 `themed_input`、`themed_message`、`show_text_dialog` 三个便捷函数
- 新增 `show_text_dialog`（BNOS 原文中无，按需新增）
- 颜色常量全部替换为明亮主题色
- 移除 `_get_drives`、`_load_lazy_dir_items`、`_create_nav_bar`、`pick_folder` 等与文件浏览器绑定的函数

##### `file_utils.py`
- 保留 `get_project_root`、`open_terminal_in_directory` 核心函数
- 新增 `open_folder`（简化版）
- 新增 `ensure_dir`（目录创建辅助）
- 移除 `resolve_and_open_folder`（与节点系统绑定的路径查找）
- 所有依赖 `themed_message` 的错误提示改为 `return False` 静默失败

##### `log_viewer.py`
- 保留 `show_log_dialog` 函数
- 移除 `ui.core.i18n` 依赖，关闭按钮文字改为硬编码"关闭"
- 保持极简风格（QDialog + QTextEdit + QPushButton）

##### `toast_notification.py`
- 保留完整的双层架构（外层透明窗口 + 内层 QLabel）
- 保留 60fps 淡入淡出动画（PreciseTimer 驱动）
- 保留窗口跟随逻辑（eventFilter 监听 Move/Resize/Activate/Deactivate）
- 颜色配置全部替换为明亮白色系（info=白、success=浅绿、warning=浅橙、error=浅红）
- 移除与画布 dock 关闭按钮对齐的逻辑

##### `toast_queue_manager.py`
- 保留完整的单例模式、FIFO 队列、智能替换、堆叠显示逻辑
- 移除 `ui.core.logger` 依赖
- 核心结构无变化（纯逻辑代码，无主题相关内容）

##### `thread_pool.py`
- 保留完整的 QRunnable 封装 + 单例模式
- 移除 `ui.core.logger` 依赖
- 保留 `run_task`、`cancel`、`wait_for_done`、`shutdown` 完整接口

##### `shortcut_manager.py`
- 保留完整的注册表模式（DEFAULTS + get/set/reset/save）
- 快捷键默认值从 BNOS 编辑场景改为聊天场景
- 移除 `QAction` 批量应用逻辑和 `MenuManager` 依赖

#### 4. 与现有组件的集成

新增组件与已有 `gui/core/` 下的组件（`event_bus.py`、`state.py`、`message_manager.py`）配合关系：

```
event_bus.py ← state.py ← message_manager.py
                                ↓ (通过 thread_pool 做后台轮询)
utils/
  ├── dialog_utils.py ── 被 pages/*.py 和 dialogs/*.py 调用
  ├── file_utils.py ──── 被 pages/*.py 调用
  └── log_viewer.py ──── 被 node_page.py 调用
toast/
  ├── toast_notification.py ── 被 main_window.py 初始化
  └── toast_queue_manager.py ── 全局单例，各处调用
system/
  ├── thread_pool.py ──── 全局单例，被 message_manager.py 使用
  └── shortcut_manager.py ── 被 main_window.py 使用
```

### 三、BNOS 源码参考

以下为适配依据的 BNOS 参考项目文件（位于 `referencees/` 目录）：

| 本文件 | 参考源文件 |
|--------|-----------|
| `gui/core/utils/dialog_utils.py` | `referencees/.../ui/core/utils/dialog_utils.py` |
| `gui/core/utils/file_utils.py` | `referencees/.../ui/core/utils/file_utils.py` |
| `gui/core/utils/log_viewer.py` | `referencees/.../ui/core/utils/log_viewer.py` |
| `gui/core/toast/toast_notification.py` | `referencees/.../ui/core/toast/toast_notification.py` |
| `gui/core/toast/toast_queue_manager.py` | `referencees/.../ui/core/toast/toast_queue_manager.py` |
| `gui/core/system/thread_pool.py` | `referencees/.../ui/core/system/thread_pool.py` |
| `gui/core/system/shortcut_manager.py` | `referencees/.../ui/core/system/shortcut_manager.py` |

---

## 验证方法

1. 导入测试：`from gui.core.utils.dialog_utils import ThemedDialogBase, themed_message, themed_input` 无报错
2. 导入测试：`from gui.core.toast.toast_queue_manager import ToastQueueManager` 无报错
3. 导入测试：`from gui.core.system.thread_pool import thread_pool` 无报错
4. 导入测试：`from gui.core.system.shortcut_manager import ShortcutManager` 无报错
