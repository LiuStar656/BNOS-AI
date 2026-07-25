# 过期回复过滤方案

> 日期：2026-07-25 | 版本：v1.0 | 状态：[PLAN]

## 目录

- [一、背景与现状评估](#一背景与现状评估)
- [二、目标](#二目标)
- [三、方案设计](#三方案设计)
  - [3.1 核心思路：request_id 请求关联](#31-核心思路request_id-请求关联)
  - [3.2 改动 1 - GUI 生成并按 request_id 过滤](#32-改动-1---gui-生成并按-request_id-过滤)
  - [3.3 改动 2 - AAA 透传 request_id](#33-改动-2---aaa-透传-request_id)
  - [3.4 改动 3 - LLM 透传 request_id](#34-改动-3---llm-透传-request_id)
  - [3.5 数据流](#35-数据流)
  - [3.6 为何能修好](#36-为何能修好)
- [四、分阶段实施计划](#四分阶段实施计划)
- [五、风险评估](#五风险评估)
- [六、测试计划](#六测试计划)
- [七、影响范围](#七影响范围)

---

## 一、背景与现状评估

### 现象

当 AAA 或 LLM 节点卡住导致 reply 没有及时传回时，若用户在超时后再次输入，下一次可能会收到**多个回复**，甚至出现回复内容与输入错位（A 的迟到回复被当成 B 的回答显示）。

### 通信协议背景

BNOS 节点间采用文件协议：listener 轮询上游 `output.json`（mtime + md5 内容哈希去重）-> 调 main.py 处理 -> 按端口写自己的 `output_*.json`。GUI 与 AAA 之间通过 `nodes/shared/gui_input.json`（输入）和 `gui_reply.json`（回复）通信。

### 根因（三个叠加因素）

**1. GUI 超时只解锁，不取消在飞请求**

`gui/core/message_manager.py:257-259` 的 60s 超时只把 `send_state` 重置为 idle，但管道里的 A 请求（AAA 已写 prompt、LLM 还在 infer）**仍在跑**。用户重发 B 后，A 和 B 两条管道同时在飞。

**2. 回复不带请求标识，GUI 无法判新旧**

`message_manager.py:144-181` 的 `poll_reply` 只要 `gui_reply.json` 内容变化（mtime + md5）就当作新回复显示。回复里没有任何字段说明"我是哪次发送的回复"，所以 A 的迟到回复和 B 的回复都会被显示。更糟的是，若 A 的迟到回复先到，还会被当成 B 的回答（内容错位）。

**3. 并发请求覆盖共享输出文件**

AAA listener 用 `ThreadPoolExecutor` 并发处理（`listener.py:414`），而每个端口只有**一个共享输出文件**（`output_prompt.json` / LLM `output.json` / `gui_reply.json`）。A 卡住时 B 进来，两条管道并发写同一批文件，互相覆盖，加剧回复错乱。

### 关键观察

- `_session_id` 在 AAA `main.py:78` 被读取（`data.get("_session_id", "default")`），但当前无人写入，恒为 "default"，不能作为关联机制。
- 回复的真正消费方只有 GUI（显示气泡）；Live2D 节点只是消费 reply 生成 emotion/tts_url，对"哪次发送"不敏感。

---

## 二、目标

1. 一次发送最终只显示一条回复，节点卡住恢复后不堆积多个气泡
2. 回复内容与输入正确对应，不出现 A 的回复显示为 B 的回答
3. 改动集中于 main.py 层的输入输出字段透传，不改变文件协议结构与 listener 行为
4. 保留节点独立可运行性，不引入跨节点 import

---

## 三、方案设计

### 3.1 核心思路：request_id 请求关联

给每次 GUI 发送打一个 `request_id`，沿管道透传到回复，GUI 只接受与"当前最新发送"匹配的回复，其余丢弃。这是标准的请求-回复关联模式，也是文件协议下最干净的修法。

### 3.2 改动 1 - GUI 生成并按 request_id 过滤

文件：`gui/core/message_manager.py`

`send_text`（L60）：

- 生成 `request_id`（`uuid.uuid4().hex[:8]`），存 `self._current_request_id`。
- 写入 `gui_input.json` 的 payload 增加 `"request_id": request_id`。

`poll_reply`（L144）：

- 在解析回复内容**之前**，先取 `reply.get("request_id")`。
- 若 `request_id != self._current_request_id`：记日志"丢弃过期回复（期望 X，收到 Y）"，**不动 send_state、不取消超时、不 emit**，return None。
- 只有匹配的回复才进入既有的 `send_state=idle` + `reply_received.emit` 逻辑。

### 3.3 改动 2 - AAA 透传 request_id

文件：`nodes/node_python_aaa_cognition/main.py`

- `_on_text`（L65-69）：把输入的 `request_id` 复制到 prompt 输出：

```python
return {
    "_port": "prompt",
    "data_type": "prompt",
    "content": pt.build(ctx),
    "request_id": data.get("request_id"),
}
```

- `_on_parsed`（L72-97）：把 LLM 回执里的 `request_id` 复制到 reply / tool_call / knowledge 各输出项。

### 3.4 改动 3 - LLM 透传 request_id

文件：`nodes/node_python_llm_infer/main.py`

- `process`（L57-84）：把输入 data 的 `request_id` 复制到所有返回分支（parsed 成功分支 + 各 error 分支 L60-82），确保卡住后返回的 error 回复也带 id，能被 GUI 正确过滤。

**listener 无需改动**：AAA listener 直接把 main.py 返回的 item 整体写入 `gui_reply.json`（`listener.py:382-383`），request_id 自然透传。LLM/AAA 的 listener 都是 `json.dumps(input_data)` 传给 main.py、原样写回输出，已验证。

### 3.5 数据流

```
GUI send_text
  └─ gui_input.json  {data_type:text, content, source:gui, request_id:<id>}
     └─ AAA _on_text 透传 request_id
        └─ output_prompt.json  {data_type:prompt, content, request_id:<id>}
           └─ LLM process 透传 request_id
              └─ output.json  {data_type:parsed, content, source:llm, request_id:<id>}
                 └─ AAA _on_parsed 透传 request_id
                    └─ gui_reply.json  {data_type:reply, content, request_id:<id>}
                       └─ GUI poll_reply 校验 request_id == _current_request_id
                          ├─ 匹配: 显示 + 解锁
                          └─ 不匹配: 丢弃
```

### 3.6 为何能修好

- 发 A（id=aaa）-> 卡住 -> 60s 超时 -> 发 B（id=bbb，`_current_request_id=bbb`）。
- A 的迟到回复带 aaa -> GUI 丢弃（≠bbb）。
- B 的回复带 bbb -> GUI 显示。
- **只显示一个回复**，且不会内容错位。
- 若 A 真死锁永不恢复，则只有 B 的回复显示，符合预期。

---

## 四、分阶段实施计划

### Phase 0 - 关联字段打通

1. 改动 1 的 `send_text`：生成并写入 request_id
2. 改动 2 + 改动 3：AAA / LLM main.py 透传 request_id
3. 改动 1 的 `poll_reply`：先做"仅日志记录不丢弃"的软校验，观察 request_id 是否正确贯穿
4. 验证：日志中能看到 request_id 从 GUI 一路传到 gui_reply.json

### Phase 1 - 启用过滤

5. 改动 1 的 `poll_reply`：将软校验改为硬丢弃（不匹配则 return None）
6. 验证：构造卡住场景，确认只显示一条回复

### Phase 2 - 边界完善

7. LLM 各 error 分支补 request_id
8. 工具循环路径补 request_id（见风险评估）
9. 回归测试

---

## 五、风险评估

| 风险 | 等级 | 应对 |
|------|------|------|
| 工具循环丢失 request_id | 中 | AAA 的 tool_call -> tool_result -> 重新 prompt 循环中，request_id 靠 main.py 每次输出都复制来保持。若存在独立工具执行节点，需一并透传；若工具循环在 AAA 内闭合则自动保持。Phase 2 需验证 |
| LLM error 回复不带 request_id | 中 | 改动 3 显式给所有 error 分支补 request_id；否则卡住后的 error 回复无法被过滤，可能仍显示。对"无 request_id"的回复，GUI 兜底策略：视为过期丢弃 |
| 并发覆盖（根因 #3）未根治 | 中 | request_id 修法解决"用户看到多个气泡"的症状。底层共享文件并发覆盖是更深的架构问题（需每请求独立输出文件或队列），属更大改动，不在本方案范围。有了 request_id 过滤，最坏情况只是丢弃过期回复，不会显示错乱 |
| 旧版回复（无 request_id）兼容 | 低 | `poll_reply` 对 `request_id` 缺失的回复：若 `_current_request_id` 存在则视为过期丢弃；过渡期可加开关兼容 |
| AAA listener 子进程 180s 超时（`listener.py:346`）与 LLM 300s 超时不一致 | 低 | 超时本身不破坏 request_id 关联，超时后 main.py 返回空/error 仍带 id。可顺带评估对齐超时阈值，但非本方案必需 |

---

## 六、测试计划

### 关联贯穿测试

1. 正常一问一答：日志确认 request_id 从 gui_input.json -> output_prompt.json -> llm output.json -> gui_reply.json 一路不变。
2. GUI 显示的回复 request_id 与发送时一致。

### 过期过滤测试

3. **卡住恢复场景**：人为让 LLM infer 延迟 >60s（如断网或 mock 慢响应），GUI 超时后发送 B，待 A 恢复：
   - 期望：只显示 B 的回复，A 的迟到回复被丢弃并记日志。
4. **A 先恢复场景**：A 的回复早于 B 到达：
   - 期望：A 的回复被丢弃（≠bbb），B 的回复显示，不出现内容错位。
5. **连续多次卡住**：A 卡 -> B 卡 -> C 正常：
   - 期望：只显示 C 的回复。

### 边界测试

6. 工具循环：触发一次工具调用的回复，确认 request_id 贯穿多轮 LLM 调用仍保持。
7. LLM error：让 LLM 后端抛错，确认 error 回复带 request_id 且被正确处理（不误显）。
8. 回归：正常对话流程、表情、TTS 链路不受影响。

---

## 七、影响范围

| 文件 | 改动 |
|------|------|
| `gui/core/message_manager.py` | `send_text` 生成 request_id；`poll_reply` 按 request_id 过滤过期回复 |
| `nodes/node_python_aaa_cognition/main.py` | `_on_text` / `_on_parsed` 透传 request_id |
| `nodes/node_python_llm_infer/main.py` | `process` 各返回分支透传 request_id |
| `nodes/shared/gui_input.json`（运行时） | payload 增加 `request_id` 字段 |
| `nodes/shared/gui_reply.json`（运行时） | payload 增加 `request_id` 字段 |

不涉及：listener（Python/JS）、文件协议结构、bnos_runtime 引擎、Live2D/TTS 链路。

### 已知不解决（更深层问题）

- **并发请求覆盖共享输出文件**（根因 #3）：本方案用 request_id 过滤解决了用户可见的"多气泡"症状，但底层多个在飞请求写同一批 output 文件的覆盖问题依旧。彻底解决需引入"每请求独立输出文件"或"节点内请求队列"，属架构级改动，另案规划。
