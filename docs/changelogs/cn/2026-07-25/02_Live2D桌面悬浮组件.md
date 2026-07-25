# 02 — Live2D 桌面悬浮组件

> 日期：2026-07-25 | 涉及文件：11 | 变更类型：新增功能

---

## 一、功能概述

新增完整的 Live2D 桌面悬浮窗系统，包含：

1. **桌面悬浮窗（Live2DOverlay）**：无边框透明窗口，支持拖拽移动、缩放、Ctrl+滚轮缩放模型、鼠标跟随
2. **预览管理页（live2d_page）**：模型列表、服务启停、Live2D Server 配置
3. **HTTP Server 集成**：基于 Node.js `express` + `live2d-viewer` 的模型托管服务

---

## 二、核心组件设计

### 2.1 Live2DOverlay 桌面悬浮窗

```python
class Live2DOverlay(QWidget):
    """Live2D 桌面悬浮窗。无边框、透明，普通窗口层级。"""

    CONFIG_KEY = "live2d_overlay"
    SCALE_KEY = "live2d_model_scale"
    SERVER_PORT = 3000
    RESIZE_MARGIN = 12
```

**关键特性：**

| 特性 | 实现方式 |
|------|---------|
| 无边框透明 | `FramelessWindowHint` + `WA_TranslucentBackground` + `setAutoFillBackground(False)` |
| 窗口拖拽 | `mousePressEvent` / `mouseMoveEvent` 中移动窗口 |
| 右下角缩放 | `_in_resize_area()` 判定，`SizeFDiagCursor` 光标 |
| Ctrl+滚轮缩放 | 在 Python 侧计算 `_model_scale`，通过 `runJavaScript` 发送绝对值给前端 |
| 鼠标跟随 | 节流（~30fps）转发 `setMouseFocus(x, y)` 到 JS |
| 右键菜单 | `contextMenuEvent` 弹出"关闭"选项 |
| 尺寸持久化 | `_save_geometry()` / `_restore_geometry()` 存储到 `AppConfig` |

### 2.2 预览管理页

在 `live2d_page.py` 中新增：

- **模型列表**：列出 `live2d-models/` 目录下的所有 `.model3.json` 文件，支持切换
- **服务控制**：启动/停止 Live2D HTTP Server（子进程管理）
- **端口配置**：支持自定义 Server 端口
- **启动超时**：Server 启动失败时自动回退为本地静态文件服务
- **缩放设置**：滑块调节模型缩放比例

### 2.3 状态管理集成

在 `bnos_status.json` 中添加 Live2D Server 状态字段：

```json
{
  "nodes": {
    "live2d_server": {
      "pid": 12345,
      "status": "running",
      "port": 3000
    }
  }
}
```

---

## 三、依赖配置

### requirements.txt 补充

```text
# 仅 live2d_page.py 需要
PySide6-QtWebEngine  # 全平台 WebEngine
```

### Live2D Server 依赖

```json
// gui_config.json
{
  "live2d_server_port": 3000,
  "live2d_server_path": ".live2d-server",
  "live2d_model_scale": 0.35
}
```

---

## 四、影响范围

| 模块 | 改动 |
|------|------|
| `gui/widgets/live2d_overlay.py` | 新增：桌面悬浮窗组件（233 行） |
| `gui/pages/live2d_page.py` | 大幅扩展：模型管理、服务控制、配置面板（+445 行） |
| `gui/main_window.py` | 集成 Live2DOverlay 显示/隐藏快捷键 |
| `gui/core/config.py` | 新增 Live2D 相关配置项 |
| `gui_config.json` | 新增 `live2d_server_port`、`live2d_model_scale` |
| `bnos_status.json` | 新增 `live2d_server` 状态 |
| `.gitignore` | 新增 `live2d-models/`、`.live2d-server/` 过滤规则 |

---

## 五、设计决策

| 决策 | 理由 |
|------|------|
| 使用 `Tool` 而非 `ToolTip` 窗口标志 | `Tool` 可被点击置顶，同时被其他窗口覆盖，行为自然 |
| Python 侧计算缩放 | 避免 JS 浮点累积误差，且值可直接持久化 |
| 节流鼠标跟随 | 避免 `runJavaScript` 调用过频（限制 ~30fps） |
| Server 超时回退 | 用户无 Node.js 环境时仍可使用本地静态页面 |

---

## 六、验证方法

1. 启动 GUI，切换到 Live2D 标签页
2. 点击启动 Live2D Server（需 Node.js 环境）
3. 选中一个模型，点击"设为桌面悬浮"
4. 验证悬浮窗可拖拽、缩放、Ctrl+滚轮缩放模型
5. 重启 GUI，验证悬浮窗位置/尺寸恢复

---

## 七、修改文件清单

| 文件 | 改动 |
|------|------|
| `gui/widgets/live2d_overlay.py` | 新增：桌面悬浮窗完整实现 |
| `gui/pages/live2d_page.py` | 重写：模型管理、服务控制、配置面板 |
| `gui/main_window.py` | 集成 Live2DOverlay 显示逻辑 |
| `gui/core/config.py` | 新增 Live2D 配置 Key |
| `gui_config.json` | 新增配置项 |
| `bnos_status.json` | 新增节点状态 |
| `.gitignore` | 新增忽略规则 |

---

**最后更新**：2026-07-25
