# 日志系统设计方案

> 状态: [OK] 已确认
> 日期: 2026-08-07
> 关联模块: gui/, bnos_runtime/

## 一、背景与问题

### 现状
- **GUI 日志**: 无持久化，仅 `print()` 到控制台
- **引擎日志**: `engine.py` 用 `_p()` → `print()`，走 stdout，无文件
- **节点日志**: `standalone_runner.py` 中 `stdout=DEVNULL, stderr=DEVNULL`，**完全丢弃**

### 痛点
1. 节点崩溃无法排查（日志丢了）
2. GUI 报错无历史记录（重启后消失）
3. 无法按启动批次追溯问题

## 二、设计原则

1. **按启动批次隔离**: GUI 启动/停止为一个批次，所有日志存同一目录
2. **分层收集**: GUI 日志 GUI 收，引擎+节点日志 bnos_runtime 收
3. **最小侵入**: 不改现有接口，通过可选参数扩展
4. **源头优先**: 先改 `E:\杂项\bnos`（编辑器源头），再同步到 `BNOS_AI_project`

## 三、目录结构

```
BNOS_AI_project/
  └── logs/
      └── 20250807_143052/       ← 启动批次 (时间戳)
          ├── app.log           ← GUI 运行日志 (INFO+)
          ├── error.log         ← GUI 错误日志 (ERROR+)
          └── engine/
              ├── engine.log    ← 引擎日志
              └── nodes/
                  ├── node_chat.log
                  ├── node_tts.log
                  └── ...
```

## 四、改动清单

### 4.1 bnos_runtime/standalone_runner.py (源头: E:\杂项\bnos)

**改动**: `start()` 方法增加可选 `log_dir` 参数

```python
def start(self, log_dir: Path | None = None) -> tuple[str, subprocess.Popen]:
    log_fh = None
    if log_dir:
        node_log = Path(log_dir) / "nodes" / f"{self.node_id}.log"
        node_log.parent.mkdir(parents=True, exist_ok=True)
        log_fh = open(node_log, "a", encoding="utf-8")

    # 两处 Popen 调用 (exe 分支 + Python 分支):
    #   stdout=log_fh, stderr=log_fh  ← 原来是 DEVNULL 或 None
```

**向后兼容**: `log_dir=None` 时行为不变

### 4.2 bnos_runtime/engine.py (源头: E:\杂项\bnos)

**改动**:

| 位置 | 改动 |
|------|------|
| `PipelineRunner.__init__` | 增加 `log_dir: Path \| None = None` 参数 |
| `PipelineRunner._p()` | 同时写 `engine.log` |
| `PipelineRunner._start_node()` | `runner.start(log_dir=self._log_dir)` |

```python
def __init__(self, pipeline_path: Path, log_dir: Path | None = None):
    ...
    self._log_dir = log_dir

def _p(self, *args, **kwargs):
    print(*args, **kwargs, flush=True)
    if self._log_dir:
        log_file = Path(self._log_dir) / "engine.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            print(*args, **kwargs, flush=True, file=f)

def _start_node(self, node_id: str):
    ...
    nid, proc = runner.start(log_dir=self._log_dir)
```

### 4.3 gui/core/logger.py (新建)

GUI 日志系统，职责:
- 创建批次目录 `logs/YYYYMMDD_HHMMSS/`
- 双文件 handler: `app.log` (INFO+) + `error.log` (ERROR+)
- 控制台 handler (INFO+)
- `sys.excepthook` → 未捕获异常写入 error.log

```python
def setup_gui_logger() -> Path:
    """创建批次目录，配置 handler，返回批次目录路径"""

def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger"""

def get_batch_dir() -> Path | None:
    """获取当前批次目录"""
```

### 4.4 gui/main.py

```python
from gui.core.logger import setup_gui_logger
_batch_dir = setup_gui_logger()

# 启动引擎时传递批次目录
env["BNOS_LOG_DIR"] = str(_batch_dir / "engine")
```

### 4.5 gui/pages/node_page.py

```python
# 读取环境变量
log_dir = env.get("BNOS_LOG_DIR")
if log_dir:
    proc = subprocess.Popen(
        [python_exe, "-m", "bnos_runtime.engine", str(pipeline_path),
         "--serve", "--log-dir", log_dir],
        ...
    )
```

## 五、error.log 收集范围

| 来源 | 说明 |
|------|------|
| `logger.error()` / `logger.critical()` | GUI 显式错误 |
| `sys.excepthook` | 未捕获 Python 异常 |
| 节点内部 traceback | 子进程 stderr → `nodes/{node_id}.log` |
| 引擎启动失败 | `engine.log` 中的 FAILED 行 |

## 六、实现步骤

| # | 操作 | 文件 | 路径 |
|---|------|------|------|
| 1 | 修改源头 | standalone_runner.py | `E:\杂项\bnos\bnos_runtime\` |
| 2 | 修改源头 | engine.py | `E:\杂项\bnos\bnos_runtime\` |
| 3 | 同步副本 | standalone_runner.py | `BNOS_AI_project/bnos_runtime/` |
| 4 | 同步副本 | engine.py | `BNOS_AI_project/bnos_runtime/` |
| 5 | 新建 | logger.py | `BNOS_AI_project/gui/core/` |
| 6 | 修改 | main.py | `BNOS_AI_project/gui/` |
| 7 | 修改 | node_page.py | `BNOS_AI_project/gui/pages/` |

## 七、向后兼容性

| 场景 | 行为 |
|------|------|
| BNOS 编辑器使用 | `log_dir=None`，节点 stdout/stderr 继承父进程，不变 |
| AI 项目使用 | 传 `log_dir`，节点日志写入文件 |
| 旧代码调用 `runner.start()` | 无参数，默认 `log_dir=None`，行为不变 |
| 旧代码构造 `PipelineRunner(path)` | 无 `log_dir`，行为不变 |
