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
- [16 回应上下文标注：聊天记录与决策上下文可读"回答谁"](#16-回应上下文标注聊天记录与决策上下文可读回答谁)
- [17 实验数据质量与机制修复：失败/静默分离、user_id 归因、末位偏置、人格演化断链、引用链注入](#17-实验数据质量与机制修复失败静默分离user_id-归因末位偏置人格演化断链引用链注入)
- [18 六项数据质量修复与末位偏置冷板凳轮转](#18-六项数据质量修复与末位偏置冷板凳轮转)
- [19 批次顺序事实源统一与七项数据采集实施](#19-批次顺序事实源统一与七项数据采集实施)
- [20 兴趣门控回复机制](#20-兴趣门控回复机制)

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
| 16 | 回应上下文标注：prompt 新增【回应对象】条件输出节（仅多消息批量场景渲染）；batch_mode 决策返回【回应对象】字段；agent_bridge 记录 batch_context（批次作者 + 内容摘录）；data_export 渲染标注「LLM 显式回应对象 > 批次作者列表」+ 旧数据重建批次回退（按弹批规则） | 多 Agent 聊天记录看不出每个 agent 在回答谁：prompt 无回应对象输出要求、决策无字段、渲染无标注 | 验收 78/78（U8 10 项 + I1/I2 3 项）；101510 重渲染标注生效；103432 LLM 显式回应对象落盘并优先渲染 |
| 17 | 实验数据质量与机制修复：**P0-1** 失败/静默分离（agent_bridge/platform_runner 失败 → `action=error`，collector error_count，topic_report 静默口径排除 error）；**P0-2** user_id 归因 = LLM 显式回应对象（静默/群聊不归因，不再取批次末尾）；**P1-3** 回应对象末位偏置（`_batch_for` 把 @ 消息移末位 + prompt 引导）；**P1-4** 人格演化断链（`_adjust_vector` 支持 neutral 反馈演化，根因是 reaction 恒 neutral 导致 pos/neg 空永不调整）；**引用链注入 v6.4**（Message/arbiter/回投/批次标注四层透传 reply_to，LLM 决策可见"谁回应谁"） | 5a40r_v2 实验欠费中断后分析报告暴露：189 条 402 失败落 silent 污染静默率（84% 假指标）、user_id 归因批次末尾（3 次复现）、末位偏置致认知黑洞、人格零漂移（情绪能动管线断链）；引用链缺失使 LLM 决策与人类阅读不一致 | 验收 96/96（U9 12 项 + U10 6 项）；llm_stats 修复验证 total=291 各 agent 全 > 0；待充值后重跑 5 Agent 40 轮实验 |
| 18 | 六项数据质量修复（111908 数据核对分析驱动）：**A** 防自认知污染（batch_mode 归因排除 `回应对象==identity_key`）；**B** 静默模板分 action（reply 无想法兜底空串，只有 silent 用"保持观察"）；**C** 幽灵发言口径标注（topic_ended 后残余批次 decisions 落 `topic_ended=True`，evolution 三口径字段 agent_speech_count/rounds_metric）；**D** 截断防御（max_tokens 2048→4096 + parser 残缺节标记剥离）；**E** 末位偏置冷板凳轮转（被回应最少者发言移批次末位，@ 优先豁免）；**F** 情绪标签强制（reply/silent 都必须输出【情绪调整】数字） | 汇报数字不符（双向认知实为 6 组非 7、决策实为 7-11 次非 12-15）+ 6 项实锤：agent:2 自认知污染、静默模板污染 reply、话题结束后 4 条幽灵发言、回复截断、末位偏置致 agent:0 认知黑洞（跨实验稳定复现）、agent:3 情绪恒 0 | 验收 111/111（U11 15 项）；v2 重跑实证：agent:0 黑洞打破（矩阵列 1/2/3/4）、双向认知 8 组、截断 0 条、静默模板污染 0 条、自认知 0 条、幽灵发言 4 条已标记；llm_stats total=62 无 402；人格漂移仍 0（短实验触不到演化门槛，待降阈值） |
| 19 | v6.6 六问题修复 + 七项数据采集实施（111908 分析报告驱动）：**P0-1** 批次顺序唯一事实源（Message.seq 全局序号 + `ordered` 单源，decisions/events 同源互证）；**P0-2** 空 user_id 过滤（批量模式 skip_empty_other 写侧 + 读取侧防御）；**P1-3** 幽灵发言源头熔断（step/drain_queue 在 `not topic_active` 提前返回）；**P1-4** 截断检测 + 重试（is_truncated 双信号：未闭合节标记 / 有回复缺情绪调整）；**P1-5** 末位偏置量化指标（reply_target_pos/batch_last_author/mention_responded/attribution_ok）；**P1-6** 演化兜底阈值 30→10；**采集**：memory_usage 表（P0-1）、silent_cognition 表（P0-2）、evolution.trajectory（P0-3）、topic_report 五~十一章（P1-4/P1-5/P2-6/P2-7） | v2 分析报告遗留：批次顺序两套来源、空归因污染认知矩阵、幽灵发言未根除（35 vs 30）、round_9_agent_1 截断、末位偏置仍高、人格零漂移（阈值 30 不可达） | 验收 142/142（U12 31 项）；v3 重跑实证：P0-1/P0-2/P1-3/P1-4 消除（events 带 seq 同源、矩阵无空键、31 vs 30 熔断正常、截断 0）；P1-5 量化 80.6% 仍在（采集达成）；P1-6 阈值 10 仍未触发（待降 ≤5）；采集数据：silent_cognition 6 条、trajectory 齐备、双向认知 0→6、归因正确率 93%、memory_hits 0（未触发检索） |
| 20 | v7.0 兴趣门控回复机制（回应对象显式判定，5a30r_v3 末位偏置 80.6% 的机制性修复）：新增 `interest_gate.py`（平台共享多语模型，编码一次比对多次；兴趣锚点=最近发言；`sim(msg, 锚点)≥0.60` 过门）；门控只决定"谁决策"（LLM 上下文仍完整批次）；未过门不调 LLM（省调用）；判定结果（**检测文本 + 兴趣值**，用户明确要求）写入各 agent 数据库 `interest_judgment` 表；`@/reply_to` 直接过门（direct）；无任何过门时兴趣最高者兜底（interest_floor）；仲裁排序 `@ > 兴趣 > 冷板凳`；阈值用 v3 真实数据标定 0.600（0.7 丢 68% 真实接话）**；v7.1 增量：近期观察记录注入（方案 a）——未过门（passed=0）最近 N 条 detected_text 经 `db.read_recent_observations()` 注入过门 agent 上下文【近期观察记录】节，让"看过但没回应"想得起，零额外 LLM 调用**；**v7.2 增量：旁观者接话切入判定 + 滑动注意力窗口——`judge_sequence` 按 seq 从旧到新**逐条不去重**做过门（1 的第一条、2 的次早发言、1 的回复第三条独立判定），第一个过门的 = 接话切入点（target+target_speaker 落库）；过门 agent 决策上下文 = `(自己最近发言, 切入消息]` 接话窗口（不含自己、无截断），未发言 agent 下界=消息池起点；`batch_context`=窗口 + `batch_full`=完整批双口径；锚点随发言滑动** | 末位偏置根因是"回应对象由 LLM 自由推断"（用末位做捷径），冷板凳轮转只是转移偏置位置；且不感兴趣 agent 每批强制调 LLM（浪费调用）；整批判定取"兴趣最高"会稀释感兴趣消息，也无法表达"从谁说完话后开始接话" | 验收 158/158（U13 16 项）→ v7.1 U13.7 五项 → 163/163 → **v7.2 U13.8 六项 → 169/169**；5a20r_v2 实测：末位回应率 80.6%→58.8%、55 判定未过门 25 条省 25 次调用（总 33）、interest_judgment 55 条全量可查；5a20r_v3（门控+注入，新种子）：末位 66.7%、双向认知 **6 组**（v2 仅 3 组、无认知黑洞）、低 curiosity agent 未静音——印证黑洞是种子×话题组合效应；**v4 实测（20 轮哲思）：total=33 vs v3 41（-19.5%）、每决策输入 -22%（窗口收窄）、agent:1/3 判定 33/33 passed=0 实证不感兴趣；60 轮新话题（AI 自我意识）：60/60 跑满、total=102、per_agent 16-22 极均匀、每轮成本 1.70 持平——成本跟随参与度而非轮数；实验 B 联动：组 C 极值对照（warmth 0.1 vs 0.9）d=+0.962/p=0.0000 极显著，"状态→输出"环首次实证，真实漂移无显著差异属统计功效不足**；遗留：话题隧道效应、注入独立贡献需 40+ 轮量化、对比口径需同构批次复核 |

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

### 16 回应上下文标注：聊天记录与决策上下文可读"回答谁"

详见 [16_回应上下文标注回答对象.md](./16_回应上下文标注回答对象.md)。

### 17 实验数据质量与机制修复：失败/静默分离、user_id 归因、末位偏置、人格演化断链、引用链注入

详见 [17_实验数据质量与机制修复.md](./17_实验数据质量与机制修复.md)。

### 18 六项数据质量修复与末位偏置冷板凳轮转

详见 [18_六项数据质量修复与末位偏置冷板凳轮转.md](./18_六项数据质量修复与末位偏置冷板凳轮转.md)。

### 19 批次顺序事实源统一与七项数据采集实施

详见 [19_批次顺序事实源统一与七项数据采集实施.md](./19_批次顺序事实源统一与七项数据采集实施.md)。

### 20 兴趣门控回复机制

详见 [20_兴趣门控回复机制.md](./20_兴趣门控回复机制.md)。

---

## 修改文件清单

### 新增文件

| 文件 | 所属 |
|------|------|
| `tests/message_pool/__init__.py` | #01、#10（措辞） |
| `tests/message_pool/event_bus.py` | #01 |
| `tests/message_pool/message_pool.py` | #01、#09、#10（措辞）、#17（Message reply_to 字段） |
| `tests/message_pool/router.py` | #01 |
| `tests/message_pool/arbiter.py` | #01、#10（release 返回语义修复）、#17（request_speech/queue 透传 reply_to） |
| `tests/message_pool/collector.py` | #01、#02、#10（措辞）、#17（error_count 独立计数） |
| `tests/message_pool/agent_bridge.py` | #01、#10（措辞）、#13（subprocess 桥接）、#15（llm_stats + inline 计数）、#16（batch_context）、#17（失败→error + reply_to 透传） |
| `tests/message_pool/platform_runner.py` | #01、#02、#08、#09、#10（避让机制）、#13（并行决策 + 优先级仲裁）、#17（_batch_for @ 移末位 + error 分支 + 回投 reply_to） |
| `tests/message_pool/data_export.py` | #02、#08、#09、#10（措辞）、#16（回应对象标注 + 旧数据重建） |
| `tests/message_pool/run_pool_experiment.py` | #02、#08、#09、#10（措辞）、#13（--inline + aaa_env + 回收）、#15（直连计数 + llm_stats.json） |
| `tests/message_pool/topic.txt` | #08 |
| `tests/message_pool/infra_acceptance_test.py` | #01、#02、#08、#09、#10（42 项）、#11（U6 9 项）、#13（U7 7 项）、#14（fake_llm 独立确定性 + ping 阈值）、#15（llm_stats 2 项 + 报告统计 2 项）、#16（U8 10 项）、#17（U9 12 项 + U10 6 项） |
| `tests/message_pool/topic_report.py` | #11、#15（API 调用量统计节）、#17（error 统计，静默口径排除失败） |
| `tests/message_pool/aaa_serve.py` | #13、#15（计数包装 + llm_stats 协议）、#17（兜底 user_id 不归因末位） |
| `tests/message_pool/README.md` | #01、#02、#08、#09、#10、#11 |
| `docs/cogevo/[PLAN] 消息池与弹幕式消息处理方案（多用户交互实验）.md` | #01、#10（措辞） |
| `gui/pages/location_page.py` | #04 |
| `docs/changelogs/cn/2026-08-08/18_六项数据质量修复与末位偏置冷板凳轮转.md` | #18 |
| `docs/changelogs/cn/2026-08-08/19_批次顺序事实源统一与七项数据采集实施.md` | #19 |
| `docs/changelogs/cn/2026-08-08/20_兴趣门控回复机制.md` | #20 |
| `tests/message_pool/interest_gate.py` | #20 |
| `tests/message_pool/calibrate_interest_threshold.py` | #20 |
| `docs/cogevo/[PLAN]-兴趣门控回复机制.md` | #20 |
| `tests/personality_output_probe.py` | #20 v7.2（实验 B：人格漂移输出影响验证） |

### 重大修改文件

| 文件 | 改动 | 所属 |
|------|------|------|
| `nodes/node_python_aaa_cognition/db.py` | v6.0 user_id 列迁移（user_messages / event_summary / other_cognition / user_facts）；`_dedup_and_merge` / `_write` / `_write_parsed` 增加 user_id 维度；新增 `g_where_identity_user` 检索（用户专属优先、全局兜底） | #01 |
| `nodes/node_python_aaa_cognition/main.py` | 新增 `_on_pool_batch` 批量入口（批量写库 + F5 合并上下文 + `_observe_counter` 静默观察计数）；`_on_parsed` 增加 `batch_mode` 显式决策返回；`_gather_context` 增加 `user_id` / `batch_items` / `pool_batch_section`；修复反思轮 pending 上下文丢失 | #01 |
| `nodes/node_python_aaa_cognition/prompt.py` | `_CONTEXT_HEADER` 他人认知标签与用户文本改为占位符，支持按 user_id 渲染与批量输入段 | #01 |
| `nodes/node_python_aaa_cognition/prompt.py` | #12 【他人认知】【用户信息】【用户记忆】注入 `current_user_label`（点名对象 + 要求详细） | #12 |
| `nodes/node_python_aaa_cognition/prompt.py` | 【想法】强制输出（静默也必须写意识流）+【自然回复】明确静默=留空 | #14 |
| `nodes/node_python_aaa_cognition/main.py` | `_on_parsed` batch_mode 兜底想法/心情默认值（静默决策也带状态） | #14 |
| `nodes/node_python_aaa_cognition/prompt.py` | 【回应对象】条件输出节（仅批量场景渲染）+ 引导从批次选择回应对象（非末位 + @ 优先） | #16、#17 |
| `nodes/node_python_aaa_cognition/main.py` | batch_mode 返回【回应对象】字段；批量 user_id 归因 = 回应对象；`_fmt_pool_msg` 批次消息标注"回应谁"引用链 | #16、#17 |
| `nodes/node_python_aaa_cognition/personality.py` | `_adjust_vector` 支持 neutral 反馈演化（人格零漂移根因修复） | #17 |
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
| `nodes/node_python_aaa_cognition/main.py` | #18 batch_mode 归因排除自认知（`回应对象==identity_key` → user_id 清空）；静默模板分 action（reply 无想法兜底空串、silent 才用"保持观察"） | #18 |
| `tests/message_pool/platform_runner.py` | #18 冷板凳轮转（`_responded` 计数 + 被回应最少者移批次末位，@ 优先豁免、platform/单条不参与）；`_end_topic` 置 `collector.topic_ended`；evolution 落 agent_speech_count/rounds_metric="processed_batches" 三口径 | #18 |
| `tests/message_pool/collector.py` | #18 `topic_ended` 字段（话题结束后残余批次 decisions 落 `topic_ended=True` 标记） | #18 |
| `tests/message_pool/aaa_serve.py` | #18 max_tokens 2048→4096（截断防御） | #18 |
| `tests/message_pool/run_pool_experiment.py` | #18 MAX_TOKENS 2048→4096（截断防御） | #18 |
| `nodes/node_python_aaa_cognition/parser.py` | #18 `_SECTION_FRAGMENT` 残缺节标记剥离（未闭合 `【情绪调整` 行不并入上一节） | #18 |
| `nodes/node_python_aaa_cognition/prompt.py` | #18 【情绪调整】节强化强制输出（reply/silent 都必须输出数字） | #18 |
| `tests/message_pool/infra_acceptance_test.py` | #18 U11 15 项（A1/A2 自认知、B1/B2 静默模板、C1-C3 幽灵口径、D1/D2 截断、E1-E5 冷板凳、F1 情绪标签） |
| `nodes/node_python_aaa_cognition/db.py` | #19 `_write_parsed` 增 `skip_empty_other`（批量模式过滤空归因）；新增 `_write_memory_usage`/`record_memory_usage`（memory_usage 表）、`_write_silent_cognition`/`record_silent_cognition`（silent_cognition 表） | #19 |
| `nodes/node_python_aaa_cognition/memos.py` | #19 `_retrieve_hits` thread-local + `get_last_hits()`（P0-1 记忆检索命中透传） | #19 |
| `nodes/node_python_aaa_cognition/main.py` | #19 `_on_parsed` 批量路径返回 `memory_hits`/`silent_cognition_written`/`cognition_sections`；`skip_empty_other=batch_mode`；截断重试（inline 路径） | #19 |
| `nodes/node_python_aaa_cognition/parser.py` | #19 `is_truncated` 双信号（未闭合节标记 / 有回复缺情绪调整）+ 重试 | #19 |
| `nodes/node_python_aaa_cognition/personality.py` | #19 `_FALLBACK_TRIGGER_COUNT` 30→10（演化兜底） | #19 |
| `tests/message_pool/message_pool.py` | #19 `Message.to_dict()` 带 `seq`（全局序号）、`enqueue_input` 自增 `_seq`（P0-1 事实源） | #19 |
| `tests/message_pool/platform_runner.py` | #19 `ordered = {a: _batch_for(a, batch)}` 单源；process_batch 传 `mention_targets`；`_trajectory()`（P0-3）；step/drain_queue `not topic_active` 熔断（P1-3） | #19 |
| `tests/message_pool/agent_bridge.py` | #19 batch_context 带 seq/pos；`reply_target_pos`/`batch_last_author`/`mention_targets`/`mention_responded`/`attribution_ok`（P1-5） | #19 |
| `tests/message_pool/aaa_serve.py` | #19 subprocess 路径 `is_truncated` 截断重试 | #19 |
| `tests/message_pool/topic_report.py` | #19 新增五~十一章：末位偏置量化 / @提及响应率+归因 / 情绪-行为 / memory_hits / silent_cognition / trajectory / 认知网络时序 | #19 |
| `tests/message_pool/infra_acceptance_test.py` | #19 U12 31 项（P0-1 seq 同源、P0-2 空归因过滤、P1-4 is_truncated 四态、P1-5 量化字段、P1-6 阈值 10 触发、采集落盘、报告节渲染） | #19 |
| `nodes/node_python_aaa_cognition/db.py` | #20 ensure() 增加 interest_judgment 表（检测文本/兴趣值/过门/原因） | #20 |
| `nodes/node_python_aaa_cognition/db.py` | #20 v7.1 新增 `read_recent_observations()`（passed=0 过滤 + id 倒序去重 + limit 容错） | #20 v7.1 |
| `nodes/node_python_aaa_cognition/main.py` | #20 v7.1 `_gather_context` 注入 recent_observations（cfg.recent_observations_limit 默认 5） | #20 v7.1 |
| `nodes/node_python_aaa_cognition/prompt.py` | #20 v7.1 `_CONTEXT_HEADER` 渲染【近期观察记录】节（空则不渲染，1对1 不受影响） | #20 v7.1 |
| `tests/message_pool/platform_runner.py` | #20 step() 门控预筛（未过门不调 LLM）+ 锚点更新（自我介绍/发言后）+ 仲裁排序键（@ > 兴趣 > 冷板凳） | #20 |
| `tests/message_pool/run_pool_experiment.py` | #20 `--gate-threshold`/`--gate-model`/`--no-gate` 参数 + interest_gate 配置落盘 _run_meta | #20 |
| `tests/message_pool/topic_report.py` | #20 新增十二章兴趣门控判定采集（判定数/过门率/兴趣值分布/reason 分布/per-agent 中位） | #20 |
| `tests/message_pool/infra_acceptance_test.py` | #20 U13 16 项（编码一次、门控判定、锚点更新、落库字段、平台集成、仲裁）+ v7.1 U13.7 五项（观察记录过滤/上限/容错/prompt 渲染） | #20 |
| `tests/message_pool/interest_gate.py` | #20 v7.2 新增 `judge_sequence`（seq 从旧到新逐条不去重判定 + target/target_speaker 落库，direct 优先） | #20 v7.2 |
| `tests/message_pool/platform_runner.py` | #20 v7.2 接话窗口：`_msg_history`/`_last_speech_seq`/`_window_for`（`(自己最近发言, 切入消息]` 不含自己）+ judge_sequence 集成 + gate_windows 落库 | #20 v7.2 |
| `tests/message_pool/agent_bridge.py` | #20 v7.2 process_batch 增加 window 参数 + `decision["window_size"]` + `batch_context`=窗口 / `batch_full`=完整批双口径 | #20 v7.2 |
| `tests/message_pool/infra_acceptance_test.py` | #20 v7.2 U13.8 六项（逐条判定、同发言者独立判定、direct 优先、窗口区间、未发言下界、batch_context/batch_full 集成）→ 169/169 | #20 v7.2 |

---

**最后更新**：2026-08-08
