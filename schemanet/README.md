# schemanet 脚本三层组织

> 整理日期：2026-08-11 | 分类依据：import 依赖图（谁被 import = 基础设施）+ 用途（阶段产物 vs 一次性）

## 三层结构

| 层 | 位置 | 数量 | 内容 |
|---|---|---|---|
| 基础设施 | 根目录 | 27 | 引擎核心 + 共享教学数据/读取工具（**被 import，不可移动**） |
| 阶段性脚本 | `stage/` | 85 | 各阶段独立实验/教学/评估/数据脚本（可复跑，报告溯源） |
| 已无用 | `archive/` | 58 | 临时/一次性/被取代脚本与剖析数据（冻结） |

## 运行方式

```bash
cd schemanet
python stage/_grow_live12.py      # 阶段性脚本
python stage/_stress_all.py       # 压力测试
python archive/_version_demo.py   # 归档脚本（仅复现时）
```

- 所有 `stage/`、`archive/` 脚本头部已自动插入 bootstrap：把项目根目录加入 `sys.path`（引擎在根目录），任意 cwd 可运行。
- 数据读写仍指向项目根：`schemanet/data/`、`schemanet/runs/`（`Path(__file__).resolve().parent.parent` 语义 = 项目根）。

## 根目录保留清单（27，被 import 或运行时）

### 引擎核心（7）
| 文件 | 用途 |
|---|---|
| `schema_net.py` | 定式网络核心动力学引擎（积分-发放 + Hebbian/STDP） |
| `sparse_net.py` | 稀疏实现（规模扩展核心，含 numba 提速） |
| `snapshot.py` | 快照版本链（vX.Y + 父子追溯 + 回退训练）——102 处 import |
| `_speak.py` | 说话通道（网络自输出自然语句引擎） |
| `_net_log.py` | 经历日志（checkpoint + 增量事件日志） |
| `grad_readout.py` | 梯度读出层（Phase 4 可选项） |
| `generator.py` | 生成器（Phase 3） |

### 共享教学数据/读取工具（18，被当前脚本 import）
| 文件 | 提供 | 主要使用者 |
|---|---|---|
| `_exam_free.py` | free_read/build_domain/build_teach_out（自由读/考试引擎） | 20+ |
| `_exam_big.py` | 期末考试题库（A-PAIRS/B-SENTS…） | 4 |
| `_grow_cat.py` | build_cats/edge_sum（6 类词义类别） | 30+ |
| `_grow_chain.py` | CHAIN_SENTS（口语化扩链数据） | _exam_free 延迟导入 |
| `_grow_dialog3.py` | SCENES（对话场景数据） | _exam_free 延迟导入 |
| `_grow_knowledge.py` | LESSONS（基本常识课程数据） | _exam_free 延迟导入 |
| `_grow_qa_s3.py` | build_pool/qa_read（问答池） | 22+ |
| `_grow_s3.py` | relation_self_judge/ITEMS（关系句式数据） | _probe_s3 等 |
| `_grow_s3_ask.py` | NEW_ASKS/RHET_ITEMS/chain_read（提问数据） | 5 |
| `_grow_self_express.py` | STATES/express_read（自我表达数据/读取） | 8 |
| `_grow_teacher.py` | LLM 教师（penalize_drift 等） | _grow_live8-12 |
| `_grow_v11.py` | LLM 通道(_load_key/_llm_chat) + rule_verifier + VO 数据 | 31+ |
| `_grow_v12.py` | self_judge/inherit_acceptance（自判+继承验收） | 6 |
| `_grow_v15.py` | direct_next/DOMAIN_WORDS | 3+ |
| `_grow_v16.py` | edge_between/direct_next_multi/EVAL（s3 数据+读取） | 32+ |
| `_grow_zh.py` | 常用字/词数据 | 9 |
| `_rl_gate.py` | 验证门机制（RL 最小实验） | 7 |
| `_rl_gate_fix.py` | 验证门缺口修复（终止+上下文） | _rl_gate_big 等 |

### 运行时/场景基类（2）
| 文件 | 用途 |
|---|---|
| `_live_stream.py` | 流式主循环运行时（整合 4.4-4.13 全部机制） |
| `_scene_day.py` | 虚拟场景基类（DayNet——被 scene_dialog/recall 继承） |

## stage/、archive/ 明细

- 阶段性脚本分类索引：见 `stage/README.md`
- 已无用脚本归档清单：见 `archive/README.md`
