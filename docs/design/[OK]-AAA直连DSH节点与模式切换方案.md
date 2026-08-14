# AAA 直连 DSH 节点与日常/工作模式方案

> 日期：2026-08-14 | 版本：v1.1 | 状态：[OK]（v1.0 已全部实施落地）

## 目录

1. [背景与现状评估](#一背景与现状评估)
2. [目标](#二目标)
3. [方案设计](#三方案设计)
4. [分阶段实施计划](#四分阶段实施计划)
5. [风险评估](#五风险评估)
6. [测试计划](#六测试计划)
7. [影响范围](#七影响范围)
8. [实施记录](#八实施记录)

---

## 一、背景与现状评估

### 1.1 问题

1. **AAA 转发 DSH 绕道 GUI**：node_dsh 本是标准 BNOS 节点（listener 轮询
   `nodes/shared/dsh_task_in.json` → filter `data_type=dsh_task` → 执行 → 写 `output.json`），
   但当前链路是 AAA → gui_tools.call_tool → GUI ToolBridge（文件通道，**GUI 必须在线**）
   → ToolRegistry `dsh.run_task` → 写同一文件。多余一跳 + 引入 GUI 依赖。
2. **DSH 结果不回流**：`dsh.run_task` 异步提交，AAA 拿到「已提交」即回复用户，
   不等完成、结果不转述（用户期望：转发 → DSH 完成 → 结果回 AAA → 转述）。
3. **全部请求走 LLM 判断**：无日常/工作模式区分，每轮都拼完整上下文发 LLM 判断
   「直接回复还是工具调用」，工作类请求（本就要 DSH）白白花判断成本。

### 1.2 已具备

| 能力 | 实现 |
|---|---|
| node_dsh 节点通道 | `port_mappings.task → ..\shared\dsh_task_in.json`；`task_id` 回带（main.py L187-190）；filter 匹配 |
| GUI 回复通道 | AAA listener 将 `data_type=reply` 输出额外写 `gui_reply.json`（GUI MessageManager 轮询） |
| GUI 工具桥 | ToolRegistry + ToolBridge（含 dsh.run_task / run_task_sync / check_task） |
| 设置面板 | `gui/pages/settings_panel.py`（可承载模式关键词配置） |

### 1.3 已确认决策（2026-08-14）

- DSH 工具**彻底迁移到节点通道**（从 GUI 工具桥移除 dsh.* 工具，AAA 直连 node_dsh）
- DSH 任务**异步回执**（先回复「已提交」，后台轮询完成后主动推送结果）
- **日常/工作模式**：手动按钮 + 自动关键词（NLP）结合切换
- 工作模式直通：**AAA 带完整上下文直接发 DSH**（上下文含自我认知/记忆/历史/用户信息）

---

## 二、目标

1. AAA 直连 node_dsh：转发不依赖 GUI，纯 BNOS 节点文件协议
2. DSH 结果闭环：提交 → 异步执行 → 完成 → 结果主动推送给用户
3. 日常/工作双模式：工作模式跳过 LLM 判断层、带完整上下文直通 DSH；
   切换支持手动（GUI 按钮）与自动（可配置关键词）
4. 工作模式交互仍入记忆系统（消息入库，便于日后检索），但不产认知节

---

## 三、方案设计

### 3.1 共享 DSH 客户端（节点通道，GUI 无关）

`nodes/node_python_aaa_cognition/dsh_client.py`（AAA 侧；GUI workflow 复用同一协议）：

```python
# 写任务文件（原子替换，带唯一 task_id）
def submit_task(task: str, session_id: str = "", context: dict | None = None) -> dict:
    """写 nodes/shared/dsh_task_in.json：
       {data_type: dsh_task, task_id, task, session_id?, context?}"""

# 读结果（task_id 精确匹配）
def read_result(task_id: str) -> dict | None:
    """读 nodes/node_dsh/output.json；task_id 不匹配返回 None（任务未完成/旧结果）"""
```

- 不依赖 GUI 进程；node_dsh listener 持续运行（BNOS 引擎负责）
- `task_id` 由 AAA 生成（uuid4 hex12），node_dsh 原样回带（main.py 已支持）
- **context 字段**：工作模式直通时携带 AAA 完整上下文（见 3.4），
  node_dsh main.py 拼入 task 前缀（"背景上下文 + 用户请求"）

### 3.2 GUI 工具桥移除 dsh.*

- `gui/core/tool_registry.py`：移除 `dsh.run_task` / `dsh.run_task_sync` / `dsh.check_task`
  注册（AI 工具清单 25 → 22，不再暴露 DSH 给 AI 经 GUI 调用；`dsh.preset_*` 管理工具保留）
- `gui/core/workflow_store.py`：流程步骤若含 `dsh.*`，改为直接调用节点通道
  （同协议——写 dsh_task_in.json + task_id 轮询），不经工具注册表
  - 实现：workflow_store 的 `run()` 对 `dsh.*` 前缀走专用分支（同步等待语义保留）

### 3.3 AAA 侧工具调用分发改造（main.py `_on_parsed`）

现状 ③ 工具调用分支：`gui_tools.call_tool(tname, targs)`（一律走 GUI）。
改造：

```
LLM 输出【工具调用】
  ├─ tname 以 "dsh." 开头
  │    → dsh_client.submit_task（直连节点，不经 GUI）
  │    → 立即返回 reply「任务已提交，完成后我会告诉你」
  │    → 后台线程轮询 read_result(task_id)
  │        → 完成 → 写 gui_reply.json（data_type=reply, content=最终回答,
  │                                      request_id=原请求 id）→ GUI 显示
  └─ 其他工具（ui.* 等）
       → 保持 gui_tools.call_tool（GUI 工具桥仅服务 UI 类操作）
```

- 后台线程参考 `_trigger_background_review` 模式（daemon thread）
- 超时 600s 与 node_dsh 一致；超时回复「任务仍在执行，可再问我进展」
- DSH 结果回带的 `session_id` 由 AAA 记录（`_dsh_session_id`），多轮续接

### 3.4 日常/工作模式

#### 3.4.1 模式状态

`nodes/shared/mode.json`（GUI 与 AAA 共享，仅存模式本身）：

```jsonc
{
  "mode": "daily"                    // "daily" | "work"
}
```

切换关键词**配置在 AAA 自己的 node_config.json**（`mode_keywords` 段），
GUI 设置面板读写同一文件（read-modify-write 保留其余配置）：

```jsonc
"mode_keywords": {
  "work":  ["进入工作模式", "开始工作模式", "切到工作模式", "工作模式"],
  "daily": ["进入日常模式", "退出工作模式", "回到日常模式", "切回日常模式", "日常模式"]
}
```

> 设计调整说明：v1.0 原拟 keywords 与 mode 同放 mode.json；实施时改为
> keywords 归 AAA 配置自治（节点配置随节点走），mode.json 只存运行时状态，
> 降低跨进程并发写同一文件的冲突面。

#### 3.4.2 切换方式（手动 + 自动）

- **手动**：GUI 聊天页顶部「日常/工作」切换按钮 → 原子写 `mode.json`
  （按钮状态每秒同步，AAA 关键词自动切换后 GUI 保持一致）
- **自动**：AAA `_on_text` 入口 NLP 检测（`mode_manager.try_switch`，子串匹配；
  多个词同时命中时按词长优先，如「退出工作模式」优先于「工作模式」）：
  - 命中 work 词 → 切 work 模式 + 回复「已切换到工作模式…」
  - 命中 daily 词 → 切 daily + 回复「已切换到日常模式…」
  - 切换指令不写库、不触发 LLM
  - 关键词改动放 GUI 设置面板（settings_panel「模式切换关键词」分组）

#### 3.4.3 工作模式链路（直通，跳过 LLM 判断）

```
用户输入 → AAA._on_text
  ├─ NLP 检测切换关键词？→ 切换 + 回复（不执行任务）
  ├─ 当前 mode == "work"？
  │    ├─ 组装完整上下文（_gather_context 产出的 ctx：
  │    │    自我认知/固定认知/最近感受/记忆/历史摘要/用户信息）
  │    ├─ dsh_client.submit_task(task=用户输入, context=ctx)
  │    ├─ 立即回复「已提交」+ 后台轮询（同 3.3）
  │    └─ 完成 → 推送结果 + 消息写库（role=tool，不产认知节）
  └─ 当前 mode == "daily"？→ 现有链路（LLM 判断）
```

- 写库：用户消息（role=user）与 DSH 回答（role=tool）入库，仅沉淀事实不做认知演化
- context 拼装：task 前缀注入背景（DDL 长任务/需要身份的请求由 DSH 带背景执行）；
  列表字段（self_cognition 等）join 为字符串后再传入
- 会话续接：工作模式多轮对话用 session_id 续接（node_dsh 已支持 DSH_SESSION_ID）

### 3.5 与 workflow 的关系

- 流程步骤含 dsh.* 时 workflow_store 直连节点（3.2），同步等待语义保留
- 工作模式直通 ≠ 流程：工作模式是"用户输入 → DSH"；流程是"AI 选流程 → 多步执行"

---

## 四、分阶段实施计划

### Phase 0：dsh_client 模块（纯新增，无行为变更） ✅ 已完成

- AAA 侧 `dsh_client.py`：submit_task / read_result / wait_result / push_reply / node_ready
- 单元冒烟：写文件 → 读回 → task_id 匹配

### Phase 1：AAA 工具分发改造 + 异步回执 ✅ 已完成

- main.py 工具分支：dsh.* 直连 + 异步回执（后台线程 + gui_reply.json 推送）
- node_dsh main.py：context 字段拼入 task 前缀
- 验证：GUI 在线/离线均可提交；DSH 完成后结果自动显示

### Phase 2：模式状态 + 切换 ✅ 已完成

- mode_manager.py（mode.json 读写 + try_switch 关键词检测）+ node_config.json `mode_keywords`
- GUI 聊天页顶部切换按钮（chat_page.py）+ settings_panel 关键词编辑分组
- AAA `_on_text` NLP 切换 + work 模式直通分支（完整上下文 + 写库）

### Phase 3：GUI 工具桥移除 dsh.* + workflow 适配 ✅ 已完成

- tool_registry 移除 3 工具（25→22）；tool_bridge `_HEAVY_TOOLS` 清空
- workflow_store run() 对 dsh.* 前缀走 `_run_dsh_direct` 节点直连（同步等待语义保留）
- 回归：GUI 预设/工具开关等不受影响；AI 清单 22 工具

---

## 五、风险评估

| 风险 | 缓解 |
|---|---|
| gui_reply.json 与 listener 并发写 | 后台线程写前锁（listener 已有 WRITE_LOCK 思路）；写后 GUI mtime/hash 判新 |
| 异步回执 request_id 被 GUI 过滤 | 推送沿用原请求 request_id（poll_reply 同 id 放行）；若用户已发新消息则旧结果被合理丢弃 |
| node_dsh 无 listener 运行 | submit 前检查 node_config 存在；失败回退提示「DSH 节点未运行」 |
| 工作模式完整上下文使 task 超长 | context 截断（如 4000 字符）；LLM token 上限可控 |
| 关键词误触发 | 关键词仅精确子串匹配；设置面板可见可改；切换均有回复确认 |
| workflow 移除 dsh 工具后旧流程引用 | run() 对 dsh.* 前缀走直连分支，兼容既有流程定义 |

## 六、测试计划

- 单元：dsh_client submit/read/task_id 匹配；关键词 NLP（enter/exit 命中与误触）✅
- 集成（offscreen/CLI）：AAA 工具分支 dsh.* 直连（GUI 未启动时提交成功）；
  后台轮询完成后 gui_reply.json 内容正确 ✅
- 模式：GUI 按钮切 work → 输入 → 直通 DSH → 结果回流；关键词切换 + 恢复 ✅
- 端到端：真实 DSH 任务（工作模式）→ 最终回答显示；日常模式回归聊天（待运行环境实测）
- 回归：GUI 25→22 工具清单；workflow 流程含 dsh 步骤仍可执行 ✅

## 七、影响范围

| 文件 | 改动 |
|---|---|
| `nodes/node_python_aaa_cognition/dsh_client.py` | 新增：节点通道客户端（submit/read/wait/推送） |
| `nodes/node_python_aaa_cognition/mode_manager.py` | 新增：模式状态读写 + NLP 关键词切换检测 |
| `nodes/node_python_aaa_cognition/main.py` | 工具分支 dsh.* 直连；`_on_text` 模式 NLP + work 直通分支；异步回执后台线程；`_dsh_session_id` 续接 |
| `nodes/node_python_aaa_cognition/node_config.json` | 新增 `mode_keywords` 段（默认切换关键词） |
| `nodes/node_dsh/main.py` | `context` 字段拼入 task 前缀（兼容旧输入） |
| `gui/core/tool_registry.py` | 移除 dsh.run_task / run_task_sync / check_task（25→22 工具） |
| `gui/core/workflow_store.py` | `run()` 对 dsh.* 前缀改节点直连（`_run_dsh_direct`） |
| `gui/core/tool_bridge.py` | `_HEAVY_TOOLS` 清空（dsh 执行已迁移节点通道） |
| `gui/pages/chat_page.py` | 顶部「日常/工作」切换按钮 + 定时同步 |
| `gui/pages/settings_panel.py` | 「模式切换关键词」配置分组 |
| `nodes/shared/gui_tool_schemas.json` | 能力清单刷新为 22 工具 |

---

## 八、实施记录

- **v1.0（2026-08-14）**：方案定稿（待决策 → 批准实施）
- **v1.1（2026-08-14）**：全部 Phase 落地，状态转 [OK]。实施差异：
  1. 切换关键词由 mode.json 移至 AAA `node_config.json` 的 `mode_keywords` 段
     （配置归节点自治，mode.json 仅存运行时状态）
  2. 关键词检测支持多词按长度优先匹配（长词更具体优先）
  3. `dsh.preset_*`（Agent 预设管理）工具保留在 GUI 工具桥（属 GUI 管理能力，非执行器官）
  4. `_HEAVY_TOOLS` 清空但保留机制
- 验证摘要：AAA/GUI 全量 py_compile 通过；mode_manager 冒烟（切 work/切 daily/误触不切）
  通过；GUI offscreen（chat_page 模式按钮、settings_panel 关键词分组）实例化通过；
  tool_registry 22 工具（执行器官移除、preset 保留）通过；workflow_store `_run_dsh_direct`
  直连分支冒烟通过；schemas 文件刷新为 22 工具
