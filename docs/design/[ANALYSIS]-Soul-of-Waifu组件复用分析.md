# Soul of Waifu 组件复用分析

> 日期：2026-07-27 | 版本：v1.2 | 状态：[ANALYSIS]
> 来源：`references/Soul-of-Waifu-main`（v2.4.0）

## BNOS 设计约束（决定复用过滤策略）

1. **一用户对应一 AI** — AI 记忆深度绑定数据库，不是可随意替换的角色卡。因此角色卡系统（Chub.ai）、Soul Stage RPG 引擎（需要多角色切换）与 BNOS 设计理念不符，**不推荐复用**。
2. **已有 grok_hands 工具系统** — 工具调用/MCP/PluginLoader 的能力已经被 grok build 覆盖，SoW 的工具系统 **不推荐复用**。
3. **BNOS 是节点化架构** — SoW 是单体应用。节点间数据流通过合约匹配，不直接调用插件 API。

> ✅ **保留推荐的模块**：与 BNOS 设计理念兼容，可借鉴设计思路或代码模式
> ❌ **排除的模块**：与 BNOS 设计理念冲突，或已被现有能力覆盖

## 目录

- [一、SoW 整体架构概况](#一sow-整体架构概况)
- [二、核心模块逐项分析](#二核心模块逐项分析)
  - [2.1 神经激素系统（NeurohormoneSystem）](#21-神经激素系统neurohormonesystem)
  - [2.2 Soul Memory 多智能体记忆系统](#22-soul-memory-多智能体记忆系统)
  - [2.3 Soul Companion 桌面叠加层](#23-soul-companion-桌面叠加层)
  - [2.4 VRM 渲染模块](#24-vrm-渲染模块)
  - [2.5 工具系统 + MCP](#25-工具系统--mcp) ❌ grok 已覆盖
  - [2.6 插件加载器（PluginLoader）](#26-插件加载器pluginloader) ❌ grok 已覆盖
  - [2.7 SoW System 全双工语音系统](#27-sow-system-全双工语音系统)
  - [2.8 AI Factory 多 Provider 体系](#28-ai-factory-多-provider-体系)
  - [2.9 Models Hub 本地模型管理](#29-models-hub-本地模型管理)
  - [2.10 图像生成引擎](#210-图像生成引擎)
  - [2.11 高级文本采样](#211-高级文本采样)
  - [2.12 Lorebook 引擎](#212-lorebook-引擎)
  - [2.13 自定义状态变量 HUD](#213-自定义状态变量-hud)
  - [2.14 角色卡系统（Chub.ai）](#214-角色卡系统chubai) ❌ 设计冲突
  - [2.15 Web Client 移动端接入](#215-web-client-移动端接入)
  - [2.16 Discord Gateway](#216-discord-gateway)
  - [2.17 翻译系统](#217-翻译系统)
- [三、与 BNOS 各设计文档的对照](#三与-bnos-各设计文档的对照)
  - [3.1 3D 角色自定义系统](#31-3d-角色自定义系统)
  - [3.2 角色种子系统](#32-角色种子系统)
  - [3.3 事件驱动型 AI 自主行为](#33-事件驱动型-ai-自主行为)
  - [3.4 插件系统](#34-插件系统)
- [四、BNOS 可直接参考/复用的组件](#四bnos-可直接参考复用的组件)
- [五、BNOS 相比 SoW 的核心优势](#五bnos-相比-sow-的核心优势)
- [六、风险与注意事项](#六风险与注意事项)

---

## 一、SoW 整体架构概况

Soul of Waifu 是一个基于 **PyQt6 + Three.js** 的桌面 AI 伴侣应用，单体架构，核心模块：

```
┌──────────────────────────────────────────────────────────┐
│ PyQt6 GUI（main.py / sowInterface.py）                   │
│  ├─ 角色管理器（角色卡导入/导出/编辑）  ❌ 设计冲突      │
│  ├─ Chat 界面（文字+语音全双工）                          │
│  ├─ Models Hub（HuggingFace 模型浏览器+下载器）           │
│  ├─ Soul Stage（桌游 RPG 引擎）         ❌ 设计冲突      │
│  ├─ QWebEngineView（VRM 渲染器）                          │
│  ├─ Soul Companion（桌面叠加层，透明窗口）                 │
│  └─ Options（配置面板）                                   │
├──────────────────────────────────────────────────────────┤
│ 后台服务层                                                │
│  ├─ AI Factory（10+ 云端 LLM / 本地 Llama.cpp）           │
│  ├─ Soul Memory（多智能体记忆系统）                       │
│  ├─ Soul Companion Engine（神经激素 + 事件驱动）          │
│  ├─ TTS 引擎（6 种）                                     │
│  ├─ ASR（Faster Whisper + Silero VAD）                    │
│  ├─ 工具系统（截图/搜索/剪贴板/媒体控制/MCP） ❌ grok覆盖 │
│  └─ Discord Gateway / Web Server                           │
└──────────────────────────────────────────────────────────┘
```

**技术栈**：PyQt6 + QWebEngineView + Three.js + @pixiv/three-vrm + Llama.cpp + sentence-transformers

---

## 二、核心模块逐项分析

### 2.1 神经激素系统（NeurohormoneSystem）

**源码**：[soul_companion.py#L117-L184](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/soul_companion/soul_companion.py#L117-L184)

**4 维激素模型**：

| 激素 | 含义 | 增长条件 | 衰减速度 | 影响 |
|------|------|---------|---------|------|
| oxytocin (催产素) | 亲密度 | 用户说话 +0.15 | 0.008/min | 决定是否感到孤独、温暖表情 |
| dopamine (多巴胺) | 愉悦度 | OS 事件 +0.08 | 0.004/min | 好奇心、兴奋程度 |
| cortisol (皮质醇) | 压力度 | — | 0.010/min | 担忧、紧张情绪 |
| energy (精力) | 精力值 | 自然恢复 0.012/min | 说话 -0.12 | 低于 0.08 进入睡眠状态 |

**关键设计**：

```python
# 说话消耗精力
def on_spoke(self) -> None:
    self.energy = max(0.0, self.energy - self.ENERGY_SPEAK_COST)  # 0.12

# 精力太低时禁止发言
def _can_speak(self, is_explicit: bool = False) -> bool:
    if self.hormones.is_sleeping:  # energy <= 0.08
        return False
    # 非主动触发时有 5 分钟冷却
    if not is_explicit:
        elapsed = (datetime.now() - self._last_spoke).total_seconds()
        if elapsed < self.SPEAK_MIN_GAP_SEC:  # 300 秒
            return False
```

**激素 → 情绪映射**（[EmotionState.from_hormones](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/soul_companion/soul_companion.py#L206-L220)）：

- sleep（精力低）、melancholy（孤独）、concerned（皮质醇高）
- curious（多巴胺高）、warm（催产素高且不孤独）
- excited（多巴胺+催产素都高）、relaxed（多巴胺低）

**对 BNOS 的价值**：BNOS 的[角色种子系统](file:///e:/杂项/BNOS_AI_project/docs/design/[PLAN]-角色种子系统设计方案.md)有**性格向量演化**（warmth/playfulness/directness/curiosity），但缺乏**实时情绪/状态层**。激素系统可作为"短期情绪层"叠加在"长期性格层"之上：

```
BNOS 现有：  性格向量（天/周级变化） → 影响 prompt 中的表达风格
SoW 借鉴：   激素系统（分钟级变化）   → 影响当前情绪/是否主动说话
```

---

### 2.2 Soul Memory 多智能体记忆系统

**源码**：[soul_memory.py](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/soul_memory.py)

**架构**：三种 LLM Agent 协作：

```
用户对话
    │
    ├─ Router Agent（每 4 条消息触发）
    │   ├─ 更新 MEMORY.md（角色心理状态索引）
    │   ├─ 更新 USER.md（用户画像+关系元数据）
    │   └─ 生成 topic_plan（决定创建/更新哪些主题文件）
    │
    ├─ Archivist Agent（按 topic_plan 执行）
    │   └─ 创建/更新 topics/*.md（按主题分类的叙事记忆文件）
    │
    └─ Diary Agent（每次都运行）
        └─ 追加 Diary_YYYY-MM-DD.md（第一人称日记）
```

**对比 BNOS 的 MemOS**：

| 维度 | BNOS MemOS（现有） | SoW Soul Memory |
|------|-------------------|-----------------|
| 存储 | DB 表（long_term_memory） | 文件系统（.md 文件） |
| 检索 | 向量语义检索（faiss.index） | sentence-transformers + 余弦相似度 |
| 更新方式 | 写入 + decay | LLM Agent 重写 |
| 结构化程度 | 扁平化的记忆条目 | 4 层文件：index / user / topics / diary |
| 自愈能力 | 无 | 检测矛盾并自动覆盖 |
| 备份 | 无 | 自动备份 5 份 |
| 存储格式 | JSON | Markdown（人类可读可改） |

**对 BNOS 的价值**：

1. ~~**Diary 机制**：SoW 每次对话后写第一人称日记~~ ✅ BNOS 已有（`diary.py` + `event_summary` 表）
2. **USER.md 独立维护**：BNOS 的用户信息分散在 `user_facts`、`other_cognition` 等表中，可以借鉴独立"用户画像"文件的设计
3. **自愈机制**：SoW 的 Router Agent 会检测"新记忆与旧记忆的矛盾"，自动覆盖过期信息。BNOS 的 decay 是纯时间衰减，可以补充"内容冲突检测"

---

### 2.3 Soul Companion 桌面叠加层

**源码**：[soul_companion.py#L849-L1748](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/soul_companion/soul_companion.py#L849-L1748)

**核心能力**：

| 能力 | 实现方式 | 备注 |
|------|---------|------|
| 透明桌面窗口 | PyQt6 透明窗口覆盖桌面 | BNOS 可做 |
| 窗口标题监听 | Win32 API `GetForegroundWindow` + `GetWindowTextW` | BNOS 可做 |
| 主动说话 | event_bus 消息泵 + heartbeat 定时器 | BNOS 已有类似设计 |
| AFK 检测 | 15s 间隔检查最后交互时间 | 简单 |
| 工具执行链 | LLM 规划 → 工具执行 → 结果回传 | SoW 有完整实现 |
| 激素影响行为 | energy/oxytocin 决定能否/想不想说话 | BNOS 可参考 |

**事件流设计**（[soul_companion.py#L1046-L1066](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/soul_companion/soul_companion.py#L1046-L1066)）：

```python
async def _event_loop(self, bus: SoulCompanionEventBus):
    while self._running:
        event = await asyncio.wait_for(bus.get(), timeout=2.0)
        await self._handle_event(event)
```

BNOS 的[事件驱动型 AI 自主行为方案](file:///e:/杂项/BNOS_AI_project/docs/design/[PLAN]-事件驱动型AI自主行为方案.md)也有类似的事件泵设计。SoW 的参考价值在于：

1. **具体的事件类型**（heartbeat / os_context / vad_trigger / idle_away / idle_return / tool_complete）和对应的处理逻辑
2. **Proactive 行为的随机概率控制**（30% 概率在心跳时主动说话）
3. **冷却机制+激素双重约束**（BNOS 只有缓冲区满才触发）

---

### 2.4 VRM 渲染模块

**源码**：[vrm_module.html](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/emotions/vrm_module.html)

**技术栈完全相同**：Three.js + @pixiv/three-vrm

SoW 已有的 BNOS 3D 方案中未涉及的能力：

| 能力 | SoW 实现 | BNOS 方案中状态 |
|------|---------|----------------|
| **Mixamo FBX 动画** | `loadMixamoAnimation` 将 Mixamo 绑骨映射到 VRM | **未规划** |
| **空闲动画系统** | 空闲时循环播放 neutral.fbx，说话时触发对应动画 | **未规划** |
| **平滑视线追踪** | VRMSmoothLookAt 类，阻尼系数 10.0 | **未规划** |
| **表情渐变** | requestAnimationFrame 渐进过渡，duration 参数 | BNOS 只有 setValue |
| **眨眼随机化** | Math.random() 控制眨眼间隔 1-11 秒 | BNOS 未涉及 |
| **背景系统** | 纯色 / 自定义图片 / 透明背景 | BNOS 未涉及 |
| **状态指示** | PROCESSING 时眼神漂移、非 idle 时跳过眨眼 | BNOS 未涉及 |

**对 BNOS 的价值**：

BNOS 的[3D 角色自定义系统](file:///e:/杂项/BNOS_AI_project/docs/design/[PLAN]-3D角色自定义系统设计方案.md)目前只规划了 BlendShape 表情 + 说话张嘴。SoW 的 **FBX 动画集成** 是 BNOS 缺失的关键能力——没有身体动画，角色就是"半身像"，沉浸感不够：

```
BNOS 现有：  表情 blendshape + 说话口型
SoW 借鉴：   + Mixamo 动画（招手/叉腰/转头等）
             + 空闲呼吸动画
             + 视线追踪
             + 状态感知动画（思考时眼神漂移）
```

---

### 2.5 工具系统 + MCP ❌ grok 已覆盖

> **排除原因**：BNOS 已有 grok_hands 工具系统，grok build 的能力远超 SoW 的简单工具调用（截图/搜索/剪贴板等），此部分不参考，仅作信息记录。

**源码**：[soul_companion.py#L267-L533](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/soul_companion/soul_companion.py#L267-L533)

**内置工具**：

| 工具名 | 作用 | BNOS 状态 |
|--------|------|----------|
| media_control | 播放/暂停/切歌 | 未规划 |
| web_search | DuckDuckGo / Brave API / SearXNG 三级回退 | 未规划 |
| open_url | 浏览器打开 URL | 未规划 |
| get_system_info | 系统时间+日期 | 未规划 |
| take_screenshot | 截图+base64 传给 LLM | 未规划 |
| read_clipboard | 读取剪贴板 | 未规划 |

**MCP 集成**（[soul_companion.py#L869-L870](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/soul_companion/soul_companion.py#L869-L870)）：

```python
class SoulCompanion:
    def __init__(self, system_ref):
        from app.utils.ai_clients.mcp_client import MCPManager
        self.mcp_manager = MCPManager()
```

---

### 2.6 插件加载器（PluginLoader） ❌ grok 已覆盖

> **排除原因**：BNOS 已有 grok_hands，插件系统使用节点级合约匹配（数据流驱动），不需要轻量 Python 插件加载器。

**源码**：[soul_companion.py#L664-L808](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/soul_companion/soul_companion.py#L664-L808)

**设计**：

```python
class PluginLoader:
    PLUGIN_DIR = Path("app/utils/soul_companion/plugins")
    
    def __init__(self):
        self._load_builtins()      # 加载内置 6 个工具
        self._load_user_plugins()  # 扫描 plugins/ 目录下的 .py 文件
    
    def _load_user_plugins(self):
        for py_file in self.PLUGIN_DIR.glob("*.py"):
            spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "Plugin"):
                inst = mod.Plugin()
                if isinstance(inst, BaseTool):
                    self._plugins[inst.name] = inst
```

**对比 BNOS 插件系统**：

| 维度 | BNOS 插件系统 | SoW PluginLoader |
|------|-------------|-----------------|
| 粒度 | 独立进程节点 | 轻量 Python 类 |
| 匹配方式 | 合约匹配（data_type） | 无匹配，手动注册 |
| 运行时 | 独立进程，可热启动 | 同进程，内存加载 |
| 事件订阅 | 消费 output.json | subscribes_to 事件类型 |

---

### 2.7 SoW System 全双工语音系统

**源码**：[sowSystem.py](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/gui/sowSystem.py)

SoW System 是一个全双工语音对话系统，支持用户实时打断 AI 说话。其核心架构：

```
用户麦克风 ─→ PyAudio 采集 ─→ Silero VAD 检测 ─→ Faster Whisper 转写
                               │                      │
                               ├─ 有语音 ─→ 缓冲到帧队列 ─→ 静音检测 → 转写
                               └─ 无语音 ─→ 继续监听
                                                │
                                                ▼
                     AI 说话时 ─→ 检测到用户声音 → 打断 TTS
```

| 组件 | 功能 | 技术选型 |
|------|------|---------|
| 音频采集 | 实时麦克风输入 | PyAudio + 16kHz/512 chunk |
| VAD | 声音活动检测 | Silero VAD（PyTorch） |
| ASR | 语音转文字 | Faster Whisper |
| 状态机 | STOPPED/LISTENING/PROCESSING/SPEAKING | QThread + pyqtSignal |
| 打断逻辑 | AI 说话时用户插话 | 能量检测 + TTS 中断 |

**状态机**（[sowSystem.py#L29-L37](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/gui/sowSystem.py#L29-L37)）：
```
STOPPED ──→ LISTENING ──→ PROCESSING ──→ SPEAKING ──→ LISTENING
    ↑                                                     │
    └──────────────────── 空闲 ────────────────────────────┘
```

每种状态有对应的 UI 环形指示器颜色（绿=监听、黄=处理、蓝=说话、灰=停止）。

**对 BNOS 的价值**：BNOS 目前有独立的 `node_python_asr_input` 和 `node_python_tts` 节点，但没有全双工对话管线。SoW 的 VAD+ASR+打断+TTS 四者联动是 BNOS 语音交互的完整参考实现。

---

### 2.8 AI Factory 多 Provider 体系

**源码**：[ai_factory.py](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/ai_clients/ai_factory.py)

**支持 10 种 provider**，通过统一工厂方法 `get_provider(conversation_method)` 实例化：

| Provider | 默认模型 | 配置方式 |
|----------|---------|---------|
| OpenAI | gpt-4o-mini | API Key + 自定义端点 |
| OpenRouter | 用户选择 | API Key |
| Anthropic | claude-sonnet-4-6 | API Key |
| Google Gemini | gemini-3.5-flash | API Key |
| DeepSeek | deepseek-v4-flash | API Key |
| Grok (xAI) | grok-4.3 | API Key |
| Qwen | qwen3.5-flash | API Key |
| Mistral AI | mistral-small-latest | API Key |
| Z.AI | glm-4.7 | API Key |
| Local LLM | — | Llama.cpp HTTP (port 48596) |

**LocalProvider 的增强**：支持高级采样参数（DRY/XTC/Min-P/Dynamic Temperature），通过 HTTP API 传递给 Llama.cpp 服务端。

每个 Provider 继承自 `base_provider.py` 的 `BaseProvider`，统一提供 `generate_stream()` 接口。

**对 BNOS 的价值**：
1. BNOS 的 `llm_infer` 节点目前只支持本地 LLM 和 OpenAI，可以借鉴 SoW 的工厂模式扩展到更多云端 provider
2. 高级采样参数（DRY/XTC/Min-P）可以集成到本地 LLM 推理中，显著提升生成质量
3. 统一 `generate_stream()` 接口模式可以简化 BNOS 的 LLM 调用层

---

### 2.9 Models Hub 本地模型管理

**源码**：[models_hub.py](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/models_hub.py)

Models Hub 提供了一个集成的 HuggingFace 模型浏览+下载器：

| 功能 | 实现 |
|------|------|
| 搜索 | `HfApi.list_models(search="qwen gguf", limit=100, sort="downloads")` |
| 下载 | `hf_hub_download()` + 进度条 |
| 取消 | QThread 信号中断 |
| LLM 服务管理 | 自动启动 Llama.cpp HTTP 服务端 |

**GUI 流程**：
```
用户打开 Models Hub 面板 → 输入搜索关键词（如 "qwen"）
  → 后台线程搜索 HF Hub → 返回模型列表（带下载量排序）
  → 用户选择模型 → 点击下载（GGUF 文件） → 进度条实时显示
  → 下载完成 → 自动配置 Llama.cpp → 一键启动 LLM 服务
```

**对 BNOS 的价值**：BNOS 目前没有模型下载功能。用户需要手动下载 GGUF 文件放到指定目录。Models Hub 的模式可以给 BNOS 增加 `node_python_model_manager` 节点，让用户直接从 GUI 中搜索和下载模型。

---

### 2.10 图像生成引擎

**源码**：[image_generator.py](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/image_generator.py)

支持 5 种图像生成引擎：

| 引擎 | 类型 | 调用方式 |
|------|------|---------|
| Automatic1111 | 本地 | HTTP API (txt2img) |
| ComfyUI | 本地 | A1111 兼容 API |
| DALL-E 3 | 云端 | OpenAI API |
| NovelAI | 云端 | NovelAI API |
| FLUX | 本地 | HTTP API |

**核心流程**（[image_generator.py#L36-L80](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/image_generator.py#L36-L80)）：
```python
class ImageGenerator:
    async def generate_image(self, core_prompt, character_name):
        # 1. 从配置读取提供商、尺寸、步数
        # 2. 构建完整 prompt（前缀 + 核心 prompt + 负面 prompt）
        # 3. 根据提供商分发到对应方法
        # 4. 保存图片到 gallery 目录
        # 5. 返回相对路径
```

图片存储在 `app/data/gallery/` 目录，支持在聊天中通过右键菜单触发。

**对 BNOS 的价值**：作为 `grok_hands` 工具执行的补充能力。AI 可以在对话中生成角色插图、场景图等。可以注册为 grok_hands 的一个工具。

---

### 2.11 高级文本采样

**源码**：[ai_factory.py#L80-L100](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/ai_clients/ai_factory.py#L80-L100)

SoW 在本地 LLM 推理中集成了 4 种高级采样技术：

| 采样技术 | 作用 | 配置参数 |
|---------|------|---------|
| **DRY 采样器** | 防止多词短语循环（"她走到窗前看着窗外..." 重复） | multiplier/base/allowed_length |
| **XTC 采样器** | 过滤高频 AI 陈词滥调词汇 | probability/threshold |
| **Min-P** | 根据最高概率 token 动态裁剪低概率 token | min_p（默认 0.05） |
| **Dynamic Temp** | 根据置信度动态调整温度 | range（温差范围） |

这些参数通过 HTTP API 传递给 Llama.cpp 服务端的 `/v1/completions` 或 `/v1/chat/completions`。

**对 BNOS 的价值**：BNOS 的 `llm_infer` 节点目前只有基础温度参数。引入高级采样可以显著减少本地模型的重复生成问题（循环短语、车轱辘话）。

---

### 2.12 Lorebook 引擎

**源码**：[prompt_engine.py#L72-L103](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/ai_clients/prompt_engine.py#L72-L103)

Lorebook（知识书）是 SoW 的角色世界设定管理引擎：

| 能力 | 说明 |
|------|------|
| **多绑定** | 一个角色可同时绑定多个 lorebook |
| **语义匹配** | 使用 sentence-transformers 向量搜索匹配相关条目（vs 关键词匹配） |
| **场景张力累积** | 对话中的张力值随时间增长，触发随机事件 |
| **链式依赖** | 多阶段任务线，延迟解锁（"先找到钥匙才能进入密室"） |
| **注入模式** | Passive（背景知识） / Active（系统指令）两种注入方式 |
| **扫描深度** | 可配置的回溯消息条数（n_depth） |

**对 BNOS 的价值**：BNOS 的 MemOS 侧重"记忆"（用户相关的信息），Lorebook 侧重"世界设定"（角色世界观）。两者是补充关系。BNOS 可以利用现有 MemOS 的向量检索基础设施，增加 Lorebook 类型的查询。

---

### 2.13 自定义状态变量 HUD

**源码**：[sowInterface.py#L150-L200](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/gui/sowInterface.py#L150-L200)

无需编码即可在角色卡中创建自定义状态变量，显示在聊天顶部 HUD 中：

| 变量类型 | 显示方式 | 示例 |
|---------|---------|------|
| `int` | 进度条动画 | 好感度 75/100 |
| `bool` | YES/NO 徽章 | 是否中毒: NO |
| `list` | 物品列表 | 背包: [剑, 药水, 钥匙] |
| `str` | 文本标签 | 当前场景: 森林 |

**AI 拦截器**：后端使用弹性解析器处理 LLM 输出的状态更新，即使 JSON 有语法错误也能容忍。

**内置 11 种预设**：Romance / RPG / Survival / Interrogation / Horror / Visual Novel 等。

**对 BNOS 的价值**：
1. 如果 BNOS 引入 SoW 的 Soul Stage RPG 引擎，状态变量 HUD 可以复用
2. 非 RPG 场景下，也可以作为 AI 的"当前状态"可视化显示
3. 在 BNOS 的 Live2D / VRM 显示区域上方叠加 HUD 条

---

### 2.14 角色卡系统（Chub.ai） ❌ 设计冲突

> **排除原因**：BNOS 设计为一用户对应一 AI，AI 记忆与数据库深度绑定，不是可随时替换的角色卡。因此角色卡系统与 BNOS 设计理念不符。

**源码**：[character_cards.py](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/character_cards.py)

SoW 集成了 **Chub.ai** 角色卡市场，支持浏览、搜索和导入角色：

| 功能 | 说明 |
|------|------|
| 热门角色 | 按 trending 排序获取 50 个角色 |
| 搜索 | 按关键词搜索角色卡 |
| 详细信息 | 获取角色名称/标题/头像/人格/示例对话/开场白 |
| V2 卡解码 | 从 PNG 图片中读取 base64 编码的 `chara` 元数据 |
| NSFW 过滤 | 根据设置决定是否包含 NSFW 内容 |

**SoulGateway** 类支持从 PNG 文件解码 V2 格式的角色卡（SillyTavern 兼容格式），解析出角色的人格、场景、示例对话等结构化数据。

---

### 2.15 Web Client 移动端接入

**源码**：[web_server.py](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/web_server.py)

SoW 内置了一个 FastAPI Web 服务器，允许手机/平板通过局域网访问：

| 技术 | 用途 |
|------|------|
| FastAPI | HTTP REST API |
| WebSocket | 实时双向消息同步 |
| StaticFiles | 静态文件服务（assets/） |
| Faster Whisper | 手机端语音输入通过 PC 的本地模型转写 |

**API 端点**：
```
GET  /                  → 返回 Web Client 首页
GET  /api/config       → 获取当前角色/用户配置
GET  /api/avatar_config → 获取角色头像配置
WS   /ws               → 实时消息 WebSocket
```

**WebSocket 双向通信**：手机端发送消息 → PC 端处理 → AI 回复 → 推送到手机端。管理类通过 `ConnectionManager` 维护所有 WebSocket 连接，支持广播和异常断开处理。

**对 BNOS 的价值**：
1. BNOS 可以复用此架构，为未来移动端访问做准备
2. FastAPI + WebSocket 的轻量级方案不引入额外依赖
3. WebSocket 的实时性比轮询更适合聊天场景

---

### 2.16 Discord Gateway

**源码**：[discord_manager.py](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/discord_manager.py)

SoW 支持将 AI 角色连接到 Discord 服务器：

| 功能 | 说明 |
|------|------|
| 消息管道 | Discord 消息 ↔ AI 对话的实时双向桥接 |
| 角色隔离 | 不同 Discord 频道可绑定不同角色 |
| 记忆共享 | Discord 对话同样写入 Soul Memory |

**对 BNOS 的价值**：第三方平台集成，低优先级。可以作为 BNOS 的长远规划。

---

### 2.17 翻译系统

**源码**：[sowInterface.py#L23-L37](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/gui/sowInterface.py#L23-L37)

SoW 使用 **YAML 文件** 实现多语言翻译：

```yaml
# app/translations/en.yaml
menu_file: "File"
menu_edit: "Edit"
settings_language: "Language"
```

```python
def load_translation(self, language):
    file_path = f"app/translations/{language}.yaml"
    with open(file_path, "r", encoding="utf-8") as file:
        self.translations = yaml.safe_load(file)
```

当前支持：英语、俄语。用户可在设置中选择语言，翻译文件热加载。

**对 BNOS 的价值**：BNOS 现有 GUI 的文本全部硬编码在 Python 代码中。YAML 翻译文件的设计可以让 BNOS 更容易扩展到多语言。

---

## 三、与 BNOS 各设计文档的对照

### 3.1 3D 角色自定义系统

| BNOS 方案中的能力 | SoW 对应实现 | 差距分析 |
|-----------------|------------|---------|
| VRM 模型加载 | ✅ 完整的 VRM 加载流程 | SoW 更完善，含优化（removeUnnecessaryVertices） |
| 表情 BlendShape | ✅ setExpression() 含渐变过渡 | SoW 有 duration 参数和动画混合 |
| 说话口型 | ✅ setMouthOpen(value) | 两者一致 |
| **Slot 零件系统** | ❌ 不支持 | **BNOS 独家** |
| **Mixamo 动画** | ✅ loadFBX() + idle animation | **BNOS 缺失** |
| 空闲动画 | ✅ neutral.fbx 循环播放 | BNOS 缺失 |
| 视线追踪 | ✅ VRMSmoothLookAt 阻尼追踪 | BNOS 缺失 |
| 背景切换 | ✅ setBackground(type, color, url) | BNOS 缺失 |

### 3.2 角色种子系统

| BNOS 方案中的能力 | SoW 对应实现 | 差距分析 |
|-----------------|------------|---------|
| 性格向量（4 维） | ❌ 无性格向量 | **BNOS 独家** |
| 预设种子 | ❌ 使用 SillyTavern 角色卡风格 | BNOS 更系统化 |
| prompt 注入 | ❌ 使用固定角色卡系统提示 | **BNOS 独家** |
| 被动演化 | ❌ 无 | **BNOS 独家** |
| **激素情绪系统** | ✅ NeurohormoneSystem | **BNOS 缺失** |
| 记忆迭代 | ✅ Soul Memory（多 Agent） | SoW 更复杂 |
| 对话风格一致性 | ❌ 靠角色卡描述 | BNOS 向量更精确 |

### 3.3 事件驱动型 AI 自主行为

| BNOS 方案中的能力 | SoW 对应实现 | 差距分析 |
|-----------------|------------|---------|
| 三层过滤 | ❌ 无过滤，直接 event_bus | BNOS 更结构化的过滤设计 |
| 观察缓冲区 | ❌ 无 | **BNOS 独家** |
| 迟滞回路 | ❌ 无 | **BNOS 独家**（从 jarvis 借鉴） |
| 代际标记 | ❌ 无 | **BNOS 独家** |
| 防注入 | ❌ 无 | **BNOS 独家** |
| **激素驱动行为** | ✅ energy 决定能否说话 | BNOS 缺失 |
| **冷却机制** | ✅ SPEAK_MIN_GAP_SEC=300s | BNOS 缺失 |
| **主动行为** | ✅ heartbeat 触发 proactive | BNOS 只有"监听环境" |
| **主动概率控制** | ✅ 30% 概率 + 随机话题选择 | BNOS 缺失 |
| **AFK 检测** | ✅ 5 分钟无交互标记 idle | BNOS 缺失 |
| **窗口上下文感知** | ✅ GetForegroundWindow | BNOS 缺失 |
| **全双工语音打断** | ✅ Silero VAD + 能量检测 | BNOS 缺失 |

### 3.4 插件系统

| BNOS 方案中的能力 | SoW 对应实现 | 差距分析 |
|-----------------|------------|---------|
| 合约匹配 | ✅（复杂） | ❌（简单） | BNOS 更完善 |
| 独立进程节点 | ✅ | ❌ 同进程类加载 | 各有优势 |
| **Tool Calling** | ❌ | ✅ LLM 选择工具→执行 | **BNOS 缺失** |
| **MCP 支持** | ❌ | ✅ MCPManager | **BNOS 缺失** |
| 用户安装 | 拖入文件夹 | 拖入 plugins/ 目录 | 相似 |

---

## 四、BNOS 可直接参考/复用的组件

### 4.1 神经激素系统（高价值，低工作量）

**建议**：在 `aaa_cognition/` 下新增 `mood.py`，作为角色种子系统的补充层。

```
性格向量（长期）: warmth/playfulness/directness/curiosity
      + 影响 prompt 表达风格
激素系统（短期）: oxytocin/dopamine/cortisol/energy
      + 影响当前情绪 + 是否主动说话
```

**参考源码**：[soul_companion.py#L117-L184](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/soul_companion/soul_companion.py#L117-L184)

**工作量**：约 0.5 天（纯 Python，无外部依赖）

### 4.2 日记机制 ✅ BNOS 已有

> **已有说明**：BNOS 的 `diary.py` 已实现"次日首条对话触发第一人称日记"机制，`event_summary` 表记录每次交互摘要。SoW 的 Diary Agent 思路相同（都是 LLM 生成第一人称叙事），BNOS 不需要额外参考。

**参考源码**：[diary.py](file:///e:/杂项/BNOS_AI_project/nodes/node_python_aaa_cognition/diary.py)、[event_summary 表](file:///e:/杂项/BNOS_AI_project/BNOS-AI伴侣开发方案.md#L1267)

### 4.3 FBX 动画集成（高价值，中等工作量）

**建议**：在 BNOS 的 Three.js 渲染器中增加 FBX 加载能力，参考 SoW 的 `loadMixamoAnimation` 绑骨映射：

```javascript
const mixamoVRMRigMap = {
    mixamorigHips: 'hips',
    mixamorigSpine: 'spine',
    mixamorigHead: 'head',
    // ... 完整映射见 vrm_module.html#L64-L117
};
```

**参考源码**：[vrm_module.html#L48-L598](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/emotions/vrm_module.html#L48-L598)

**工作量**：约 1 天（前端 JS，需准备 FBX 动画文件）

### 4.4 工具调用 + MCP（高价值，中等工作量）

**建议**：新增 `node_python_tool_executor` 节点，实现 SoW 的 `BaseTool` 体系：

```
AAA prompt → LLM 选择工具 → tool_executor 执行 → 结果回 prompt
```

工具列表（逐步添加）：
1. `web_search`（DuckDuckGo / SearXNG 三级回退）
2. `get_system_info`（时间/日期）
3. `take_screenshot`（截图传给 VLM）
4. `read_clipboard`
5. MCP 客户端

**参考源码**：[soul_companion.py#L267-L533](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/soul_companion/soul_companion.py#L267-L533)、[soul_companion.py#L869-L870](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/soul_companion/soul_companion.py#L869-L870)

### 4.5 窗口上下文感知（中等价值，低工作量）

**建议**：在 BNOS 的事件驱动方案中的 Phase 2 多模态扩展中，增加窗口标题监听：

```python
def get_foreground_window_title() -> str:
    import ctypes
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value
```

**参考源码**：[soul_companion.py#L1656-L1668](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/soul_companion/soul_companion.py#L1656-L1668)

### 4.6 VRM 渲染增强（高价值，低工作量）

**建议**：在 BNOS 现有的 Three.js 渲染器中直接复用以 JS 函数：

| SoW 函数 | BNOS 引入方式 |
|---------|-------------|
| `window.setExpression(expr, duration)` | 直接复用，替换 BNOS 的 setValue |
| `window.loadFBX(url)` | 新增，需准备 FBX 动画 |
| `window.setMouthOpen(value)` | 已兼容 |
| `window.setBackground(type, color, url)` | 新增 |
| 眨眼逻辑 | 直接复用 |

### 4.7 AFK 检测（中等价值，低工作量）

```python
# 15 秒检查一次
def _qt_idle_check(self):
    elapsed = (datetime.now() - self._last_user_input).total_seconds()
    if elapsed >= self.IDLE_THRESHOLD_SEC:  # 5 分钟
        self._is_afk = True
        self.event_bus.emit_threadsafe("idle_away", ...)
```

### 4.8 AI Factory 多 Provider 体系（高价值，中等工作量）

**建议**：在 `node_python_llm_infer` 中新增 Factory 模式，参考 SoW 的 `AIFactory.get_provider()`，将当前单一的 LLM 调用抽象为统一接口：

```python
# 参考 SoW 的工厂模式
provider = AIFactory.get_provider("Anthropic")  # 或 "DeepSeek" / "Qwen" 等
async for chunk in provider.generate_stream(messages):
    yield chunk
```

| Provider | BNOS 现有 | SoW 参考量 |
|----------|:---------:|:---------:|
| OpenAI | ✅ 已有 | 补充自定义端点 |
| OpenRouter | ❌ | ~80 行 |
| Anthropic | ❌ | ~50 行 |
| Gemini | ❌ | ~50 行 |
| DeepSeek | ❌ | ~50 行 |
| Grok | ❌ | ~50 行 |
| Qwen | ❌ | ~50 行 |
| Mistral | ❌ | ~50 行 |
| Z.AI | ❌ | ~50 行 |

**参考源码**：[ai_factory.py](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/ai_clients/ai_factory.py)

**工作量**：约 2-3 天（提供 + provider 实现）

### 4.9 高级文本采样（高价值，低工作量）

**建议**：在 `node_python_llm_infer` 的本地 LLM 调用中，增加对 Llama.cpp 高级采样参数的支持：

```python
advanced_params = {
    "min_p": 0.05,
    "xtc_probability": 0.0,
    "xtc_threshold": 0.1,
    "dry_multiplier": 0.0,
    "dry_base": 1.75,
    "dry_allowed_length": 2,
    "dynatemp_range": 0.5,
}
```

**参考源码**：[ai_factory.py#L80-L100](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/ai_clients/ai_factory.py#L80-L100)

**工作量**：约 0.3 天（纯参数透传，不涉及算法实现）

### 4.10 Models Hub 模型管理器（高价值，中等工作量）

**建议**：新增 `node_python_model_manager` 节点，集成 HuggingFace 搜索+下载+LLM 服务管理：

| 功能 | 参考实现 |
|------|---------|
| HF 模型搜索 | `HfApi.list_models(search="qwen gguf", limit=100)` |
| GGUF 下载 | `hf_hub_download()` + QThread 进度 |
| 服务启停 | 自动启动/停止 Llama.cpp HTTP 服务端 |

**参考源码**：[models_hub.py](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/models_hub.py)

**工作量**：约 1.5 天（GUI 页面 + 后台下载逻辑）

### 4.11 图像生成工具（中等价值，低工作量）

**建议**：在 `grok_hands` 中注册图像生成工具，AI 可在对话中生成图片：

| 引擎 | 集成方式 |
|------|---------|
| Automatic1111 | HTTP API（已有现成） |
| DALL-E 3 | OpenAI API（BNOS 已有 API key 体系） |
| FLUX | HTTP API |

**参考源码**：[image_generator.py](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/image_generator.py)

**工作量**：约 1 天（grok_hands 注册 + prompt 构建）

### 4.12 Lorebook 世界设定引擎（中等价值，中等工作量）

**建议**：借鉴 SoW 的 Lorebook 设计，在 BNOS 的 MemOS 基础上增加"世界设定"查询维度：

```python
class LorebookEngine:
    def __init__(self):
        self.books = {}          # lorebook_name -> {entries: [...]}
        self.tension = {}        # 张力累积
        self.entry_cache = {}    # 已激活条目缓存
    
    def get_relevant_entries(self, context, mode="semantic"):
        # semantic: 向量检索匹配; keyword: 关键词匹配
        ...
```

| SoW Lorebook 能力 | BNOS 复用方式 |
|------------------|-------------|
| 语义匹配 | 复用现有 MemOS 的 sentence-transformers |
| 张力累积 | 新增 `tension` 计数器，影响事件触发概率 |
| 链式依赖 | 新增 `prereq` 字段，条件满足才激活 |
| 注入模式 | 现有 prompt 模板新增 `{lorebook}` 占位符 |

**参考源码**：[prompt_engine.py#L72-L103](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/ai_clients/prompt_engine.py#L72-L103)

**工作量**：约 1.5 天

### 4.13 全双工语音管线（高价值，中等工作量）

**建议**：将 BNOS 现有的 `node_python_asr_input` + `node_python_tts` 增强为全双工对话管线：

```
现有：用户说话 → ASR 文件识别 → 文字 → AAA → TTS 播放
全双工：麦克风实时采集 → Silero VAD → Faster Whisper → AAA → TTS
          ↑                                                       │
          └───────── 用户打断检测（能量/VAD） ←───────────────────────┘
```

| 组件 | BNOS 现有 | 增强方式 |
|------|:---------:|---------|
| 音频采集 | 文件输入 | PyAudio 实时流 |
| VAD | ❌ 无 | Silero VAD（PyTorch） |
| ASR | Whisper 文件 | Faster Whisper 实时 |
| 打断逻辑 | ❌ 无 | 能量检测中断 TTS |
| 状态 UI | ❌ 无 | QThread 信号驱动环形指示器 |

**参考源码**：[speech_to_text.py](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/utils/speech_to_text.py)、[sowSystem.py](file:///e:/杂项/BNOS_AI_project/references/Soul-of-Waifu-main/app/gui/sowSystem.py)

**工作量**：约 2-3 天

---

## 五、BNOS 相比 SoW 的核心优势

| 能力 | BNOS | SoW | BNOS 复用？ |
|------|------|-----|:----------:|
| 性格种子 + 演化 | ✅ 独家设计 | ❌ 固定角色卡 | — |
| Slot 零件换装 | ✅ 独家设计 | ❌ 只能换整模 | — |
| 插件系统（合约匹配） | ✅ 数据流驱动 | ❌ 手动注册 | — |
| 事件三层过滤 | ✅ 迟滞+代际+防注入 | ❌ 无过滤 | — |
| 记忆 decay | ✅ 时间衰减 | ❌ 无 | — |
| 节点化架构 | ✅ 独立进程 | ❌ 单体应用 | — |
| 稳定性 | ✅ 单节点崩溃不影响整体 | ❌ 全挂 | — |
| **神经激素系统** | ❌ **缺失** | ✅ NeurohormoneSystem | 🟢 高优先级 |
| **日记机制（Diary）** | ✅ **已有** | ✅ Diary Agent | — |
| **FBX 动画** | ❌ **缺失** | ✅ Mixamo + idle | 🟢 高优先级 |
| **全双工语音** | ❌ **缺失** | ✅ Silero VAD + 打断 | 🟢 高优先级 |
| **窗口上下文感知** | ❌ **缺失** | ✅ GetForegroundWindow | 🟢 中优先级 |
| **桌面叠加模式** | ❌ **缺失** | ✅ 透明窗口 | 🟢 参考设计 |
| **记忆自愈** | ❌ **缺失** | ✅ 矛盾检测+覆盖 | 🟢 参考设计 |
| **VRM 平滑视线** | ❌ **缺失** | ✅ VRMSmoothLookAt | 🟢 直接参考 |
| **Lorebook 世界设定** | ❌ **缺失** | ✅ 语义匹配+张力 | 🟡 可选增强 |
| **高级采样** | ❌ **缺失** | ✅ DRY/XTC/Min-P | 🟡 可选增强 |
| **图像生成** | ❌ **缺失** | ✅ 5 引擎 | 🟡 可选增强 |
| AI Factory 多 Provider | ❌ 仅本地+OpenAI | 10 云端+本地 | 🟡 远期考虑 |
| Models Hub 模型管理 | ❌ 无 | ✅ HF 搜索+下载 | 🟡 远期考虑 |
| Web Client 移动端 | ❌ 无 | ✅ FastAPI+WebSocket | 🟡 远期考虑 |
| **工具调用 + MCP** | ❌ **缺失** | ✅ 6 工具 + MCP | 🔴 **grok 已覆盖** |
| **插件加载器** | ❌ **缺失** | ✅ PluginLoader | 🔴 **grok 已覆盖** |
| **角色卡市场（Chub.ai）** | ❌ **缺失** | ✅ 角色卡导入 | 🔴 **设计冲突** |
| **RPG 引擎（Soul Stage）** | ❌ **缺失** | ✅ GM+WorldState | 🔴 **设计冲突** |
| Discord Gateway | ❌ 无 | ✅ Discord 桥接 | 🔴 **设计冲突** |
| LLM 支持范围 | 本地 + OpenAI | 10 云端 + 本地 | — |
| 社区生态 | 待建立 | Discord 社区 | — |

### 按 BNOS 设计约束过滤后的复用优先级

| 优先级 | 模块 | 工作量 | 依据 |
|--------|------|:-----:|------|
| **P0 高价值推荐** | 神经激素系统 | ~0.5天 | 增强单一 AI 的情绪深度，与设计兼容 |
| | FBX 动画集成 | ~1天 | 让 VRM 角色有自然动作，提升陪伴感 |
| | 全双工语音管线 | ~2-3天 | 实时语音对话，核心交互体验 |
| **P1 中价值可选** | 窗口上下文感知 | ~0.5天 | 让 AI 知道用户在做什么，提升主动性 |
| | VRM 平滑视线 | ~0.3天 | 视觉体验细节优化 |
| | Lorebook 世界设定 | ~1.5天 | 可选的设定丰富，而非必需 |
| | 高级文本采样 | ~0.3天 | 改善输出质量，非必需 |
| | 图像生成 | ~1天 | AI 能力扩展，非核心 |
| **P2 远期考虑** | AI Factory / Models Hub / Web Client | 各 1-3天 | 与 BNOS 现有架构兼容，但不急迫 |
| **🔴 不推荐** | 工具系统 + MCP | — | grok_hands 已覆盖 |
| | 插件加载器 | — | grok_hands 已覆盖 |
| | 角色卡系统 | — | 与"一用户一 AI"设计冲突 |
| | Soul Stage RPG | — | 与"一用户一 AI"设计冲突 |
| | Discord Gateway | — | 桌面 AI 场景不需要多平台接入 |

---

## 六、风险与注意事项

1. **SoW 是 GPL v3 协议**，BNOS 引用其设计思路没有问题，但不应直接复制代码。上述参考均为"设计模式借鉴"，具体的 Python/JS 实现需 BNOS 自己写。

2. **SoW 的激素系统代码约 70 行**，实现简单但依赖 LLM 做决策（_call_companion 每次都调 LLM）。BNOS 如要集成，可通过 `mood.py` 纯逻辑实现（不增加 LLM 调用次数）。

3. **SoW 的 Soul Memory 每次更新都调 LLM**（Router + Archivist + Diary），对本地模型来说成本较高。BNOS 的 MemOS 使用纯向量检索+decay，没有 LLM 调用成本。如要集成 Diary 机制，建议控制频率（每 N 次对话触发一次）。

4. **SoW 的 VRM 渲染需要加载 FBX 文件**（约 1-3MB/个），BNOS 需要准备一批基础动画文件。可以从 Mixamo 免费下载绑定到 VRM 的 FBX。

5. **SoW 的网站搜索依赖第三方 API**（DuckDuckGo / SearXNG），BNOS 如果做离线版需要注意网络依赖问题。

6. **SoW 的全双工语音依赖 PyAudio + Silero VAD + Faster Whisper**，三者合计约 2GB 磁盘（Whisper 模型）+ 2GB 运行时内存。BNOS 集成时需要注意资源占用。

7. **SoW 的 Models Hub 需要 HuggingFace Hub 网络访问**（国内需要镜像），且 GGUF 文件通常 4-20GB，下载时间和存储空间需提前考虑。

8. **SoW 的角色卡市场使用 Playwright 绕过 Cloudflare**，这种方式不稳定（Cloudflare 规则会变）。BNOS 如果做角色市场，建议用官方 API 或自建市场。

9. **SoW 的 Soul Stage RPG 引擎一次交互调 2-3 次 LLM**（Planner + Executor + Routing + NPC + Character），Token 消耗较大。BNOS 如果要集成，建议限制场景模式下的 LLM 调用频率。

---

*本文档基于 `Soul-of-Waifu v2.4.0` 源码分析生成，与 BNOS 现有设计文档对照分析。*
