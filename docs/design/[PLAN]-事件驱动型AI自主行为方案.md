# 事件驱动型 AI 自主行为方案

> 日期：2026-07-26 | 版本：v2.0 | 状态：[PLAN]

## 目录

- [一、背景与问题](#一背景与问题)
- [二、核心思路](#二核心思路)
- [三、整体架构](#三整体架构)
- [四、事件路由层（AAA 内部 turn_taking 组件）](#四事件路由层aaa-内部-turn_taking-组件)
  - [4.1 组件定位](#41-组件定位)
  - [4.2 AAA 内部数据流](#42-aaa-内部数据流)
  - [4.3 三层过滤机制](#43-三层过滤机制)
  - [4.4 观察缓冲区](#44-观察缓冲区)
  - [4.5 内部触发流程](#45-内部触发流程替代跨节点协议)
- [五、与现有节点的衔接（已合并到 AAA 内部）](#五与现有节点的衔接已合并到-aaa-内部)
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
[声音] ─→ ASR 节点 ──→ voice_segment ──→ ┐
                                             │  AAA 节点（内部 turn_taking 组件）
[屏幕] ─→ Vision 节点 (Phase 2) ──→ vision ─┤
  ;                                           ├──→ _quick_filter() → _obs_buffer
[系统] ─→ Env 节点 (Phase 2) ────→ env_event ─┘        │
                                                         │ 达标 → 内部构建 prompt
                                                         │
[GUI] ───────────────────────────────────────────────────┘（直达，不走过滤）
                                                         │
                                                         ▼
                                                       LLM
```

**核心改动**：turn_taking 不作为独立节点，而是嵌入 AAA 内部的组件。AAA 崩溃等价于整个 AI 崩溃，独立进程无隔离收益，且多感官输入共享同一套过滤逻辑。

**两条路径互不干扰**：
- GUI 打字 → `gui_input` → 直达 prompt 构建（过滤延迟零）
- ASR/Vision/Env → 感官端口 → 内部 turn_taking → 有条件触发 prompt

---

## 四、事件路由层（AAA 内部 turn_taking 组件）

### 4.1 组件定位

AI 的**注意力过滤器**，嵌入 `aaa_cognition/main.py` 的 `TurnTakingFilter` 类。不调用 LLM，纯规则 + 缓冲区操作，决定：

1. 这条事件值不值得让 AI 知道？
2. 如果值得，放到观察缓冲区等处理
3. 什么时候该把缓冲区的内容发给 prompt 构建？

**不决定**"AI 要不要说话"——那是收到 prompt 后 LLM 的决定。

**不占用独立进程**——AAA 崩溃等价于整个 AI 崩溃，独立进程无隔离收益。

### 4.2 AAA 内部数据流

```
asr_input → handle_asr_input()
  ├─ 写 DB: INSERT INTO memory (source='asr')
  ├─ turn_taking._quick_filter(voice_seg)
  │   ├─ DISCARD → 结束（只写日志）
  │   └─ ATTENTION/PRIORITY → turn_taking._obs_buffer.add()
  │       ├─ 缓冲区未满 + 未超时 → 结束
  │       └─ 已满 / 超时 / PRIORITY → _buffer_flush()
  │           └─ → _build_from_env() 内部构建 prompt

gui_input → handle_gui_input()
  └─ 直达 _build_context() → 内部构建 prompt（不走 turn_taking）
```

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

### 4.5 内部触发流程（替代跨节点协议）

缓冲区刷新后，`TurnTakingFilter` 内部调用 `_build_from_env()` 直接构建 prompt。不再需要跨节点的 context_bundle 协议：

```python
class TurnTakingFilter:
    def __init__(self, aaa_instance):
        self._aaa = aaa_instance           # 持有 AAA 实例引用
        self._buffer = ObservationBuffer()

    def on_voice_segment(self, voice_seg: dict, dbp):
        """ASR 语音事件入口"""
        result = self.quick_filter(voice_seg)
        if result == FilterResult.DISCARD:
            return  # 只写日志，不触发 AI
        if result == FilterResult.PRIORITY:
            return self._aaa._build_from_env(dbp)  # 立即触发
        if self._buffer.add(voice_seg):
            return self._aaa._build_from_env(dbp)  # 缓冲区满

    def should_timeout_flush(self) -> bool:
        return self._buffer.should_timeout_flush()
```

AAA 新增方法：

```python
class AAACognition:
    def __init__(self):
        # ... 原有初始化 ...
        self._turn_taking = TurnTakingFilter(self)

    def handle_asr_input(self, voice_seg: dict, dbp):
        """ASR 输入端口 → 写 DB → 进入 turn_taking 过滤"""
        db.write_async({"data_type": "voice_input",
            "content": voice_seg.get("text", "")}, dbp, role="user")
        self._turn_taking.on_voice_segment(voice_seg, dbp)

    def handle_gui_input(self, text: str, dbp):
        """GUI 输入 → 直达 prompt 构建（不走 turn_taking）"""
        db.write_async(...)
        ctx = self._gather_context(text, dbp)
        return {"data_type": "prompt", "content": pt.build(ctx)}

    def _build_from_env(self, dbp):
        """缓冲区刷新 → 构建含环境观察的 prompt"""
        bundle = self._turn_taking._buffer.flush()
        ctx = self._gather_context(user_text="", dbp=dbp)
        ctx["env_observation"] = _format_events(bundle)
        prompt = pt.build(ctx)
        return {"data_type": "prompt", "content": prompt}
```

prompt 模板新增一段：

```
### 环境观察（AI 通过 ASR/Vision 自主感知，非用户直接输入）
{env_observation}
```

**不破坏现有 GUI 打字链路的任何逻辑**。GUI 打字始终走 `handle_gui_input()` → 直接构建 prompt，不受 turn_taking 影响。

---

## 五、与现有节点的衔接（已合并到 AAA 内部）

turn_taking 不再作为独立节点，所有衔接逻辑已合并到 AAA 内部：

| 旧方案（独立节点） | 新方案（AAA 内部组件） |
|-----------------|---------------------|
| ASR → turn_taking → AAA | ASR → AAA `asr_input` 端口 → `handle_asr_input()` → 内部 TurnTakingFilter |
| turn_taking 的独立 node_config.json | AAA 的 node_config.json 新增 `asr_input` 端口 |
| turn_taking 的独立 listener.py | 无，AAA 进程启动时加载 TurnTakingFilter 实例 |
| turn_taking → AAA 的 context_bundle 协议 | 内部 `TurnTakingFilter._build_from_env()` 方法直调 |
| Vision/Env 走 turn_taking 独立端口 | AAA 新增 `vision_in` / `env_input` 端口，共享同一 TurnTakingFilter |

---

## 六、Phase 2 多模态扩展入口

turn_taking 的过滤逻辑天然支持多模态扩展——只需要在 AAA 新增对应端口和过滤规则：

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

### Phase 1a — AAA 内部实现 turn_taking 组件

| 任务 | 说明 | 依赖 |
|------|------|------|
| 在 `aaa_cognition/main.py` 中实现 `TurnTakingFilter` 类 | 第1层 `quick_filter()` + 第2层 `ObservationBuffer` | 无 |
| 实现 `handle_asr_input()` 入口 | ASR 输入端口写 DB + 走 turn_taking 过滤 | TurnTakingFilter 完成 |
| 实现 `_build_from_env()` | 缓冲区刷新时构建含环境观察的 prompt | AAA 现有 `_gather_context` |
| prompt 模板增加环境观察段 | 不破坏现有结构，空时自动跳过 | 模板文件 |
| node_config.json 新增 asr_input 端口 | BNOS 多端口配置 | BNOS 引擎支持 |
| 写日志：区分 DISCARD 和正常触发 | 有据可查（第1层丢弃率可统计） | 日志基础设施 |

> turn_taking **不是独立节点**，不单独启动。AAA 进程启动后自动加载 TurnTakingFilter 组件。

### Phase 1b — ASR 节点配合

| 任务 | 说明 | 依赖 |
|------|------|------|
| ASR 节点 `voice_segment` 输出中 `speaker_id` / `speaker_type` / `emotion` / `text` 字段实现 | 确保结构化输出 | ASR 节点开发 |
| ASR → AAA 的 BNOS 连线配置 | `port_mappings` 中 `asr_input` 端口 filter 为 `voice_segment` | BNOS 运行时就绪 |

### Phase 2 — 多模态扩展

| 任务 | 说明 | 依赖 |
|------|------|------|
| AAA 新增 `vision_in` 端口 | 过滤规则扩展，turn_taking 共享 ObservationBuffer | Phase 1 完成 |
| AAA 新增 `env_input` 端口 | 仅写 DB，不触发 prompt | Phase 1 完成 |
| Vision 节点开发 | 定时截图 + 画面描述 | Phase 1 完成 |
| OCR 集成 | 屏幕文字提取 | vision 就绪 |

### 组件关系图（Phase 1 完成后）

```
ASR ──→ voice_segment ──→ AAA (asr_input)
                             │
                             ├── _turn_taking._quick_filter()
                             │       ├── DISCARD → 结束
                             │       └── 通过 → _obs_buffer.add()
                             │               ├── 未满 → 等待
                             │               └── 满/超时 → _build_from_env()
                             │
GUI ──→ text ───────────────┤ (直接构建 prompt，不走 turn_taking)
                             │
                             ▼
                          prompt → LLM
```

**两条路径互不干扰**：
- GUI 打字 → `handle_gui_input()` → 直达 prompt 构建（延迟零）
- ASR 事件 → `handle_asr_input()` → turn_taking 过滤 → 有条件构建 prompt

---

## 九、FAQ

**Q: 会不会增加 LLM 调用次数？**

不增加。turn_taking 的缓冲区过滤掉绝大部分噪音，正常旁听时多数时间不触发 LLM。只有被叫名字、直接提问、强情绪、或长时间累积到有话题时，才走 AAA→LLM 流程。

**Q: 用户打字时，ASR 也在工作怎么办？**

GUI 发消息时附带 `source=gui` 标记，turn_taking 识别到用户在主动输入后，暂停缓冲区的自动刷新，避免 AI 同时说话（语音冲突由 Live2D 的 TTS 队列管理）。

**Q: turn_taking 为什么不放在 ASR 节点里？**

因为职责分离。ASR 只管"把声音转成文字+声纹"，turn_taking 管"什么值得关注"。后续 vision/ocr/env 事件也走 turn_taking，如果 embedding 在 ASR 里，每个感官节点各自实现一套过滤逻辑就重复了。放在 AAA 内部是折中方案——多感官共享过滤逻辑，同时节省一个独立节点的维护开销。

**Q: 为什么不把 turn_taking 做成独立节点？**

最初方案就是独立节点，但分析后发现：AAA 崩溃等价于整个 AI 崩溃，独立进程无隔离收益。嵌入 AAA 省去 node_config.json、listener.py、进程管理等全套节点基础设施成本。详见主方案 §3.5 的设计理由。

**Q: AI 一直监听会不会很耗资源？**

第1层规则过滤器是纯文本判断 + 几个 `if`，耗时 <0.01ms。第2层缓冲区只是内存列表操作。只有缓冲区刷新后才走正常 AAA→LLM 流程（和现在一样）。ASR 本身的资源消耗参考其开发方案。
