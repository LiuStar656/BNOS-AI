# stage — 阶段性脚本（85 个）

> 整理日期：2026-08-11 | 定义：各开发阶段**独立运行**的实验/教学/评估/数据脚本——结论已沉淀到 docs/reports/，脚本保留用于复跑溯源。
> 运行：`cd schemanet && python stage/_xxx.py`（头部 bootstrap 已自动处理 import 路径；数据/输出仍在根 `data/`、`runs/`）。

## 分类索引

### 教学课程（27）
| 文件 | 阶段 |
|---|---|
| `_grow_zh.py` 系已入根（数据层）；以下为课程脚本 | |
| `_grow_stage2.py` | Stage 2 短句级增量成长（句内结构） |
| `_grow_svo.py` | Stage 2.6 主谓宾句式（S/V/O 槽位造句） |
| `_grow_v13.py` | 复杂句式练习题（想要/在看 判断题） |
| `_grow_s3_v19.py` | s3 正式课程 v19 整合（对话→表达→问答） |
| `_grow_s23_v2.py` | s2+s3 组合泛化教学（词对级） |
| `_grow_oov.py` | 字级 OOV 落地（词表外词→字模式并集） |
| `_grow_continue.py` | 续训闭环实验（扩容不丢记忆） |
| `_grow_fix23/24/25.py` | 考试修复三部曲（造词/OOV 固化/E 问答补教） |
| `_grow_free/free2/free3.py` | 自发表达教学 v1-v3（提示依赖修复） |
| `_grow_dialog2.py` | 真实多轮对话 v2（回应受问题语义约束） |
| `_grow_chain.py` 系已入根（数据层） | |
| `_grow_live*.py`（13 个） | 自由运行/活着模式 系列（v1-v12：心理透明化→质量引导→表达阶梯→条件化验证门） |
| `_grow_time.py` | 时序感知（内在时钟落地） |
| `_grow_s3_v19` 见上 | |

### 实验（22）
`_exp_ask` `_exp_ask2`（求证循环）· `_exp_attn`（多信号处理模式）· `_exp_compress` `_exp_compress2` `_exp_compress3`（压缩沉淀/sleep 压缩/受控压缩）· `_exp_flood`（灌注饱和归因）· `_exp_forget`（遗忘曲线）· `_exp_generalize`（自主举一反三量化）· `_exp_kvcache`（外挂 KV 上下文）· `_exp_listen`（逐字听）· `_exp_modal`（模态内化）· `_exp_mode` `_exp_mode2`（模式选择/多维反应）· `_exp_read`（正确读文章）· `_exp_recall_limit`（回忆极限与颗粒度）· `_exp_sleep_self`（自发 sleep）· `_exp_stream`（流式交互）· `_exp_time`（时间定位）· `_exp_wm` `_exp_wm2`（工作记忆回路）· `_exp_wm_limit`（多条目 WM）

### 场景演示（2）
`_scene_dialog`（完整对话演示）· `_scene_recall`（自发回忆演示）

### 压力/基准（3）
`_stress_all`（全功能压力测试 10/10）· `_bench_prune`（剪枝前后性能基准）· `_eq_check_prune`（v34↔v35 剪枝等价对拍）

### 评估/考试（5）
`_eval_mind`（自我表达与思考评估）· `_eval_quality`（自然语言质量评估）· `_exam_paper`（卷面生成）· `_exam_review`（答案审查）· `_exam_s23`（s2+s3 最终压力考试）

### 数据管线（5）
`_data_curriculum`（分级纯净数据抽取）· `_data_hanzi`（常用字/词表）· `_data_sememes`（OpenHowNet 义原）· `_gen_rel_v2` `_gen_rel_v3`（Stage 3 关系句数据生成）

### 探测（25）
`_probe_boundary` `_probe_concurrent`（并发训练边界）· `_probe_concurrent_v35`（v35 单快照并发激活 + 记忆合并写入，2026-08-11）· `_probe_mem_share`（多实例不重启记忆互通：经历日志+rng 重放+就地应用，2026-08-11）· `_probe_shared_write`（共同上下文直写方案评估：tick 错开直写 vs 写前拉取合并，2026-08-11）· `_probe_sound_modal`（无转译器声音模态最小闭环：合成音→帧词编码→听声唤起词，2026-08-11）· `_probe_sound_robust`（声音概念鲁棒性：类内 8 变体汇聚 + 噪声 SNR 扫描 + 掩蔽混叠，2026-08-11）· `_probe_sound_tts`（生成侧最小闭环：双向桥 + 声带合成器 + 可逆/闭环验证，2026-08-11）· `_probe_sound_real`（真实音效逆向解析：过零率 vs mel 编码，ESC-50，2026-08-11）· `_probe_sound_mel`（mel 频谱物理层：真实音效感知/生成/闭环，2026-08-11）· `_probe_vq_mel`（VQ 原型量化：mel k-means 64 原型，2026-08-11）· `_probe_vq_mel_longframe`（VQ+200ms 长帧：轨迹压缩，2026-08-11）· `_probe_pop_coding`（群编码连续注入：mel→神经元群，2026-08-11）· `_probe_cats` `_probe_hownet` `_probe_sememes` `_probe_svo`（数据可行性）· `_probe_dialog_v17`（v17 对话训练实验）· `_probe_expose_prose`（v17 先见后教管线）· `_probe_infer`（推理性能）· `_probe_order_entropy`（有向脉冲熵减诊断）· `_probe_prose`（散文语料探测）· `_probe_s3` `_probe_s3adv`（s3 现状探测）· `_probe_speed`（速度基准）· `_probe_v16_scale`（训练量缩放）

### RL 验证门（3）
`_rl_gate_big`（大网络机制验证）· `_rl_gate_scale`（规模扩大压力测试）· `_rl_gate_stress`（五级彻底泛化验证）

### 画图（3）
`_plot_boundary`（并发边界图）· `_plot_infer`（推理优化曲线）· `_plot_speed`（速度对照图）

## 维护约定

- **移动脚本必须补 bootstrap**：头部加 `sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))`（引擎/共享模块在根目录）。
- **路径语义**：`Path(__file__).resolve().parent.parent` = 项目根（`data/`、`runs/` 都在根）。
- 被 3+ 脚本 import 的模块应**提升回根目录**（共享层）。
