# 2026-08-08 更新总览

[返回总索引](../README.md)

---

## 更新目录

- [01 消息池多用户交互实验基础设施](#01-消息池多用户交互实验基础设施)
- [02 消息池实验数据收集设施与多 Agent 启动脚本](#02-消息池实验数据收集设施与多-agent-启动脚本)
- [03 角色种子系统 GUI 与人格格式化收尾](#03-角色种子系统-gui-与人格格式化收尾)
- [04 地图独立标签页](#04-地图独立标签页)
- [05 数据库冗余清理与 MemOS 索引去重](#05-数据库冗余清理与-memos-索引去重)
- [06 知识图谱物理引擎修复](#06-知识图谱物理引擎修复)
- [07 知识图谱数据源语义过滤与"想法"分类](#07-知识图谱数据源语义过滤与想法分类)
- [08 多 Agent 随机角色种子、自我介绍与话题发放](#08-多-agent-随机角色种子自我介绍与话题发放)
- [09 Agent 间多轮对话与话题轮数控制](#09-agent-间多轮对话与话题轮数控制)
- [10 避让机制防自言自语与聊天室措辞](#10-避让机制防自言自语与聊天室措辞)
- [11 话题报告生成器：相互认知记忆与人格漂移分析](#11-话题报告生成器相互认知记忆与人格漂移分析)
- [12 认知记忆生成指名说话对象：多用户歧义修复](#12-认知记忆生成指名说话对象多用户歧义修复)
- [13 Agent 子进程化：平台维护多个独立 AAA 子进程（F9）](#13-agent-子进程化平台维护多个独立-aaa-子进程f9)
- [14 意识流同步：静默决策也更新想法](#14-意识流同步静默决策也更新想法)
- [15 API 调用量统计：实验报告记录总量与各 Agent 调用量](#15-api-调用量统计实验报告记录总量与各-agent-调用量)

---

## 摘要

| # | 核心改动 | 根因 | 影响 |
|---|---------|------|------|
| 01 | 按 `[PLAN] 消息池与弹幕式消息处理方案` 开发多用户交互实验基础设施（F1–F8，先不做实验）：AAA 侧新增 `_on_pool_batch` 批量入口与 `batch_mode` 显式 `{action: reply|silent}` 决策、v6.0 user_id 维度迁移与多用户认知检索隔离；平台侧新增 `tests/message_pool/` 包（事件总线 / 弹幕消息池 / @ 点名路由 / 发言仲裁器 / 数据采集器 / Agent 桥接 / 平台编排） | 多 Agent 弹幕场景需要批量消费、区分说话用户、认知隔离、静默处理、单一发言权与结构化数据采集，现有 `_on_text` 单条路径与无用户维度记忆无法支撑 | GUI 直连与既有测试不受影响（新参数带默认值）；消息池实验可复用平台包编排多 Agent 并采集 events/decisions/evolution 数据 |
| 02 | 补齐实验数据收集与启动：新增 `data_export.py`（每个 Agent 原始数据库按表分类导出 + 聊天历史 md 渲染）、`collector.py`/`platform_runner.py` 增加 `chat_history.jsonl`（用户弹幕 + Agent 广播）、新增 `run_pool_experiment.py` 启动脚本（`--agents` 默认 5，按需调整数量） | 实验需要"原始 DB 按表分类 + 消息池聊天历史 + 一键拉起多 Agent"，原平台仅有 events/decisions/evolution，DB 导出逻辑散落在旧验收脚本且未集成 | 每次运行独立时间戳留档（runs/ 目录），产物含 db/{agent}_final/ 各表 JSON + sqlite、chat_history、events/decisions/evolution、_run_meta |
| 03 | 角色种子系统 Phase 3/4 收尾：`write_seed_background` 改为写入 `event_summary`（source='seed'，幂等）；`format` 与"清空数据库"合并——彻底清空全部表（含 fixed_cognition）+ 重置性格 + 清 GUI 对话历史；性格参数滑块维度名统一全角冒号 | 种子背景写入长期记忆表（存 QA）语义错位；格式化未彻底清库且与清空功能重复；滑块维度名半角冒号不统一 | 设置面板仅保留"人格格式化（清空并重来）"一个入口；重复格式化不产生重复种子背景 |
| 04 | 地图从设置悬浮窗迁移为侧边栏独立标签页：新建 `location_page.py`（LocationPage），sidebar 增加"地图"标签，main_window 注册并懒加载，设置面板移除地图区域 | 地图属运行时状态可视化，与设置配置项混放导致面板臃肿、空间不足 | 侧边栏可切换到独立地图页，地图组件按需懒加载 |
| 05 | 数据库冗余清理 + MemOS 索引去重：v5.4 迁移 `DROP TABLE retrieval_log`（死表）；MemOS 索引移除 user_messages 源（只索引 long_term_memory + diaries），删除 `_fetch_feeling` 死代码；数据浏览补 mood_value/personality_seed 翻译、移除 retrieval_log 残留翻译 | retrieval_log 从未写入数据；对话已合并 QA 进 long_term_memory，双源索引同一内容导致检索重复 | 检索无重复命中；数据浏览所有表名均有中文翻译 |
| 06 | 知识图谱物理引擎修复：节点同坐标（画布中心）生成 + 随机冲量；力尺度 L 缩放斥力半径与吸引平衡距离（25~120 clamp）、中心重力固定；移除矩形硬边界反弹改圆形软边界（750px 内无边界力）；`_expand_scene_to_fit` 动态扩展画布；连线流式生成 | 随机坐标破坏物理起始态；L 只改斥力强度导致力尺度失效；margin=30 矩形反弹在大力尺度下把节点推成正方形轮廓 | 力尺度拉到最大时节点自由散布成圆形分布、不再有正方形轮廓；L=1 默认布局行为不变 |
| 07 | 知识图谱数据源语义过滤与"想法"分类：`MEMORY_QUERIES` v4 过滤（feelings 只留有 thought、long_term_memory 剔除 tool/diary/超短、纳入 diaries 表，GRAGH_INDEX_VERSION 3→4）；feelings category 统一为 'feelings'（v5）；数据浏览标签"情感"→"想法"；图谱 hover 显示 [想法] | 低区分度记录（纯情绪词/工具返回/整篇日记）与瞬时元数据表塞满图谱；想法（thought）未以"想法"展示 | 图谱 117 节点全部为有效语义记忆；数据预览出现"想法"分类 |
| 08 | 多 Agent 实验启动初始化：随机角色种子（四维性格向量 0.1~0.9 + 6 种说话风格池随机抽取，`--seed` 固定可复现）+ 每个 Agent 基于角色设定做自我介绍（stage=self_intro）+ 自我介绍后平台发放话题（`--topic` > `topic.txt` > 默认）；修复 `init_character` 未建表导致 personality_seed 写入静默失败 | 原固定种子使 Agent 初始设定完全相同；启动无自我介绍与话题阶段，话题也无法配置 | 每次启动 Agent 角色差异化；chat_history 含自我介绍与平台话题；`_run_meta.json` 记录 seed/topic；改 `topic.txt` 即可换话题重启实验 |
| 09 | Agent 间多轮对话与话题轮数控制：广播发言回投消息池（source=agent、dedup=False），其他 Agent 下一轮接话构成连续对话；`--topic-rounds N`（默认 10，0=不限，只统计成功入池的 agent 发言，后台思考/总结不计）达到后平台主动宣告话题结束（role=system 公告 + topic_ended 事件）；`enqueue_input` 增加 dedup 参数；主循环改会话驱动 | Agent 广播发言不入池，Agent 之间无法连续对话；话题会话长度无法控制 | 验收 39/39；真实测试 2 Agent 10 轮自然对话（拼图隐喻连续延伸），第 10 轮平台宣告结束、Agent 回应最后一句后停止 |
| 10 | 避让机制（防自言自语）：上一条 agent 广播发言者下批跳过决策（@ 点名豁免，其他 Agent 均沉默时解除防停滞），不侵入 AAA（身份判断由平台记录 agent_id 完成）；修复 `arbiter.release()` 返回语义导致 QUEUE 排队发言丢失的潜伏 bug；措辞统一『弹幕』→『聊天室』 | 无点名时派发顺序固定，先到先得发言权形成单 Agent 系统性主导；QUEUE 排队发言从未被广播 | 验收 42/42；真实测试 2 Agent 10 轮对话序列交替 5:5，不再自言自语，排队发言正常广播 |
| 11 | 话题报告生成器 `topic_report.py`：话题结束生成 `topic_report.md`，分析相互认知记忆（other_cognition 按认知方×对象矩阵 + 双向判定 + 内容摘录）与人格漂移倾向（初始种子 vs 最终向量欧氏距离）；`_run_meta.json` 记录每个 Agent 初始种子；收尾自动生成报告；**n-agent 全覆盖**（glob 自动发现全部 Agent，验收 3-Agent 双重验证）（对齐实验设计方案采集方法） | evolution.json 只有他人认知计数，无法回答"Agent 间是否相互认识"与"人格是否漂移"两个科学问题；personality_seed 表只存最终向量，初始种子未落盘无法计算漂移基线 | 验收 57/57（新增 U6 15 项）；yield10 真实 run 报告显示双向认知已形成（0→1×4、1→0×3）、漂移 0（短话题不触发演化门槛）；3-Agent fake run 矩阵 3×3+其他、gid 正确；旧 run 无 seeds 自动回退 decisions 首条快照；修复 run_dir 名含 `_final` 时误伤全部 Agent 库 |
| 12 | 认知记忆生成指名说话对象：DIRECT_TEMPLATE【他人认知】【用户信息】【用户记忆】注入 `current_user_label`（user_id，回退"用户"），要求点名对象 + 详细描述；Background Review 沉淀链路（build_review_prompt / persist_insight / run_review / 触发链 / 回执回调）透传 user_id，declarative 用户事实按说话对象归属落库 user_facts | LLM 生成他人认知/用户信息/用户记忆用笼统"用户"二字未点名对象，review 沉淀 declarative 也无 user_id → 多人场景记忆无主、检索交叉混淆 | Prompt 构建验证（三段渲染"当前对话对象 agent:1"）；review declarative 落库 user_id='agent:1'；验收 57/57 无回归；单用户行为不变（回退"用户"/归全局） |
| 13 | Agent 子进程化（F9）：平台为父进程、每 Agent 一个独立 AAA 子进程。新增 `aaa_serve.py` 常驻服务（stdin/stdout 每行 JSON 协议：ping/pool_batch/flush_review/shutdown；LLM 经环境变量注入；AAA_SKIP_HEAVY=1 跳过模型加载）；`agent_bridge.py` 改 subprocess 桥接（崩溃自动重启 + 日志重定向 + close 回收）；`platform_runner.py` 并行决策 + @ 优先级仲裁（决策完成后按点名排序，非先到先得）；`run_pool_experiment.py` 默认子进程模式 + `--inline` 单进程对照保留 | 单进程多 AAA 实例共享 memos 索引有竞态/native 崩溃风险、崩溃连坐、GIL 下无法真并行；LLM 为 HTTP 直连天然支持并发 | 进程级隔离（memos 索引/后台线程每子进程独立）、崩溃隔离自动重启、并行决策提速；内存预算每子进程 ~80MB（Agent ≤ 5）；AAA 节点代码零改动 |
| 14 | 意识流同步：静默决策（action=silent）也更新想法/心情。prompt.py【想法】强制输出（即使【自然回复】留空也必须写意识流）+【自然回复】明确静默=留空；main.py batch_mode 兜底（无想法→"收到消息，保持观察，暂不回应"、无心情→"平静"）；回不回复只看【自然回复】有无文本（判断逻辑未变）。测试稳定性：I1/I2 共享 fake_llm 计数器改每 Agent 独立确定性 LLM（消除 F9 并行线程竞态），U7 ping 阈值 1s→2s | 真实 LLM 静默时未输出【想法】节，`parse_llm_output` 空节跳过 → decisions.jsonl 里 silent 记录想法/心情为空；fake LLM 固定输出想法故冒烟未暴露 | 临时脚本验证 3 场景（reply+想法 / silent+想法 / silent 兜底）；`infra_acceptance_test.py` 连续两次 64/64；GUI 单用户对话不受影响（batch_mode=False 不经过兜底） |
| 15 | API 调用量统计：aaa_serve `_make_llm` 计数包装（决策 + 后台 review 全经过 llm_fn）+ 新增 `llm_stats` 协议请求；agent_bridge 新增 `llm_stats()`（subprocess 查子进程计数 / inline 决策路径计数）；run_pool_experiment 平台直连计数 + 收尾落盘 `llm_stats.json`（mode/fake_llm/platform_direct/per_agent/total）；topic_report 报告新增「四、API 调用量统计」节（总量 + 子进程/直连拆分 + 各 Agent 明细占比，缺失降级） | 子进程架构下 LLM 调用在 AAA 子进程内，平台看不到调用次数，协议无统计通道；实验无法核算 API 成本与调用分布 | 验收 68/68（U7 llm_stats 2 项 + U6 报告 2 项）；冒烟 total=35（子进程 32 + 直连 3）；5 Agent 40 轮真实实验报告展示总量与明细 |

---

### 01 消息池多用户交互实验基础设施

详见 [01_消息池多用户交互实验基础设施.md](./01_消息池多用户交互实验基础设施.md)。

### 02 消息池实验数据收集设施与多 Agent 启动脚本

详见 [02_消息池实验数据收集与多Agent启动脚本.md](./02_消息池实验数据收集与多Agent启动脚本.md)。

### 03 角色种子系统 GUI 与人格格式化收尾

详见 [03_角色种子系统GUI与人格格式化收尾.md](./03_角色种子系统GUI与人格格式化收尾.md)。

### 04 地图独立标签页

详见 [04_地图独立标签页.md](./04_地图独立标签页.md)。

### 05 数据库冗余清理与 MemOS 索引去重

详见 [05_数据库冗余清理与MemOS索引去重.md](./05_数据库冗余清理与MemOS索引去重.md)。

### 06 知识图谱物理引擎修复

详见 [06_知识图谱物理引擎修复.md](./06_知识图谱物理引擎修复.md)。

### 07 知识图谱数据源语义过滤与"想法"分类

详见 [07_知识图谱数据源语义过滤与想法分类.md](./07_知识图谱数据源语义过滤与想法分类.md)。

### 08 多 Agent 随机角色种子、自我介绍与话题发放

详见 [08_多Agent随机角色种子自我介绍与话题发放.md](./08_多Agent随机角色种子自我介绍与话题发放.md)。

### 09 Agent 间多轮对话与话题轮数控制

详见 [09_Agent间多轮对话与话题轮数控制.md](./09_Agent间多轮对话与话题轮数控制.md)。

### 10 避让机制防自言自语与聊天室措辞

详见 [10_避让机制防自言自语与聊天室措辞.md](./10_避让机制防自言自语与聊天室措辞.md)。

### 11 话题报告生成器：相互认知记忆与人格漂移分析

详见 [11_话题报告生成器相互认知与人格漂移分析.md](./11_话题报告生成器相互认知与人格漂移分析.md)。

### 12 认知记忆生成指名说话对象：多用户歧义修复

详见 [12_认知记忆生成指名说话对象.md](./12_认知记忆生成指名说话对象.md)。

### 13 Agent 子进程化：平台维护多个独立 AAA 子进程

详见 [13_Agent子进程化平台多Agent独立AAA进程.md](./13_Agent子进程化平台多Agent独立AAA进程.md)。

### 14 意识流同步：静默决策也更新想法

详见 [14_意识流同步静默决策也更新想法.md](./14_意识流同步静默决策也更新想法.md)。

### 15 API 调用量统计：实验报告记录总量与各 Agent 调用量

详见 [15_API调用量统计实验报告记录.md](./15_API调用量统计实验报告记录.md)。

---

## 修改文件清单

### 新增文件

| 文件 | 所属 |
|------|------|
| `tests/message_pool/__init__.py` | #01、#10（措辞） |
| `tests/message_pool/event_bus.py` | #01 |
| `tests/message_pool/message_pool.py` | #01、#09、#10（措辞） |
| `tests/message_pool/router.py` | #01 |
| `tests/message_pool/arbiter.py` | #01、#10（release 返回语义修复） |
| `tests/message_pool/collector.py` | #01、#02、#10（措辞） |
| `tests/message_pool/agent_bridge.py` | #01、#10（措辞）、#13（subprocess 桥接）、#15（llm_stats + inline 计数） |
| `tests/message_pool/platform_runner.py` | #01、#02、#08、#09、#10（避让机制）、#13（并行决策 + 优先级仲裁） |
| `tests/message_pool/data_export.py` | #02、#08、#09、#10（措辞） |
| `tests/message_pool/run_pool_experiment.py` | #02、#08、#09、#10（措辞）、#13（--inline + aaa_env + 回收）、#15（直连计数 + llm_stats.json） |
| `tests/message_pool/topic.txt` | #08 |
| `tests/message_pool/infra_acceptance_test.py` | #01、#02、#08、#09、#10（42 项）、#11（U6 9 项）、#13（U7 7 项）、#14（fake_llm 独立确定性 + ping 阈值）、#15（llm_stats 2 项 + 报告统计 2 项） |
| `tests/message_pool/topic_report.py` | #11、#15（API 调用量统计节） |
| `tests/message_pool/aaa_serve.py` | #13、#15（计数包装 + llm_stats 协议） |
| `tests/message_pool/README.md` | #01、#02、#08、#09、#10、#11 |
| `docs/cogevo/[PLAN] 消息池与弹幕式消息处理方案（多用户交互实验）.md` | #01、#10（措辞） |
| `gui/pages/location_page.py` | #04 |

### 重大修改文件

| 文件 | 改动 | 所属 |
|------|------|------|
| `nodes/node_python_aaa_cognition/db.py` | v6.0 user_id 列迁移（user_messages / event_summary / other_cognition / user_facts）；`_dedup_and_merge` / `_write` / `_write_parsed` 增加 user_id 维度；新增 `g_where_identity_user` 检索（用户专属优先、全局兜底） | #01 |
| `nodes/node_python_aaa_cognition/main.py` | 新增 `_on_pool_batch` 批量入口（批量写库 + F5 合并上下文 + `_observe_counter` 静默观察计数）；`_on_parsed` 增加 `batch_mode` 显式决策返回；`_gather_context` 增加 `user_id` / `batch_items` / `pool_batch_section`；修复反思轮 pending 上下文丢失 | #01 |
| `nodes/node_python_aaa_cognition/prompt.py` | `_CONTEXT_HEADER` 他人认知标签与用户文本改为占位符，支持按 user_id 渲染与批量输入段 | #01 |
| `nodes/node_python_aaa_cognition/prompt.py` | #12 【他人认知】【用户信息】【用户记忆】注入 `current_user_label`（点名对象 + 要求详细） | #12 |
| `nodes/node_python_aaa_cognition/prompt.py` | 【想法】强制输出（静默也必须写意识流）+【自然回复】明确静默=留空 | #14 |
| `nodes/node_python_aaa_cognition/main.py` | `_on_parsed` batch_mode 兜底想法/心情默认值（静默决策也带状态） | #14 |
| `tests/message_pool/collector.py` | 新增 chat_history.jsonl 输出与 `chat()` 方法 | #02 |
| `tests/message_pool/platform_runner.py` | inject/step/drain_queue 记录聊天历史（role=user / agent） | #02 |
| `tests/message_pool/platform_runner.py` | 新增 `record_speech`（自我介绍，不入池）与 `announce`（话题发放，入池 + 记录 role=topic） | #08 |
| `tests/message_pool/data_export.py` | 聊天历史 md 渲染支持 role=topic 与 agent stage 标注 | #08 |
| `tests/message_pool/run_pool_experiment.py` | 随机角色种子（--seed 可复现）、自我介绍阶段、话题发放（--topic/--topic-file）、init_character 修复 ensure 建表 | #08 |
| `tests/message_pool/platform_runner.py` | `topic_rounds` 轮数控制、广播发言回投消息池（`_feed_agent_speech`）、平台宣告话题结束（`_end_topic`） | #09 |
| `tests/message_pool/message_pool.py` | `enqueue_input` 增加 `dedup` 参数（agent 回投跳过去重） | #09 |
| `tests/message_pool/run_pool_experiment.py` | `--topic-rounds` 参数（默认 10，0=不限）、会话驱动主循环 | #09 |
| `tests/message_pool/run_pool_experiment.py` | `_run_meta.json` 记录每个 Agent 初始种子（seeds）；收尾调用 `generate_topic_report` 输出 topic_report.md | #11 |
| `tests/message_pool/topic_report.py` | 新增：相互认知矩阵/双向判定/内容摘录、人格漂移（初始种子 vs 最终向量欧氏距离）、E3 采集指标表 | #11 |
| `tests/message_pool/data_export.py` | 聊天历史 md 渲染 role=system（平台结束公告） | #09 |
| `nodes/node_python_aaa_cognition/db.py` | `write_seed_background` 写入目标从 long_term_memory 改为 event_summary（source='seed'）；v5.2 迁移增加 event_summary.source 列 | #03 |
| `nodes/node_python_aaa_cognition/main.py` | 删除 clear 命令；format 彻底清空全部表 + `reset_personality_seed` + `_clear_conversation_history` 清 GUI 对话历史 | #03 |
| `nodes/node_python_aaa_cognition/review.py` | #12 `build_review_prompt` 标注说话对象（user_id）；`persist_insight` / `run_review` 透传 user_id，declarative 用户事实按说话对象归属落库 user_facts | #12 |
| `nodes/node_python_aaa_cognition/main.py` | #12 review 触发链（`_get_recent_conversation` / `_trigger_background_review` / `_run_background_review` / `_on_review_response`）透传 user_id | #12 |
| `gui/pages/settings_panel.py` | 移除"清空数据库"按钮合并为"人格格式化"；性格参数维度名全角冒号 | #03、#04 |
| `gui/dialogs/personality_dialog.py` | 滑块维度名全角冒号 | #03 |
| `gui/widgets/sidebar.py` | 新增"地图"标签 | #04 |
| `gui/main_window.py` | 注册 location 页面；`_after_page_switch` 懒加载 | #04 |
| `nodes/node_python_aaa_cognition/db.py` | v5.4 迁移删除 retrieval_log（含移除建表） | #05 |
| `nodes/node_python_aaa_cognition/memos.py` | 索引源移除 user_messages（只索引 long_term_memory + diaries）；删除 `_fetch_feeling` 死代码 | #05 |
| `gui/widgets/knowledge_panel.py` | 翻译补全 mood_value/personality_seed，移除 retrieval_log 翻译 | #05 |
| `gui/widgets/knowledge_graph.py` | 同坐标生成；力尺度 L 缩放（斥力半径/吸引平衡距离）；重力固定；圆形软边界替代矩形硬边界；`_expand_scene_to_fit` 动态画布；连线流式生成；节点显示重置 + 冲量 | #06 |
| `nodes/node_python_aaa_cognition/memos.py` | MEMORY_QUERIES v4 语义过滤 + 纳入 diaries（GRAGH_INDEX_VERSION 3→4）；feelings category 改 'feelings'（GRAGH_INDEX_VERSION 4→5） | #07 |
| `gui/widgets/knowledge_panel.py` | TABLE_LABELS feelings "情感"→"想法" | #07 |
| `gui/widgets/knowledge_graph.py` | CATEGORY_LABELS 映射 + hover tooltip 显示"想法" | #07 |

---

**最后更新**：2026-08-08
