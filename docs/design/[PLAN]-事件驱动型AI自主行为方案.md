# 事件驱动型 AI 自主行为方案

> 日期：2026-07-26 | 版本：v1.0 | 状态：[PLAN]

## 目录

- [一、背景与问题](#一背景与问题)
- [二、核心思路](#二核心思路)
- [三、整体架构](#三整体架构)
- [四、事件路由层（turn_taking 节点）](#四事件路由层turn_taking-节点)
  - [4.1 节点定位](#41-节点定位)
  - [4.2 端口定义](#42-端口定义)
  - [4.3 三层过滤机制](#43-三层过滤机制)
  - [4.4 观察缓冲区](#44-观察缓冲区)
  - [4.5 输出协议](#45-输出协议)
- [五、与现有节点的衔接](#五与现有节点的衔接)
  - [5.1 ASR → turn_taking](#51-asr--turn_taking)
  - [5.2 turn_taking → AAA](#52-turn_taking--aaa)
  - [5.3 AAA 的改动](#53-aaa-的改动)
- [六、Phase 2 多模态扩展入口](#六phase-2-多模态扩展入口)
- [七、Phase 3 行为学习](#七phase-3-行为学习)
- [八、实施计划](#八实施计划)
- [九、FAQ](#九faq)

---

## 一、背景与问题

### 现有方案的局限

当前 AAA 节点是 **"输入 → 必回应"** 模式——只要有 text 输入到 `_on_text`，就必构建 prompt 调 LLM。这在 GUI 打字场景下没问题，但扩展到语音后，问题就暴露了：

| 场景 | 现有行为 | 期望行为 |
|------|---------|---------|
| 用户在跟别人聊天 | AI 每句都回 | AI 在旁边听，不插嘴 |
| 用户在自言自语 | AI 每句都回 | AI 不回应 |
| 陌生人说话 | 无此能力 | 记录但不触发回复 |
| 长时间安静 | AI 无事可做 | AI 可以进行内部思考 |

Mewco 的 ASE 用定时器解决"主动说话"，但**定时触发是假的自然**——人不会每隔 X 分钟就想说话。

### 真正的目标

让 AI 的行为由**外部事件驱动**，而不是由**定时器驱动**：

```
✗ 定时器: 「每 5 分钟该找话题了」
✓ 事件:   「张三说'今天天气真差' → 联想到用户怕下雨 → 搭话提醒带伞」
✓ 静默:   「没人在说话 → 正常，AI 继续监听/内部思考」
```

---

## 二、核心思路

### 三层过滤 + 累积观察

```
ASR 事件（15次/分钟）
  │
  ├─ 第1层: 规则过滤（零LLM）─── 过滤 80-90% 噪音
  │   ├─ 陌生人? → 丢弃（只写日志）
  │   ├─ 提到名字? → 放行
  │   ├─ 句尾是问号? → 放行
  │   ├─ 情绪强烈? → 放行
  │   └─ 其他 → 丢弃
  │
  ├─ 第2层: 观察缓冲区（合并）
  │   └─ 被放行的事件 → 放入缓冲区（最多缓冲 5 句或 30 秒）
  │
  └─ 第3层: 兴趣度评估（过 LLM，正常旁听时多数时间不触发）
      └─ 缓冲区满或超时 → 打包成一条"环境观察" → 发给 AAA
          └─ AAA 正常构建 prompt → LLM 判断"要不要说 + 说什么"
```

**关键约束**：LLM 调用频率不增加——正常旁听时多数时间不触发 LLM，只有真正值得关注的事件（被叫名字、直接提问、强情绪、长时间有话题）才走 LLM。

### 多阶段扩展

| Phase | 感官 | 事件源 | 行为表现 |
|-------|------|--------|---------|
| 1 | 语音（ASR） | 说话声 | 听、区分熟人/陌生人、选择性回应 |
| 2 | 视觉（Vision/OCR） | 屏幕变化 | 看画面、读文字、点评内容 |
| 3 | 学习（Bandit） | 历史反馈 | 自动优化"什么时候该说话" |

---

## 三、整体架构

```
[声音] ─→ ASR 节点 ──→ voice_segment ──→ turn_taking 节点 ──→ AAA 节点 ──→ LLM
                                                    │               │
                                                    │  (过滤/缓冲/   │  (构建 prompt)
                                                    │   兴趣评估)    │
[屏幕] ─→ Vision 节点 (Phase 2) ────→ vision_event ─┘               │
                                                                     │
[系统] ─→ Env 节点 (Phase 2) ───────→ env_event ────────────────────┘
```

**核心新增**：`turn_taking` 节点——事件路由层，决定"什么值得让 LLM 过脑子"。

---

## 四、事件路由层（turn_taking 节点）

### 4.1 节点定位

AI 的**注意力过滤器**。不调用 LLM，纯规则 + 向量相似度，决定：

1. 这条事件值不值得让 AI 知道？
2. 如果值得，放到观察缓冲区等处理
3. 什么时候该把缓冲区的内容发给 AAA？

**不决定**"AI 要不要说话"——那是 AAA 收到 prompt 后 LLM 的决定。

### 4.2 端口定义

| 端口 | data_type | 方向 | 来源/目标 |
|------|-----------|------|-----------|
| `voice_input` | `voice_segment` | 入 | ASR 节点 |
| `vision_input` | `vision_event` | 入 | Vision 节点（Phase 2） |
| `env_input` | `env_event` | 入 | Env 节点（Phase 2） |
| `default` | `context_bundle` | 出 | AAA 节点 |

### 4.3 三层过滤机制

#### 第 1 层：规则过滤器（零 LLM，零向量）

```python
def quick_filter(segment: VoiceSegment) -> FilterResult:
    """毫秒级判断是否值得关注"""
    # 1. 陌生人 → 丢弃（只写日志不触发任何后续）
    if segment.speaker_type in ("stranger", "unknown"):
        return FilterResult.DISCARD

    # 2. 被叫名字 → 必须关注（最高优先级）
    if any(name in segment.text for name in AI_NAMES):
        return FilterResult.PRIORITY

    # 3. 情绪强烈 → 关注
    if segment.emotion in ("ANGRY", "SAD"):
        return FilterResult.ATTENTION

    # 4. 直接提问
    if segment.text.strip()[-1:] in ("？", "?"):
        return FilterResult.ATTENTION

    # 5. 刚刚才回复过（3秒内）→ 对话持续，关注
    if time_since_last_ai_output < 3:
        return FilterResult.NORMAL

    # 6. 其他 → 丢弃（自言自语、语气词、闲聊）
    return FilterResult.DISCARD
```

| 结果 | 含义 | 后续处理 |
|------|------|---------|
| `DISCARD` | 不值得关注 | 只写日志，不入缓冲区 |
| `NORMAL` | 普通关注 | 放入缓冲区 |
| `ATTENTION` | 可能值得回应 | 放入缓冲区并标记优先级 |
| `PRIORITY` | 必须回应（被点名） | 跳过缓冲区直接触发 AAA |

#### 第 2 层：观察缓冲区

```python
class ObservationBuffer:
    """
    累积观察，降低 LLM 调用频率。
    不到触发条件时，事件只写入缓冲区，不过 LLM。
    """
    def __init__(self):
        self.events: list[dict] = []       # 事件列表
        self.max_events = 5                # 最多累积 5 条
        self.flush_interval = 30           # 最长 30 秒必须刷新
        self.last_flush = time.time()

    def push(self, event: dict) -> list[dict] | None:
        """放入事件，返回 None 表示继续累积，返回 list 表示该刷新了"""
        self.events.append(event)
        if event.get("priority"):           # 高优先级 → 立即刷新
            return self.flush()
        if len(self.events) >= self.max_events:
            return self.flush()
        if time.time() - self.last_flush >= self.flush_interval:
            return self.flush()
        return None

    def flush(self) -> list[dict]:
        """取出所有事件并清空缓冲区"""
        batch = self.events.copy()
        self.events.clear()
        self.last_flush = time.time()
        return batch
```

#### 第 3 层：兴趣度评估（过 LLM，但合并在正常流程中）

缓冲区刷新后，打包成一条 `context_bundle` 发给 AAA。AAA 在正常的 prompt 构建中加入"最近环境观察"部分：

```
### 输入上下文
你的自我认知：...
你的最近感受：...

本轮输入：
  [张三] 今天天气真差啊
  [张三] 要不要带伞出门
  （用户没有说话，以上是 AI 通过 ASR 听到的环境对话）

### 额外观察（当前环境摘要）
张三正在讨论出门计划，语气中性偏积极。

### 输出格式（同现有，不需要的节省略）
【自然回复】—— 如果想说话，这里写回复
【想法】—— 内心想法（不播报），如果不想说话也至少写这个
......
```

**LLM 输出时自然决定**：想说就说【自然回复】，不想说就只写【想法】（内心活动写 DB 但不播报）。**不增加额外 LLM 调用**。

### 4.5 输出协议

```json
// turn_taking → AAA 的 context_bundle
{
  "data_type": "context_bundle",
  "source": "turn_taking",
  "conversation_id": "default",
  "observation_period": {
    "start": 1711350000.0,
    "end": 1711350030.0
  },
  "events": [
    {
      "type": "voice",
      "speaker_id": "zhangsan",
      "speaker_name": "张三",
      "text": "今天天气真差啊",
      "emotion": "NEUTRAL",
      "importance": "normal"
    },
    {
      "type": "voice",
      "speaker_id": "lisi",
      "speaker_name": "李四",
      "text": "对啊，要不要带伞出门",
      "emotion": "NEUTRAL",
      "importance": "attention"
    }
  ],
  "trigger_reason": "buffer_timeout"
}
```

---

## 五、与现有节点的衔接

### 5.1 ASR → turn_taking

ASR 节点输出 `voice_segment` 写入 `output.json`，turn_taking 轮询消费——和 BNOS 标准节点间通信机制一致，不需要额外协议。

### 5.2 turn_taking → AAA

turn_taking 将 `context_bundle` 写入 `output.json`，AAA 新增 `context_bundle` 输入端口接收：

**route_map 新增一条**：

| data_type | 目标端口 | 对应处理 |
|-----------|---------|---------|
| `context_bundle` | `context_bundle` | `_on_context_bundle()` |

### 5.3 AAA 的改动

AAA 新增 `_on_context_bundle()` 处理逻辑，其他不变：

```python
def _on_context_bundle(self, data, dbp):
    """处理 turn_taking 累积的观察事件"""
    db.ensure(dbp)
    events = data.get("events", [])

    # 1. 所有事件写 DB（不阻塞）
    for ev in events:
        db.write_async({
            "data_type": "env_observation",
            "speaker_id": ev.get("speaker_id", ""),
            "content": f"[{ev.get('speaker_name','')}] {ev.get('text','')}",
            "emotion": ev.get("emotion", ""),
        }, dbp, role="observation")

    # 2. 构建 prompt（与现有 _on_text 共用 _gather_context）
    #    但现在 user_text 为空，context 中附带观察事件摘要
    ctx = self._gather_context(
        user_text="",
        dbp=dbp,
        conv_id=self._current_conversation_id,
    )
    # 把 turn_taking 的观察注入到 prompt 的"环境信息"部分
    ctx["env_observation"] = _format_observations(events)

    return {
        "_port": "prompt",
        "data_type": "prompt",
        "content": pt.build(ctx),
        "request_id": None,  # 非用户直接请求，不关联 request_id
    }
```

prompt 模板新增一段：

```
### 环境观察（AI 通过 ASR/Vision 自主感知，非用户直接输入）
{env_observation}
```

这样 AAA 的改动最小——只加了一个端口、一个处理方法、prompt 模板加了一段。**不破坏现有 GUI 打字链路的任何逻辑**。

---

## 六、Phase 2 多模态扩展入口

turn_taking 的过滤逻辑天然支持多模态扩展——只需要新增事件类型和对应的过滤规则：

```python
def quick_filter_v2(event: dict) -> FilterResult:
    event_type = event.get("type", "voice")

    if event_type == "voice":
        return filter_voice(event)      # 同上
    elif event_type == "vision":
        return filter_vision(event)     # 屏幕变化 → 关注
    elif event_type == "ocr":
        return filter_ocr(event)        # 屏幕文字 → 关注
    elif event_type == "env":
        return filter_env(event)        # 系统事件 → 低优先级
```

**所有类型的事件都走同一个缓冲区、同一条 AAA 管道**——不需要额外节点。

---

## 七、Phase 3 行为学习（远期）

参考 Autonomous VTuber 的 Thompson Sampling Bandit，为每种触发类型记录"回应后的效果"：

```python
# 远期想法，不是本期实现
bandit_weights = {
    "被叫名字_回应":  {"success": 45, "fail": 5},
    "情绪强烈_安慰":  {"success": 12, "fail": 8},
    "闲聊_搭话":     {"success": 3,  "fail": 17},  # 闲聊搭话成功率低
}
```

根据历史成功率调整兴趣度阈值，让 AI 自动学会什么场景该说话、什么场景不该说。

---

## 八、实施计划

### Phase 1a — 新增 turn_taking 节点

| 任务 | 说明 | 依赖 |
|------|------|------|
| 创建 `node_python_turn_taking` | 新节点，事件路由层 | 无 |
| 实现第1层规则过滤器 | `quick_filter()`，零 LLM | ASR 输出协议定稿 |
| 实现第2层观察缓冲区 | `ObservationBuffer`，累积合并 | 第1层完成 |
| 定义 `context_bundle` 输出协议 | 结构化事件数组 | 缓冲区完成 |
| 注册到 BNOS 路由表 | `port_mappings` 配置 | ASR 节点就绪 |

### Phase 1b — 修改 AAA 节点

| 任务 | 说明 | 依赖 |
|------|------|------|
| 新增 `context_bundle` 输入端口 | 接收 turn_taking 输出 | turn_taking 就绪 |
| 实现 `_on_context_bundle()` | 写 DB + 构建 prompt | AAA 现有代码 |
| prompt 模板增加环境观察段 | 不破坏现有结构 | 模板文件 |

### Phase 2 — 多模态扩展

| 任务 | 说明 | 依赖 |
|------|------|------|
| Vision 节点开发 | 定时截图 + 画面描述 | Phase 1 完成 |
| OCR 集成 | 屏幕文字提取 | vision 就绪 |
| turn_taking 扩展过滤规则 | 新增 vision/ocr/env 类型 | 对应节点就绪 |

### 节点关系图（Phase 1 完成后）

```
ASR ──→ voice_segment ──→ turn_taking ──→ context_bundle ──→ AAA ──→ prompt ──→ LLM
                              │                                  │
GUI ──────────────────────────┴── text ──────────────────────────┤
```

GUI 打字走 `text` 端口（直连，不经过 turn_taking），ASR 事件走 `context_bundle` 端口（经过 turn_taking 过滤）。**两条路径互不干扰**。

---

## 九、FAQ

**Q: 会不会增加 LLM 调用次数？**

不增加。turn_taking 的缓冲区过滤掉绝大部分噪音，正常旁听时多数时间不触发 LLM。只有被叫名字、直接提问、强情绪、或长时间累积到有话题时，才走 AAA→LLM 流程。

**Q: 用户打字时，ASR 也在工作怎么办？**

GUI 发消息时附带 `source=gui` 标记，turn_taking 识别到用户在主动输入后，暂停缓冲区的自动刷新，避免 AI 同时说话（语音冲突由 Live2D 的 TTS 队列管理）。

**Q: 为什么要单独一个 turn_taking 节点，不直接在 ASR 里做？**

职责分离。ASR 只管"把声音转成文字+声纹"，turn_taking 管"什么值得关注"。后续 vision/ocr/env 事件也走 turn_taking，不需要每个感官节点都重复实现过滤逻辑。

**Q: AI 一直监听会不会很耗资源？**

第1层规则过滤器是纯文本判断 + 几个 `if`，耗时 <0.01ms。第2层缓冲区只是内存列表操作。只有缓冲区刷新后才走正常 AAA→LLM 流程（和现在一样）。ASR 本身的资源消耗参考其开发方案。
