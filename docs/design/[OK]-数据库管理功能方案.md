# 数据库管理功能方案

> 日期：2026-07-25 | 版本：v1.0 | 状态：[PLAN]

## 一、功能需求

在 GUI 上提供三个按钮，触发 AAA 节点执行数据库操作，结果反馈到 GUI：

1. **清空数据库** — 删除所有表的数据行，保留表结构
2. **备份数据库** — 复制当前 SQLite 文件到备份路径（带时间戳）
3. **恢复数据库** — 用选定的备份文件替换当前数据库

> "实际功能在 AAA 里"：GUI 仅负责触发和展示结果，所有 DB 操作由 `node_python_aaa_cognition/main.py` 执行。

---

## 二、通信协议

复用现有的文件协议通道，新增 `data_type: "db_command"` 路由。**listener.py 无需改动。**

### 2.1 GUI → AAA（请求）

文件：`nodes/shared/gui_input.json`

```json
{
  "data_type": "db_command",
  "source": "gui",
  "cmd": "clear|backup|restore",
  "params": {},
  "request_id": "a1b2c3d4"
}
```

- `cmd`：命令类型
- `params`：restore 时传 `{"backup_file": "chatbot_20260725_153000.db"}`

### 2.2 AAA → GUI（响应）

文件：`nodes/shared/gui_reply.json`

```json
{
  "data_type": "db_result",
  "cmd": "backup",
  "status": "ok",
  "message": "备份成功: chatbot_20260725_153000.db",
  "request_id": "a1b2c3d4"
}
```

`status` 为 `"ok"` 或 `"error"`，GUI 据此弹出对应的提示框。

### 2.3 数据流

```
GUI 按钮点击
  └─ MessageManager.send_db_command(cmd, params)
     └─ gui_input.json  {data_type:db_command, cmd, ...}
        └─ AAA listener 轮询到 → main.py.process()
           └─ _on_db_command(data, dbp)
              ├─ clear: 遍历所有表 DELETE FROM
              ├─ backup: shutil.copy2 → chatbot_TIMESTAMP.db
              └─ restore: shutil.copy2 备份文件 → chatbot.db
           └─ gui_reply.json  {data_type:db_result, cmd, status, message}
              └─ GUI poll_reply 检测到 db_result → 弹提示框
```

---

## 三、AAA 侧改动

### 3.1 main.py — 新增 `_on_db_command` 方法

在 `MyNode` 类中新增：

```python
import shutil
import glob
from datetime import datetime

def _on_db_command(self, data, dbp):
    """处理数据库管理命令：clear / backup / restore"""
    cmd = data.get("cmd", "")
    db_dir = os.path.dirname(dbp)
    db_name = os.path.basename(dbp)  # chatbot.db
    
    if cmd == "clear":
        conn = sqlite3.connect(dbp)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        count = 0
        for (tname,) in tables:
            conn.execute(f"DELETE FROM [{tname}]")
            count += conn.total_changes
        conn.commit()
        conn.close()
        return {"status": "ok", "message": f"已清空 {len(tables)} 张表，影响 {count} 行"}
    
    elif cmd == "backup":
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{os.path.splitext(db_name)[0]}_{ts}.db"
        backup_path = os.path.join(db_dir, backup_name)
        shutil.copy2(dbp, backup_path)
        return {"status": "ok", "message": f"备份成功: {backup_name}"}
    
    elif cmd == "restore":
        backup_file = (data.get("params") or {}).get("backup_file", "")
        if not backup_file:
            return {"status": "error", "message": "未指定备份文件"}
        backup_path = os.path.join(db_dir, backup_file)
        if not os.path.isfile(backup_path):
            return {"status": "error", "message": f"备份文件不存在: {backup_file}"}
        shutil.copy2(backup_path, dbp)
        return {"status": "ok", "message": f"已从 {backup_file} 恢复"}
    
    else:
        return {"status": "error", "message": f"未知命令: {cmd}"}
```

### 3.2 main.py — process() 新增路由

```python
# DB 管理命令（data_type: "db_command", source: "gui"）
if data_type == "db_command":
    return self._on_db_command(data, dbp)
```

插入在 `tool_result` 路由之后。

### 3.3 listener.py — 无需改动

`listener.py` 将 AAA `main.py.process()` 返回的 dict 整体写入 `gui_reply.json`（已有逻辑），`data_type: "db_result"` 的 item 自然透传。GUI 侧只需在 `poll_reply` 中增加对 `db_result` 的处理。

---

## 四、GUI 侧改动

### 4.1 message_manager.py — 新增 `send_db_command` 方法

复用 `gui_input.json` 文件通道，但**不走 `send_state` 状态锁**（DB 命令不参与聊天状态机）。新增方法：

```python
def send_db_command(self, cmd: str, params: dict = None):
    """发送数据库管理命令到 AAA（不占用发送状态锁）。"""
    data = {
        "data_type": "db_command",
        "source": "gui",
        "cmd": cmd,
        "params": params or {},
        "request_id": uuid.uuid4().hex[:8],
        "timestamp": datetime.now().isoformat(),
    }
    try:
        with open(GUI_INPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        self.error_occurred.emit(f"发送 DB 命令失败: {e}")
```

### 4.2 message_manager.py — poll_reply 增加 db_result 处理

在 `poll_reply` 末尾（`if reply_text:` 分支之后），增加对 `data_type == "db_result"` 的处理，通过新信号 `db_command_result` 通知 GUI：

```python
# DB 命令结果
if isinstance(content, dict) and content.get("data_type") == "db_result":
    db_result = content.get("data_type")
    cmd_name = content.get("cmd", "")
    status = content.get("status", "error")
    msg = content.get("message", "")
    self.db_command_result.emit(cmd_name, status, msg)
    return None  # 不与 reply 流程冲突
```

新增信号：

```python
db_command_result = Signal(str, str, str)  # cmd, status, message
```

### 4.3 settings_page.py — 新增"数据库管理"区域

在颜色选择器下方或右侧添加一个 `QGroupBox`"数据库管理"，包含：

- **清空数据库** 按钮 → `QMessageBox.question` 确认 → 调用 `send_db_command("clear")`
- **备份数据库** 按钮 → 直接调用 `send_db_command("backup")` → 弹出 QMessageBox.information 显示备份文件名
- **恢复数据库** 按钮 → 扫描备份目录列出可用备份 → 弹出选择对话框 → 确认后调用 `send_db_command("restore", {"backup_file": ...})`

所有按钮绑定 `db_command_result` 信号展示结果（成功弹 `information`，失败弹 `warning`）。

备份文件路径：DB 同级目录，命名 `chatbot_YYYYMMDD_HHMMSS.db`。

---

## 五、文件改动清单

| 文件 | 改动 |
|------|------|
| `nodes/node_python_aaa_cognition/main.py` | 新增 `_on_db_command` + `process()` 新增路由 |
| `gui/core/message_manager.py` | 新增 `send_db_command` 方法 + `db_command_result` 信号 + `poll_reply` 处理 `db_result` |
| `gui/pages/settings_page.py` | 新增"数据库管理"区域，三个按钮 + 交互（确认框/选择框/结果提示） |

**不涉及**：listener.py、任何 JS 文件、数据库表结构。

---

## 六、风险与边界

| 风险 | 等级 | 应对 |
|------|------|------|
| 清空操作不可撤销 | 中 | 清空前弹出确认对话框，显式提示"此操作不可撤销"。恢复操作同理需确认 |
| 恢复时数据库文件正被写入 | 中 | SQLite 允许读锁下的文件复制。恢复时 AAA 写操作完成后立即复制，时间窗口极短。极端情况可加 `conn.close()` 后 `time.sleep(0.1)` 再复制 |
| 备份文件累积 | 低 | 不做自动清理，用户可手动删除。可后续增加"最多保留 N 个"配置 |
| DB 路径未知 | 低 | 从 AAA `config.py` 的 `load_config()` 中读取 `db_path`，与 main.py 现有逻辑一致 |
| backup/restore 时 DB 不存在 | 低 | 函数入口检查 `os.path.isfile(dbp)`，不存在则返回 error |

---

## 七、测试计划

1. **清空**：点确认前取消 → 不清空。确认后 → 查 DB 各表为空、表结构保留。
2. **备份**：点击后备份目录生成 `chatbot_YYYYMMDD_HHMMSS.db`，内容可正常打开。
3. **恢复**：用刚生成的备份恢复 → DB 内容恢复至备份时刻。用不存在的文件名恢复 → 弹 error。
4. **流程**：备份 → 清空 → 确认空 → 恢复 → 确认内容恢复。
5. **回归**：正常聊天流程不受影响，`gui_input.json` / `gui_reply.json` 的 `data_type: text/reply` 依旧正常工作。
