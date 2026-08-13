# BNOS AI CLI TUI 终端管理方案

> **参考源**：`references/hermes-agent-main/hermes_cli/curses_ui.py`
> **目标**：复用 Hermes CLI TUI 组件，为 BNOS AI 构建一套终端管理工具

## 目录

- [一、方案概述](#一方案概述)
- [二、CLI 架构设计](#二cli-架构设计)
- [三、组件复用方案](#三组件复用方案)
- [四、子命令实现示例](#四子命令实现示例)
- [五、实施路线图](#五实施路线图)
- [六、验收标准](#六验收标准)
- [七、验收方法](#七验收方法)

---

## 一、方案概述

### 1.1 为什么需要 CLI TUI

BNOS AI 当前依赖 PySide6 GUI 进行交互，但在以下场景中，终端工具更高效：

| 场景 | 说明 |
|------|------|
| **远程服务器部署** | GUI 无法运行，需要终端管理 |
| **批量操作** | 批量启停节点、批量导入技能 |
| **调试开发** | 开发阶段快速查看状态、日志 |
| **资源受限** | GUI 占用大，终端更轻量 |
| **自动化脚本** | 通过 CLI 接口集成到 CI/CD 流程 |

### 1.2 Hermes CLI TUI 可复用组件

| 组件 | 源文件 | 复用价值 | 复用难度 |
|------|--------|----------|----------|
| **模糊搜索算法** | `curses_ui.py` → `_fuzzy_score()` | 跨平台生产级 fuzzy match | ⭐ 低 |
| **通用菜单循环** | `curses_ui.py` → `_run_curses_menu()` | 抽象化事件循环 | ⭐⭐ 中 |
| **多选清单** | `curses_ui.py` → `curses_checklist()` | 完整多选交互 | ⭐ 低 |
| **单选列表（带搜索）** | `curses_ui.py` → `curses_radiolist()` | 支持搜索的单选 | ⭐ 低 |
| **ANSI 颜色系统** | `colors.py` | 统一终端颜色 | ⭐ 低 |
| **子命令架构** | `subcommands/*.py` | argparse 子命令模式 | ⭐⭐ 中 |

---

## 二、CLI 架构设计

### 2.1 目录结构

```
bnos_cli/                      # CLI 工具根目录
├── __init__.py
├── main.py                    # 入口：bnos <subcommand>
├── fuzzy_search.py            # 🆕 复用 Hermes _fuzzy_score()
├── terminal_ui.py            # 🆕 复用 Hermes curses 组件
├── colors.py                  # 🆕 复用 Hermes colors.py
├── config.py                  # CLI 配置加载
└── subcommands/
    ├── __init__.py
    ├── nodes.py               # 节点管理
    ├── skills.py              # 技能管理
    ├── config_cmd.py          # 配置管理
    ├── memory.py              # 记忆管理
    ├── models.py              # 模型配置
    ├── status.py              # 系统状态
    └── logs.py                # 日志查看
```

### 2.2 命令体系

```
bnos
├── nodes                      # 节点管理
│   ├── list                   # 列出所有节点
│   ├── status <name>          # 查看节点状态
│   ├── start <name>           # 启动节点
│   ├── stop <name>            # 停止节点
│   ├── restart <name>         # 重启节点
│   ├── enable <name>          # 启用节点
│   ├── disable <name>         # 禁用节点
│   ├── batch-enable           # 批量启用（TUI 多选）
│   └── batch-disable          # 批量禁用（TUI 多选）
│
├── skills                     # 技能管理
│   ├── list                   # 列出已安装技能
│   ├── install <path>         # 安装技能
│   ├── uninstall <name>       # 卸载技能
│   ├── search <query>         # 搜索技能（TUI 可选）
│   └── batch-enable           # 批量启用（TUI 多选）
│
├── config                     # 配置管理
│   ├── show                   # 显示当前配置
│   ├── edit                   # 交互式编辑配置（TUI）
│   ├── get <key>              # 获取配置项
│   └── set <key> <value>      # 设置配置项
│
├── memory                     # 记忆管理
│   ├── stats                  # 记忆统计
│   ├── export <path>          # 导出记忆
│   ├── import <path>          # 导入记忆
│   ├── clear                  # 清空记忆
│   └── search <query>         # 搜索记忆（TUI 可选）
│
├── models                     # 模型配置
│   ├── list                   # 列出可用模型
│   ├── set <name>             # 设置当前模型（TUI 可选）
│   └── test                   # 测试模型连接
│
├── status                     # 系统状态
│   ├── engine                 # 引擎状态
│   ├── nodes                  # 所有节点状态
│   └── health                 # 健康检查
│
└── logs                       # 日志查看
    ├── tail                   # 实时查看日志
    ├── error                  # 查看错误日志
    └── clear                  # 清空日志
```

---

## 三、组件复用方案

### 3.1 模糊搜索算法复用

> **参考源**：`hermes_cli/curses_ui.py` → `_fuzzy_score()`, `_token_score()`

将 Hermes 的 fuzzy search 算法移植到 `bnos_cli/fuzzy_search.py`：

```python
"""模糊搜索算法 — 移植自 Hermes curses_ui.py

用于节点/技能/配置的交互式搜索选择。
保持与 Hermes UI 一致的排序规则：
- 连续匹配加分
- 词边界匹配加分
- 前缀匹配加分
- 精确匹配最高分
"""

from __future__ import annotations

from typing import List, Optional

_WORD_BOUNDARY = frozenset("-_/. ")


def _is_boundary(target: str, index: int) -> bool:
    """检查位置 index 是否为词边界"""
    if index == 0:
        return True
    prev = target[index - 1]
    if prev in _WORD_BOUNDARY:
        return True
    cur = target[index]
    return prev == prev.lower() and cur != cur.lower() and cur == cur.upper()


def _token_score(orig: str, lower: str, token: str) -> float | None:
    """计算单个 token 的匹配分数
    
    Returns:
        分数（float）或 None（不匹配）
    """
    score = 0.0
    prev = -1
    search_from = 0
    positions: list[int] = []
    
    for ch in token:
        idx = lower.find(ch, search_from)
        if idx < 0:
            return None
        
        positions.append(idx)
        score += 1
        
        # 连续匹配加分
        if prev >= 0 and idx == prev + 1:
            score += 5
        elif prev >= 0:
            score -= min(idx - prev - 1, 3)
        
        # 词边界匹配加分
        if _is_boundary(orig, idx):
            score += 3
        
        # 首字符匹配加分
        if idx == 0:
            score += 5
        
        prev = idx
        search_from = idx + 1
    
    # 前缀匹配额外加分
    if positions and positions[0] == 0 and positions[-1] == len(positions) - 1:
        score += 8
    
    # 精确匹配最高
    if lower == token:
        score += 20
    
    # 轻微偏好短目标
    score -= len(lower) * 0.01
    
    return score


def fuzzy_score(label: str, query: str) -> float | None:
    """多 token 查询的聚合分数
    
    Args:
        label: 待匹配文本
        query: 查询字符串（支持空格分隔的多 token）
    
    Returns:
        聚合分数或 None（任一 token 不匹配）
    """
    lower = label.lower()
    tokens = query.lower().split()
    
    if not tokens:
        return 0.0
    
    total = 0.0
    for token in tokens:
        token_score = _token_score(label, lower, token)
        if token_score is None:
            return None
        total += token_score
    
    return total


def fuzzy_search(items: list[str], query: str, 
                  limit: int = 20) -> list[tuple[str, float]]:
    """对列表执行模糊搜索并排序
    
    Args:
        items: 候选列表
        query: 查询字符串
        limit: 返回数量限制
    
    Returns:
        [(item, score), ...] 按分数降序排列
    """
    results = []
    for item in items:
        score = fuzzy_score(item, query)
        if score is not None:
            results.append((item, score))
    
    results.sort(key=lambda x: -x[1])
    return results[:limit]


def fuzzy_filter_indices(items: list[str], query: str) -> list[int]:
    """返回匹配项的索引列表（排序后）
    
    用于 TUI 菜单过滤。
    """
    q = query.strip()
    if not q:
        return list(range(len(items)))
    
    scored = []
    for i, label in enumerate(items):
        score = fuzzy_score(label, q)
        if score is not None:
            scored.append((i, score))
    
    scored.sort(key=lambda x: (-x[1], x[0]))
    return [i for i, _ in scored]
```

### 3.2 TUI 组件复用

> **参考源**：`hermes_cli/curses_ui.py` → `curses_radiolist()`, `curses_checklist()`

将 Hermes 的 TUI 组件简化移植到 `bnos_cli/terminal_ui.py`：

```python
"""终端 TUI 组件 — 借鉴 Hermes curses_ui.py

提供交互式菜单、选择列表等终端交互组件。
支持搜索、键盘导航、状态行等功能。
"""

from __future__ import annotations

import sys
from typing import Callable, List, Optional, Set

from bnos_cli.fuzzy_search import fuzzy_filter_indices


def is_tty() -> bool:
    """检查是否在 TTY 环境"""
    return sys.stdin.isatty()


def flush_stdin() -> None:
    """清理输入缓冲区"""
    try:
        if not sys.stdin.isatty():
            return
        import termios
        termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass


def _radio_numbered_fallback(
    title: str,
    items: List[str],
    selected: int,
    cancel_returns: int,
) -> int:
    """数字选择回退（无 curses 时使用）"""
    print(f"\n  {title}")
    print("  输入编号选择，回车确认。\n")
    
    for i, label in enumerate(items):
        marker = "●" if i == selected else "○"
        print(f"  {marker} {i + 1:>2}. {label}")
    print()
    
    try:
        val = input(f"  选择 [默认 {selected + 1}]: ").strip()
        if not val:
            return selected
        idx = int(val) - 1
        if 0 <= idx < len(items):
            return idx
        return selected
    except (ValueError, KeyboardInterrupt, EOFError):
        return cancel_returns


def _numbered_checklist_fallback(
    title: str,
    items: List[str],
    selected: Set[int],
    cancel_returns: Set[int],
) -> Set[int]:
    """多选清单回退"""
    chosen = set(selected)
    print(f"\n  {title}")
    print("  输入编号切换选择，回车确认。\n")
    
    while True:
        for i, label in enumerate(items):
            marker = "[✓]" if i in chosen else "[ ]"
            print(f"  {marker} {i + 1:>2}. {label}")
        print()
        try:
            val = input("  切换编号（或回车确认）: ").strip()
            if not val:
                break
            idx = int(val) - 1
            if 0 <= idx < len(items):
                chosen.symmetric_difference_update({idx})
        except (ValueError, KeyboardInterrupt, EOFError):
            return cancel_returns
        print()
    
    return chosen


def select_option(
    title: str,
    items: List[str],
    default_index: int = 0,
    searchable: bool = True,
    cancel_label: str = "取消",
) -> Optional[int]:
    """交互式单选列表（支持搜索）
    
    Args:
        title: 标题
        items: 选项列表
        default_index: 默认选中索引
        searchable: 是否支持 / 搜索
        cancel_label: 取消按钮文字
    
    Returns:
        选中索引，或 None（取消）
    """
    if not is_tty():
        return _radio_numbered_fallback(title, items, default_index, None)
    
    try:
        import curses
        return _curses_select(title, items, default_index, searchable, cancel_label)
    except Exception:
        return _radio_numbered_fallback(title, items, default_index, None)


def select_multiple(
    title: str,
    items: List[str],
    selected: Optional[Set[int]] = None,
    status_fn: Optional[Callable[[Set[int]], str]] = None,
) -> Set[int]:
    """交互式多选清单
    
    Args:
        title: 标题
        items: 选项列表
        selected: 初始选中集合
        status_fn: 状态行函数（返回状态文本）
    
    Returns:
        选中索引集合
    """
    if selected is None:
        selected = set()
    
    if not is_tty():
        return _numbered_checklist_fallback(title, items, selected, selected)
    
    try:
        import curses
        return _curses_checklist(title, items, selected, status_fn)
    except Exception:
        return _numbered_checklist_fallback(title, items, selected, selected)


def _curses_select(title: str, items: List[str], 
                   default_index: int, searchable: bool,
                   cancel_label: str) -> Optional[int]:
    """curses 单选实现"""
    import curses
    
    all_items = list(items) + [cancel_label]
    cancel_idx = len(items)
    chosen_idx = min(default_index, len(all_items) - 1)
    search_state = {"active": False, "query": ""}
    
    def draw_header(stdscr, max_y, max_x):
        row = 0
        stdscr.addnstr(row, 0, title, max_x - 1, curses.A_BOLD)
        row += 1
        
        if searchable and search_state["active"]:
            hint = f"  搜索: {search_state['query']}  BACKSPACE 删除  ESC 取消搜索"
        elif searchable:
            hint = "  ↑↓ 导航  ENTER 确认  / 搜索  ESC 取消"
        else:
            hint = "  ↑↓ 导航  ENTER 确认  ESC 取消"
        stdscr.addnstr(row, 0, hint, max_x - 1, curses.A_DIM)
        return row + 2
    
    def draw_row(stdscr, y, i, is_cursor, max_x):
        arrow = "→" if is_cursor else " "
        line = f" {arrow} {all_items[i]}"
        attr = curses.A_NORMAL
        if is_cursor:
            attr = curses.A_BOLD | curses.color_pair(1) if curses.has_colors() else curses.A_BOLD
        stdscr.addnstr(y, 0, line, max_x - 1, attr)
    
    def handle_action(action, cursor):
        if action == "select":
            return None if cursor >= cancel_idx else cursor
        return None  # cancel
    
    def _draw(stdscr):
        nonlocal chosen_idx
        curses.curs_set(0)
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, -1)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)
        
        cursor = chosen_idx
        scroll_offset = 0
        
        while True:
            stdscr.clear()
            max_y, max_x = stdscr.getmaxyx()
            
            # 过滤
            labels = all_items if searchable else all_items
            filtered = fuzzy_filter_indices(labels, search_state["query"]) if search_state["query"] else list(range(len(labels)))
            cursor_pos = filtered.index(cursor) if cursor in filtered else 0
            cursor = filtered[cursor_pos]
            
            items_start = draw_header(stdscr, max_y, max_x)
            visible_rows = max(1, max_y - items_start - 1)
            
            # 滚动
            if cursor_pos < scroll_offset:
                scroll_offset = cursor_pos
            elif cursor_pos >= scroll_offset + visible_rows:
                scroll_offset = cursor_pos - visible_rows + 1
            scroll_offset = max(0, min(scroll_offset, max(0, len(filtered) - visible_rows)))
            
            # 绘制行
            for draw_i, pos in enumerate(range(scroll_offset, min(len(filtered), scroll_offset + visible_rows))):
                i = filtered[pos]
                y = draw_i + items_start
                if y >= max_y - 1:
                    break
                draw_row(stdscr, y, i, i == cursor, max_x)
            
            stdscr.refresh()
            
            # 读取按键
            key = stdscr.getch()
            
            # 搜索处理
            if searchable and search_state["active"]:
                if key == 27:  # ESC
                    search_state["active"] = False
                    search_state["query"] = ""
                    continue
                elif key in (curses.KEY_BACKSPACE, 127, 8):
                    search_state["query"] = search_state["query"][:-1]
                    continue
                elif key in (curses.KEY_ENTER, 10, 13):
                    if filtered:
                        cursor = filtered[0]
                        if cursor >= cancel_idx:
                            return None
                        return cursor
                    continue
                elif 32 <= key < 127:
                    search_state["query"] += chr(key)
                    continue
                # 导航键继续处理
            elif searchable and key == ord("/"):
                search_state["active"] = True
                continue
            
            # 导航
            if key in (curses.KEY_UP, ord("k")):
                cursor_pos = (cursor_pos - 1) % len(filtered)
                cursor = filtered[cursor_pos]
            elif key in (curses.KEY_DOWN, ord("j")):
                cursor_pos = (cursor_pos + 1) % len(filtered)
                cursor = filtered[cursor_pos]
            elif key in (curses.KEY_ENTER, 10, 13):
                if cursor >= cancel_idx:
                    return None
                return cursor
            elif key == ord("q") or key == 27:
                return None
    
    try:
        curses.wrapper(_draw)
        flush_stdin()
        return chosen_idx if chosen_idx < cancel_idx else None
    except KeyboardInterrupt:
        return None


def _curses_checklist(title: str, items: List[str], 
                      selected: Set[int],
                      status_fn: Optional[Callable[[Set[int]], str]]) -> Set[int]:
    """curses 多选实现"""
    import curses
    
    chosen = set(selected)
    
    def draw_header(stdscr, max_y, max_x):
        row = 0
        stdscr.addnstr(row, 0, title, max_x - 1, curses.A_BOLD | curses.color_pair(2) if curses.has_colors() else curses.A_BOLD)
        row += 1
        stdscr.addnstr(row, 0, "  ↑↓ 导航  SPACE 切换  ENTER 确认  ESC 取消", max_x - 1, curses.A_DIM)
        return row + 2
    
    def draw_row(stdscr, y, i, is_cursor, max_x):
        check = "✓" if i in chosen else " "
        arrow = "→" if is_cursor else " "
        line = f" {arrow} [{check}] {items[i]}"
        attr = curses.A_NORMAL
        if is_cursor:
            attr = curses.A_BOLD | curses.color_pair(1) if curses.has_colors() else curses.A_BOLD
        stdscr.addnstr(y, 0, line, max_x - 1, attr)
    
    def draw_footer(stdscr, max_y, max_x):
        if status_fn:
            status_text = status_fn(chosen)
            if status_text:
                sx = max(0, max_x - len(status_text) - 1)
                stdscr.addnstr(max_y - 1, sx, status_text, max_x - sx - 1, curses.A_DIM)
    
    def _draw(stdscr):
        nonlocal chosen
        curses.curs_set(0)
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, -1)
            curses.init_pair(2, curses.COLOR_YELLOW, -1)
            curses.init_pair(3, 8, -1)
        
        cursor = 0
        
        while True:
            stdscr.clear()
            max_y, max_x = stdscr.getmaxyx()
            
            items_start = draw_header(stdscr, max_y, max_x)
            visible_rows = max(1, max_y - items_start - (2 if status_fn else 1))
            scroll_offset = 0
            
            # 调整滚动
            if cursor < scroll_offset:
                scroll_offset = cursor
            elif cursor >= scroll_offset + visible_rows:
                scroll_offset = cursor - visible_rows + 1
            
            # 绘制行
            for draw_i, pos in enumerate(range(scroll_offset, min(len(items), scroll_offset + visible_rows))):
                i = pos
                y = draw_i + items_start
                if y >= max_y - 1:
                    break
                draw_row(stdscr, y, i, i == cursor, max_x)
            
            if status_fn:
                draw_footer(stdscr, max_y, max_x)
            
            stdscr.refresh()
            
            # 读取按键
            key = stdscr.getch()
            
            if key in (curses.KEY_UP, ord("k")):
                cursor = (cursor - 1) % len(items)
            elif key in (curses.KEY_DOWN, ord("j")):
                cursor = (cursor + 1) % len(items)
            elif key == ord(" "):
                chosen.symmetric_difference_update({cursor})
            elif key in (curses.KEY_ENTER, 10, 13):
                return set(chosen)
            elif key == ord("q") or key == 27:
                return set(selected)
    
    try:
        curses.wrapper(_draw)
        flush_stdin()
        return chosen
    except KeyboardInterrupt:
        return set(selected)
```

### 3.3 颜色系统复用

> **参考源**：`hermes_cli/colors.py`

```python
"""终端颜色系统 — 借鉴 Hermes colors.py

提供统一的 ANSI 颜色代码定义。
"""

from __future__ import annotations


class Colors:
    """ANSI 颜色常量"""
    
    # 前景色
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # 亮色前景
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    
    # 背景色
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    
    # 样式
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"
    BLINK = "\033[5m"
    
    # 重置
    RESET = "\033[0m"
    NORMAL = "\033[0m"


def color(text: str, *colors: str) -> str:
    """为文本添加颜色"""
    prefix = "".join(colors)
    return f"{prefix}{text}{Colors.RESET}"


def bold(text: str) -> str:
    """加粗文本"""
    return color(text, Colors.BOLD)


def dim(text: str) -> str:
    """变暗文本"""
    return color(text, Colors.DIM)


def success(text: str) -> str:
    """成功消息"""
    return color(text, Colors.GREEN)


def error(text: str) -> str:
    """错误消息"""
    return color(text, Colors.RED)


def warning(text: str) -> str:
    """警告消息"""
    return color(text, Colors.YELLOW)


def info(text: str) -> str:
    """信息消息"""
    return color(text, Colors.CYAN)


def highlight(text: str) -> str:
    """高亮文本"""
    return color(text, Colors.BRIGHT_YELLOW, Colors.BOLD)
```

---

## 四、子命令实现示例

### 4.1 节点管理子命令

```python
"""节点管理子命令"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from bnos_cli.colors import (
    color, Colors, bold, success, error, warning, info
)
from bnos_cli.terminal_ui import select_option, select_multiple


def build_nodes_parser(subparsers):
    """创建 nodes 子命令解析器"""
    nodes_parser = subparsers.add_parser(
        "nodes",
        help="节点管理",
        description="管理 BNOS AI 的节点（列表、启停、配置等）"
    )
    nodes_subparsers = nodes_parser.add_subparsers(dest="nodes_action")
    
    # nodes list
    nodes_subparsers.add_parser("list", help="列出所有节点")
    
    # nodes status
    status_parser = nodes_subparsers.add_parser("status", help="查看节点状态")
    status_parser.add_argument("name", help="节点名称")
    
    # nodes start/stop/restart
    for action in ["start", "stop", "restart"]:
        parser = nodes_subparsers.add_parser(action, help=f"{action} 节点")
        parser.add_argument("name", help="节点名称")
    
    # nodes enable/disable
    for action in ["enable", "disable"]:
        parser = nodes_subparsers.add_parser(action, help=f"{action} 节点")
        parser.add_argument("name", help="节点名称")
    
    # nodes batch-enable/disable
    batch_enable = nodes_subparsers.add_parser("batch-enable", help="批量启用节点")
    batch_enable.add_argument("--interactive", "-i", action="store_true", 
                              help="使用交互式选择")
    
    batch_disable = nodes_subparsers.add_parser("batch-disable", help="批量禁用节点")
    batch_disable.add_argument("--interactive", "-i", action="store_true", 
                               help="使用交互式选择")
    
    nodes_parser.set_defaults(func=cmd_nodes)


def cmd_nodes(args):
    """nodes 子命令主入口"""
    action = args.nodes_action
    
    if action == "list":
        _list_nodes()
    elif action == "status":
        _show_status(args.name)
    elif action == "start":
        _start_node(args.name)
    elif action == "stop":
        _stop_node(args.name)
    elif action == "restart":
        _restart_node(args.name)
    elif action == "enable":
        _enable_node(args.name)
    elif action == "disable":
        _disable_node(args.name)
    elif action == "batch-enable":
        _batch_enable(getattr(args, "interactive", False))
    elif action == "batch-disable":
        _batch_disable(getattr(args, "interactive", False))
    else:
        print(error("请指定操作：list / status / start / stop / restart / enable / disable / batch-enable / batch-disable"))
        return 1
    
    return 0


def _get_nodes_status() -> list[dict]:
    """获取节点状态（模拟实现，实际对接 BNOS API）"""
    # TODO: 对接 BNOS 节点管理 API
    return [
        {"name": "llm_infer", "status": "running", "pid": 12345, "uptime": "2h 30m"},
        {"name": "aaa_cognition", "status": "running", "pid": 12346, "uptime": "2h 30m"},
        {"name": "asr_input", "status": "stopped", "pid": None, "uptime": "-"},
        {"name": "vlm_vision", "status": "running", "pid": 12347, "uptime": "1h 15m"},
    ]


def _list_nodes():
    """列出所有节点"""
    nodes = _get_nodes_status()
    
    print(f"\n{bold('节点列表')} ({len(nodes)} 个)\n")
    print(f"  {'名称':<20} {'状态':<10} {'PID':<10} {'运行时间'}")
    print(f"  {'─' * 20} {'─' * 10} {'─' * 10} {'─' * 10}")
    
    for node in nodes:
        status_color = Colors.GREEN if node["status"] == "running" else Colors.YELLOW
        status_display = color(node["status"], status_color)
        pid_display = str(node["pid"]) if node["pid"] else "-"
        print(f"  {node['name']:<20} {status_display:<18} {pid_display:<10} {node['uptime']}")
    
    print()


def _show_status(name: str):
    """显示单个节点状态"""
    nodes = _get_nodes_status()
    node = next((n for n in nodes if n["name"] == name), None)
    
    if not node:
        print(error(f"节点 '{name}' 不存在"))
        return 1
    
    status_color = Colors.GREEN if node["status"] == "running" else Colors.YELLOW
    
    print(f"\n{bold('节点详情')}")
    print(f"  名称: {info(node['name'])}")
    print(f"  状态: {color(node['status'], status_color)}")
    print(f"  PID:  {str(node['pid']) if node['pid'] else '-'}")
    print(f"  运行时间: {node['uptime']}")
    print()


def _start_node(name: str):
    """启动节点"""
    print(info(f"正在启动节点 '{name}'..."))
    # TODO: 对接 BNOS API
    print(success(f"节点 '{name}' 已启动"))


def _stop_node(name: str):
    """停止节点"""
    print(info(f"正在停止节点 '{name}'..."))
    # TODO: 对接 BNOS API
    print(success(f"节点 '{name}' 已停止"))


def _restart_node(name: str):
    """重启节点"""
    print(info(f"正在重启节点 '{name}'..."))
    # TODO: 对接 BNOS API
    print(success(f"节点 '{name}' 已重启"))


def _enable_node(name: str):
    """启用节点"""
    print(info(f"正在启用节点 '{name}'..."))
    # TODO: 对接 BNOS API
    print(success(f"节点 '{name}' 已启用"))


def _disable_node(name: str):
    """禁用节点"""
    print(info(f"正在禁用节点 '{name}'..."))
    # TODO: 对接 BNOS API
    print(success(f"节点 '{name}' 已禁用"))


def _batch_enable(interactive: bool = False):
    """批量启用节点"""
    nodes = _get_nodes_status()
    disabled = [n for n in nodes if n["status"] == "stopped"]
    
    if not disabled:
        print(warning("没有已停止的节点"))
        return 0
    
    names = [n["name"] for n in disabled]
    
    if interactive:
        print(bold("选择要启用的节点（空格切换，回车确认）："))
        selected_indices = select_multiple("批量启用节点", names)
        selected = [names[i] for i in selected_indices]
    else:
        selected = names
    
    if not selected:
        print(warning("未选择任何节点"))
        return 0
    
    print(f"\n将要启用 {len(selected)} 个节点：")
    for name in selected:
        print(f"  - {name}")
    
    # TODO: 对接 BNOS API 批量启用
    print(success(f"\n已启用 {len(selected)} 个节点"))


def _batch_disable(interactive: bool = False):
    """批量禁用节点"""
    nodes = _get_nodes_status()
    running = [n for n in nodes if n["status"] == "running"]
    
    if not running:
        print(warning("没有运行中的节点"))
        return 0
    
    names = [n["name"] for n in running]
    
    if interactive:
        print(bold("选择要禁用的节点（空格切换，回车确认）："))
        selected_indices = select_multiple("批量禁用节点", names)
        selected = [names[i] for i in selected_indices]
    else:
        selected = names
    
    if not selected:
        print(warning("未选择任何节点"))
        return 0
    
    print(f"\n将要禁用 {len(selected)} 个节点：")
    for name in selected:
        print(f"  - {name}")
    
    # TODO: 对接 BNOS API 批量禁用
    print(success(f"\n已禁用 {len(selected)} 个节点"))
```

---

## 五、实施路线图

### Phase 1：基础框架（2天）

| 任务 | 文件 | 产出 |
|------|------|------|
| 搭建 CLI 入口 | `bnos_cli/main.py` | argparse 主框架 |
| 实现 fuzzy search | `bnos_cli/fuzzy_search.py` | 模糊搜索算法 |
| 实现颜色系统 | `bnos_cli/colors.py` | ANSI 颜色 |
| 实现 TUI 组件 | `bnos_cli/terminal_ui.py` | select_option / select_multiple |
| 实现 config 加载 | `bnos_cli/config.py` | 配置读取 |

### Phase 2：核心子命令（3天）

| 任务 | 文件 | 产出 |
|------|------|------|
| nodes 子命令 | `subcommands/nodes.py` | 节点管理 |
| skills 子命令 | `subcommands/skills.py` | 技能管理 |
| status 子命令 | `subcommands/status.py` | 系统状态 |
| models 子命令 | `subcommands/models.py` | 模型配置 |

### Phase 3：扩展子命令（3天）

| 任务 | 文件 | 产出 |
|------|------|------|
| config 子命令 | `subcommands/config_cmd.py` | 配置管理 |
| memory 子命令 | `subcommands/memory.py` | 记忆管理 |
| logs 子命令 | `subcommands/logs.py` | 日志查看 |

### Phase 4：集成与优化（2天）

| 任务 | 产出 |
|------|------|
| 对接 BNOS API | 节点/技能/记忆操作真正可用 |
| 添加 shell 补全 | bash/zsh 自动补全脚本 |
| 编写帮助文档 | `bnos_cli --help` 完善 |

---

## 六、验收标准

- [ ] `bnos nodes list` 能正确显示节点状态
- [ ] `bnos nodes batch-enable -i` 能打开交互式多选界面
- [ ] `bnos skills search <query>` 支持模糊搜索
- [ ] 所有命令支持 `--help` 查看用法
- [ ] 颜色输出在支持 ANSI 的终端正常显示
- [ ] 非 TTY 环境自动降级到数字输入模式
- [ ] 代码结构清晰，子命令之间无循环依赖

---

## 七、验收方法

### 7.1 验收环境与前置条件

| 项 | 要求 |
|------|------|
| 操作系统 | Windows 10/11、Linux（Ubuntu 20.04+）、macOS 12+ |
| Python 版本 | Python 3.10 及以上 |
| 终端环境 | 支持 ANSI 颜色的终端（Windows Terminal / iTerm2 / GNOME Terminal） |
| TTY 环境 | 验收 TUI 交互时须在真实 TTY 终端中执行（非管道、非重定向） |
| 依赖安装 | `bnos_cli` 包已按 Phase 1 完成安装，`curses` 模块可用 |
| BNOS 运行时 | 主进程 `bnos_console.py` 可正常启动，`nodes/` 目录存在至少 4 个示例节点 |
| 测试数据 | 预置节点：llm_infer（running）、aaa_cognition（running）、asr_input（stopped）、vlm_vision（running） |
| 非 TTY 验证 | 通过管道方式触发：`echo "" \| bnos nodes batch-enable -i` |
| 验收工具 | 计时器（用于性能项）、支持 ANSI 颜色的终端模拟器 |

### 7.2 功能验收用例

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| F1 | 节点列表展示 | 1. 启动终端<br>2. 执行 `bnos nodes list` | 输出表头"名称/状态/PID/运行时间"，列出 4 个节点；running 显示绿色，stopped 显示黄色；PID 与运行时间正确 | 表格列对齐，颜色区分正确，节点数量与预置数据一致 | 核心 |
| F2 | 单节点状态查看 | 1. 执行 `bnos nodes status llm_infer` | 输出"节点详情"块，含名称、状态、PID、运行时间四项；状态带颜色 | 字段完整，状态名与 list 中一致 | 核心 |
| F3 | 启动节点 | 1. 执行 `bnos nodes start asr_input` | 输出 info 色"正在启动节点 'asr_input'..."，随后输出 success 色"节点 'asr_input' 已启动" | 提示信息颜色正确，进程返回码 0 | 核心 |
| F4 | 停止节点 | 1. 执行 `bnos nodes stop llm_infer` | 输出 info 色"正在停止节点..."，随后输出 success 色"节点 'llm_infer' 已停止" | 提示信息颜色正确，返回码 0 | 核心 |
| F5 | 重启节点 | 1. 执行 `bnos nodes restart vlm_vision` | 输出 info 色"正在重启节点..."，随后输出 success 色"节点 'vlm_vision' 已重启" | 提示信息颜色正确，返回码 0 | 核心 |
| F6 | 启用/禁用节点 | 1. 执行 `bnos nodes enable asr_input`<br>2. 执行 `bnos nodes disable aaa_cognition` | 两条命令均输出对应 info/success 提示消息 | 提示信息颜色正确，返回码 0 | 核心 |
| F7 | 批量启用（非交互） | 1. 执行 `bnos nodes batch-enable` | 列出已停止节点（asr_input），输出"将要启用 1 个节点"清单，最终输出"已启用 1 个节点" | 列表正确，数量统计正确 | 核心 |
| F8 | 批量启用（交互式 TUI） | 1. 执行 `bnos nodes batch-enable -i`<br>2. 在 TUI 中用方向键导航、空格勾选、回车确认 | 弹出 curses 多选界面，标题"批量启用节点"，显示已停止节点；空格可切换勾选；确认后输出启用结果 | 界面正常渲染，勾选状态正确更新，结果与选择一致 | 核心 |
| F9 | 批量禁用（交互式 TUI） | 1. 执行 `bnos nodes batch-disable -i`<br>2. 选择部分 running 节点并回车确认 | 弹出 curses 多选界面，列出 running 节点（llm_infer/aaa_cognition/vlm_vision）；确认后输出禁用结果 | 界面正常，结果与选择一致 | 核心 |
| F10 | TUI 单选界面 | 1. 调用 `select_option("测试", ["选项A","选项B","取消"])`<br>2. 用 ↑↓ 导航，回车确认 | 显示标题与提示行"↑↓ 导航 ENTER 确认 / 搜索 ESC 取消"；光标行加粗高亮；回车返回选中索引 | 导航正常，返回值与选中项一致 | 核心 |
| F11 | TUI 搜索过滤 | 1. 在单选/多选界面按 `/` 进入搜索<br>2. 输入查询字符串<br>3. 按 ESC 退出搜索 | 进入搜索模式后底部显示"搜索: \<query\>"；列表实时按 fuzzy_score 过滤排序；ESC 退出恢复全部列表 | 过滤结果符合 fuzzy 算法排序规则（前缀/连续匹配优先） | 核心 |
| F12 | 模糊搜索算法 | 1. 调用 `fuzzy_search(["llm_infer","aaa_cognition","asr_input"], "llm")`<br>2. 检查返回结果排序 | 返回 `[("llm_infer", score), ...]`；前缀匹配的 llm_infer 排首位；不匹配项被过滤 | 排序符合前缀加分、连续匹配加分、词边界加分规则 | 核心 |
| F13 | 颜色系统输出 | 1. 依次调用 `success("ok")`、`error("fail")`、`warning("warn")`、`info("msg")`<br>2. 在支持 ANSI 的终端打印 | 输出分别带绿色、红色、黄色、青色 ANSI 转义码；末尾均含 RESET | ANSI 码正确，每段均以 RESET 闭合 | 核心 |
| F14 | 帮助信息完整性 | 1. 执行 `bnos --help`<br>2. 执行 `bnos nodes --help`<br>3. 执行 `bnos nodes list --help` | 主命令列出 7 个子命令；nodes 列出 9 个子动作；list 显示用法说明 | 帮助文本完整，无缺失子命令 | 核心 |
| F15 | 子命令无循环依赖 | 1. 检查 `subcommands/nodes.py` 等文件的 import 关系<br>2. 运行 `python -c "import bnos_cli.main"` | 各子命令仅依赖 `colors`、`terminal_ui`、`config`，子命令之间无相互 import；主模块可正常导入无报错 | import 关系无环，导入成功 | 核心 |

### 7.3 边界与异常验收

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| E1 | 非 TTY 降级 | 1. 执行 `echo "" \| bnos nodes batch-enable -i`（管道非 TTY） | 自动降级为数字编号选择模式，输出"输入编号切换选择，回车确认" | `is_tty()` 返回 False 时走 fallback 分支，不调用 curses | 核心 |
| E2 | 节点不存在 | 1. 执行 `bnos nodes status not_exist_node` | 输出红色错误"节点 'not_exist_node' 不存在"，返回码 1 | 错误提示清晰，返回码非 0 | 核心 |
| E3 | 无可操作节点 | 1. 假设全部节点 running，执行 `bnos nodes batch-enable` | 输出黄色警告"没有已停止的节点"，返回码 0 | 空列表场景有友好提示，不报错 | 核心 |
| E4 | curses 异常回退 | 1. 在 curses 不可用环境（或模拟异常）触发 `select_option` | 捕获异常后回退到 `_radio_numbered_fallback` 数字选择模式 | 异常被 except 捕获，不崩溃，降级可用 | 核心 |
| E5 | 中断取消处理 | 1. 在 TUI 多选界面按 ESC<br>2. 另一次按 Ctrl+C | ESC 返回初始选中集合；Ctrl+C 返回初始选中集合不崩溃 | 中断返回合理默认值，无异常抛出 | 核心 |
| E6 | 大列表滚动性能 | 1. 构造 500 个节点的列表<br>2. 触发 `select_multiple` 并连续按 ↓ 50 次 | 列表可正常滚动，光标跟随，无明显卡顿 | 单次按键响应 < 100ms，滚动边界正确 | 非核心 |
| E7 | 空查询显示全部 | 1. 在搜索模式清空查询字符串（连续 BACKSPACE）<br>2. 检查列表 | `fuzzy_filter_indices` 空查询时返回全部索引，列表恢复完整 | 空查询等价于无过滤，列表项数 == 候选总数 | 非核心 |
| E8 | 超长节点名显示 | 1. 构造节点名长度 > 20 的节点<br>2. 执行 `bnos nodes list` | 表格列宽自适应或截断，不破坏整体行布局 | 布局不错乱，可读性可接受 | 非核心 |

### 7.4 验收结论判定标准

| 验收等级 | 判定标准 |
|------|---------|
| **通过** | 所有"核心"项全部通过 |
| **附条件通过** | 核心项全通过，非核心项 ≤2-3 项不通过且有补救计划 |
| **不通过** | 任一核心项不通过 |

#### 验收记录模板

```
# BNOS CLI TUI 终端管理方案 验收记录

> 验收日期：______-______-______  验收人：____________  环境：____________

## 功能验收用例

- [ ] F1  节点列表展示                [核心]   结果：□通过 □不通过  备注：________
- [ ] F2  单节点状态查看              [核心]   结果：□通过 □不通过  备注：________
- [ ] F3  启动节点                    [核心]   结果：□通过 □不通过  备注：________
- [ ] F4  停止节点                    [核心]   结果：□通过 □不通过  备注：________
- [ ] F5  重启节点                    [核心]   结果：□通过 □不通过  备注：________
- [ ] F6  启用/禁用节点               [核心]   结果：□通过 □不通过  备注：________
- [ ] F7  批量启用（非交互）          [核心]   结果：□通过 □不通过  备注：________
- [ ] F8  批量启用（交互式 TUI）      [核心]   结果：□通过 □不通过  备注：________
- [ ] F9  批量禁用（交互式 TUI）      [核心]   结果：□通过 □不通过  备注：________
- [ ] F10 TUI 单选界面               [核心]   结果：□通过 □不通过  备注：________
- [ ] F11 TUI 搜索过滤               [核心]   结果：□通过 □不通过  备注：________
- [ ] F12 模糊搜索算法               [核心]   结果：□通过 □不通过  备注：________
- [ ] F13 颜色系统输出               [核心]   结果：□通过 □不通过  备注：________
- [ ] F14 帮助信息完整性             [核心]   结果：□通过 □不通过  备注：________
- [ ] F15 子命令无循环依赖           [核心]   结果：□通过 □不通过  备注：________

## 边界与异常验收

- [ ] E1  非 TTY 降级                [核心]   结果：□通过 □不通过  备注：________
- [ ] E2  节点不存在                 [核心]   结果：□通过 □不通过  备注：________
- [ ] E3  无可操作节点               [核心]   结果：□通过 □不通过  备注：________
- [ ] E4  curses 异常回退            [核心]   结果：□通过 □不通过  备注：________
- [ ] E5  中断取消处理               [核心]   结果：□通过 □不通过  备注：________
- [ ] E6  大列表滚动性能             [非核心] 结果：□通过 □不通过  备注：________
- [ ] E7  空查询显示全部             [非核心] 结果：□通过 □不通过  备注：________
- [ ] E8  超长节点名显示             [非核心] 结果：□通过 □不通过  备注：________

## 验收结论

□ 通过        □ 附条件通过        □ 不通过

核心项不通过清单：__________________________________________________
非核心项不通过清单：________________________________________________
补救计划：__________________________________________________________

验收人签字：____________  日期：______-______-______
```