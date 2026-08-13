# AI 自动验收系统设计方案（AAV — AI Acceptance Verifier）

> 日期：2026-08-08 | 版本：v1.0 | 状态：[PLAN]

## 目录

1. [背景与现状评估](#一背景与现状评估)
2. [目标](#二目标)
3. [方案设计](#三方案设计)
4. [验收用例模型](#四验收用例模型)
5. [分阶段实施计划](#五分阶段实施计划)
6. [风险评估](#六风险评估)
7. [影响范围](#七影响范围)
8. [AAV 自身的验收方法](#八aav-自身的验收方法)

---

## 一、背景与现状评估

### 1.1 现状

`docs/design/` 下 12 份 PLAN（3D 角色、打断事件、功能优先级路线图、角色种子、声纹认证、事件驱动、长文本 RAG、AAA 记忆改造、AI 定位、AI 世界感知、CLI-TUI、GUI 改造、插件系统）的验收方法存在共同局限：

| 局限 | 具体表现 | 已引发的真实问题 |
|------|---------|----------------|
| **人为测试验收** | 验收记录模板要求人工填写（日期/人员/勾选 ☐ 用例），通过标准依赖人眼判断 | Qt 定位精度(204m)被 IP 定位(5000m)覆盖而验收未察觉 |
| **回归成本高** | 功能变更后须人重新跑全部用例 | 定位源跑偏到贵阳、`[日常，位置确认]` 垃圾数据复发 |
| **语义断言无法脚本化** | 通过标准多为语义描述（"Prompt 含 top-k 片段"、"角色可见且贴图正确"） | LLM 输出格式漂移难被硬编码断言捕获 |
| **无跨层链路检查** | 各用例只测单点，不验端到端 | 知识面板遍历 location_history 显示 ":" 空卡片 |
| **无版本依赖锁定** | 验收环境要求松散 | PySide6 6.11.1 API 变更导致 Qt 定位崩溃 |

### 1.2 现有可复用基础设施（已调研确认）

| 资产 | 路径 | 作用 |
|------|------|------|
| 子进程执行基座 | `tests/test_llm_aaa_pipeline.py` 的 `run_main(node_dir, input_data)` | 子进程跑节点 main.py → 返回 JSON 结果；失败回退直接 import |
| LLM 评审后端 | `nodes/node_python_llm_infer/backends.py` 的 `create_backend(model_type, params)` + `infer()` | DeepSeek(deepseek-v4-flash) / openai 兼容多供应商 |
| 节点 venv 探测 | `_py(node_dir)` 辅助函数 | 定位各节点独立 venv 的 python |
| 结构化用例源 | 12 份 PLAN 的验收表格（编号/操作步骤/预期结果/通过标准/类型） | 已是机器可解析的表格结构 |
| DB 检查 | `sqlite3` + `nodes/shared/chatbot.db` | 数据断言（表、记录数、内容） |

---

## 二、目标

用 **AI 自动验收（AAV）** 替代/补充人为测试验收：

1. **自动执行**：从 PLAN 验收表格解析用例 → 自动执行可自动化的部分（A/B 级），收集结构化证据。
2. **AI 语义评审**：用 LLM 读「执行证据 + 预期结果 + 通过标准」做语义判定 → 输出 `PASS / FAIL / REVIEW` 及理由。
3. **一键报告**：生成验收报告（沿用 PLAN 的验收记录模板：通过/附条件通过/不通过 + 问题清单），支持 `--plan <名字>` 单跑、`--all` 全量。
4. **零成本可回归**：默认 `--mock` 模式（本地规则 + 固定 mock LLM，离线免费）；`--real` 模式才调 DeepSeek 高精度语义判定。
5. **覆盖未实现功能**：对 `[PLAN]` 未实施的功能执行「代码就绪度审查」（检查方案要求的文件/类/接口/依赖是否就位），报告标注状态。

---

## 三、方案设计

### 3.1 总体架构

```
PLAN 验收表格（编号/操作步骤/预期结果/通过标准/类型）
        │  ① 解析
        ▼
┌─────────────────────────────────────────────┐
│        验收用例模型 Case（JSON）              │
│  {id, plan, title, step, expect, pass,      │
│   level: A|B|C, action: <Action>}           │
└─────────────────────────────────────────────┘
        │  ② 执行
        ▼
┌─────────────────────────────────────────────┐
│        执行器 runner.py                      │
│  A级: 脚本断言（DB/文件/依赖/字段）           │
│  B级: 子进程跑节点 run_main() → 证据集       │
│  C级: 代码就绪度扫描（AST/glob/grep）         │
│  产出: 证据包 evidence.json                  │
└─────────────────────────────────────────────┘
        │  ③ 评审
        ▼
┌─────────────────────────────────────────────┐
│        评审器 reviewer.py                    │
│  mock模式: 本地规则+固定LLM（离线零成本）      │
│  real模式: DeepSeek（backends.py create_backend）│
│  输入: 证据+预期+通过标准 → 输出结构化判定     │
└─────────────────────────────────────────────┘
        │  ④ 汇总
        ▼
┌─────────────────────────────────────────────┐
│        报告器 reporter.py                    │
│  汇总 verdict → 验收结论（通过/附条件/不通过） │
│  输出: acceptance_report.md + evidence/*.json│
└─────────────────────────────────────────────┘
```

### 3.2 目录结构（独立 CLI，不引入 pytest）

```
scripts/acceptance/
├── run_acceptance.py        # CLI 入口（--plan / --all / --mock / --real）
├── parser.py                # ① PLAN 表格 → Case JSON
├── runner.py                # ② 执行器（A/B/C 级动作分发）
├── reviewer.py              # ③ 评审器（mock/real 双模式）
├── reporter.py              # ④ 报告器（Markdown 报告生成）
├── cases/                   # 自动解析失败时的手动兜底用例（YAML/JSON）
│   └── *_cases.json
├── evidence/                # 证据包输出目录（运行时生成）
│   └── YYYYMMDD_HHMMSS/
└── requirements.txt         # 仅标准库（mock 模式）或加 requests（real 模式）
```

### 3.3 执行级别与动作类型

| 级别 | 判定方式 | 动作类型 | 示例用例 |
|:----:|---------|---------|---------|
| **A** | 脚本规则断言 | `db_query` / `file_check` / `dep_check` / `field_check` | 长文本 D1 不污染记忆（查库）、V1 依赖版本锁定 |
| **B** | 子进程执行 + LLM 语义断言 | `run_node` → 证据包 → reviewer | F3 相关检索（验证 Prompt 含片段）、S1-S5 状态机、定位链路端到端 |
| **C** | 代码就绪度审查 + 标注需人工复核 | `code_scan`（glob/grep/AST 查类、函数、接口） | 3D 渲染（需 GPU）、Qt 定位（需真实传感器）、声纹（需录音） |

**Action 数据结构**：

```json
{
  "action": "run_node",
  "node_dir": "nodes/node_python_aaa_cognition",
  "input": {"data_type": "text", "content": "你好", "source": "gui"},
  "expect_field": {"data_type": "prompt", "content_contains": ["记忆检索结果"]}
}
```

```json
{
  "action": "db_query",
  "db": "nodes/shared/chatbot.db",
  "sql": "SELECT COUNT(*) FROM long_term_memory WHERE content LIKE '%文档%'",
  "expect": {"eq": 0}
}
```

```json
{
  "action": "code_scan",
  "pattern": "class DocumentMemory",
  "path": "nodes/node_python_aaa_cognition",
  "expect": {"exists": true}
}
```

### 3.4 评审器（核心：AI 语义判定）

**输入**：`{case: {预期结果, 通过标准, 类型}, evidence: {...}, level: A|B|C}`

**prompt 模板（real 模式）**：

```
你是 BNOS 项目的验收评审专家。请根据以下验收用例和自动执行的证据，
判定该用例是否通过。

【验收项】{title}
【预期结果】{expect}
【通过标准】{pass_standard}
【执行级别】{level}（A=脚本断言 B=链路执行 C=代码就绪度）
【证据】{evidence_json}

请严格输出以下 JSON（不要输出其他内容）：
{"verdict": "PASS|FAIL|REVIEW", "confidence": 0-1, "reason": "一句话理由",
 "evidence_ref": "引用证据中关键字段"}
```

**mock 模式（零成本）**：
- A 级：直接按 `expect` 规则比较，不走 LLM。
- B/C 级：本地启发式（关键词包含 / 数值比较 / 存在性）→ 无法判定的输出 `REVIEW` 并提示 `--real` 精确判定。

### 3.5 报告器输出格式（沿用 PLAN 验收记录模板）

```markdown
================ <功能名> AI 自动验收报告 ================
功能名称：长文本分割向量化内存检索
验收日期：2026-08-08
验收模式：AI 自动（mock/real）
执行级别覆盖：A/B/C 各级用例数

功能验收：  ✅ F1  ✅ F2  ✅ F3  ...
状态机：    ✅ S1  ...
版本兼容：  ⚠️ V1（详见问题）
数据边界：  ✅ D1  ...

验收结论：☐ 通过  ☐ 附条件通过  ☐ 不通过
问题清单：
1. [V1] 原因... 证据: evidence/.../case_V1.json
```

---

## 四、验收用例模型

### 4.1 自动解析（parser.py）

12 份 PLAN 的验收表格格式统一为 `| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |`，因此：

1. 按标题定位「验收」章节（`^##+ .*验收`）。
2. 解析 Markdown 表格行 → 每个用例含 `id / title / step / expect / pass_standard / type`。
3. 需要人工补充的只有 `level`（A/B/C）和 `action`（映射到可执行动作）——在 `cases/*_cases.json` 中维护映射表（**自动解析得到用例骨架，人工补充动作映射一次**）。

### 4.2 动作映射示例（长文本 RAG 方案 §8）

| 用例 | step 摘要 | action | level |
|------|----------|--------|:----:|
| F1 | 三种格式各上传一份 | run_node（attachments=3 格式）→ 断言 fragments>0 | B |
| F2 | 上传 1000 token 文本 | run_node → 断言分 2 段且 ≤512 | A |
| F3 | 问"文档中关于 XX" | run_node → 断言 prompt 含 top-k 片段 | B |
| F4 | 无附件正常对话 | run_node → 断言 `{doc_context}` 为空串 | B |
| S2 | 连续 6 次 <0.4 | run_node×6 → 断言 active=False | B |
| D1 | 文档会话后查库 | db_query → 断言无新增记录 | A |
| D4 | 上传损坏 pdf | run_node → 断言 DocumentParseError 被捕获 | A |

### 4.3 代码就绪度审查（C 级，覆盖未实现功能）

对 `[PLAN]` 状态的功能，`code_scan` 检查方案中承诺的产物是否就位：

- 文件存在性：`glob` 目标模块/资源
- 类/函数存在性：`grep`/AST 扫描 `class DocumentMemory` 等
- 依赖锁定：读节点 `requirements.txt` 检查版本号
- 接口签名：`grep "def process"` 等

输出结论：`就绪 / 部分就绪（列出缺失项）/ 未就绪`，并标注「运行时验收需人工复核」。

---

## 五、分阶段实施计划

| Phase | 内容 | 产出 | 验收 |
|-------|------|------|------|
| **0** | parser.py：PLAN 表格 → 用例骨架 JSON | `cases/*_cases.json` 生成脚本 | 12 份 PLAN 骨架解析成功率 100% |
| **1** | runner.py：A/B/C 动作执行 + 证据包 | evidence 输出 | 3 份已实现 PLAN（长文本/定位/世界感知）A+B 级自动执行成功 |
| **2** | reviewer.py：mock 规则 + real DeepSeek 双模式 | 结构化 verdict | mock 判定与人工标注基准一致率 ≥80% |
| **3** | reporter.py + run_acceptance.py CLI | Markdown 报告 | `--all` 一键生成 12 份报告 |
| **4** | C 级代码就绪度覆盖未实现 PLAN + 基准对齐 | 全量报告 | 与人工验收对比，核心项符合率 ≥90% |

---

## 六、风险评估

| 风险 | 等级 | 缓解措施 |
|------|:----:|---------|
| PLAN 表格解析失败（格式漂移） | 中 | cases/*.json 手动兜底；解析器加格式容错 |
| LLM 语义判定不稳定 | 中 | 双模式：mock 做回归基线，real 做精确判定；verdict 强制 JSON schema |
| C 级（GUI/GPU/传感器）无法全自动 | 高 | 明确定位：C 级只做代码就绪度，运行时项标注"需人工复核"，不强行自动化 |
| API 成本 | 低 | 默认 mock 零成本；real 仅在有争议用例/发布前跑 |
| 跨节点约束 | 低 | 验收器是脚本层非节点，不违反节点隔离；评审 LLM 通过 backends 库复用，不注入业务节点 |

---

## 七、影响范围

- **新增**：`scripts/acceptance/` 目录（parser/runner/reviewer/reporter/run_acceptance.py）
- **只读依赖**：`tests/test_llm_aaa_pipeline.py`（复用 run_main 模式）、`backends.py`（评审后端）、12 份 PLAN 文档（用例源）
- **不修改**：任何业务节点代码、GUI、路由文件（验收器是纯外围工具）
- **文档**：12 份 PLAN 的验收方法章节补充「AI 自动验收对接」说明（可选，Phase 3 后）

---

## 八、AAV 自身的验收方法

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|--------|---------|---------|---------|:----:|
| A1 | PLAN 表格解析 | 对 12 份 PLAN 跑 parser | 每份成功提取 ≥1 个用例，无崩溃 | 解析成功率 100% | 核心 |
| A2 | A 级动作执行 | 跑长文本 RAG 的 D1（查库） | 返回真实行数，断言正确 | 与人工 sqlite 查询一致 | 核心 |
| A3 | B 级链路执行 | 跑定位链路端到端用例 | run_node 返回 JSON 证据 | 与 test_llm_aaa_pipeline 结果一致 | 核心 |
| A4 | mock 判定准确率 | 人工先标注 10 个用例答案 | mock 判定一致率 ≥80% | 一致率达标 | 核心 |
| A5 | real 判定有效性 | 对 3 个有争议用例跑 DeepSeek | 输出合法 JSON verdict 且理由合理 | schema 合法、reason 非空 | 非核心 |
| A6 | 报告格式 | 跑 --all | 生成 12 份 Markdown 报告，含结论与问题清单 | 模板字段完整 | 核心 |
| A7 | 零成本回归 | 无网络环境跑 --mock --all | 全程不调 API 完成 | 无网络请求 | 非核心 |
| A8 | 未实现覆盖 | 对 [PLAN] 3D 角色跑 C 级 | 输出代码就绪度 + 标注人工复核 | 不误报"通过" | 核心 |
| A9 | 核心项符合率 | 已实现 3 份 PLAN 与人工验收对比 | 核心项符合率 ≥90% | 达标 | 核心 |

**验收记录模板**：

```
功能名称：AI 自动验收系统（AAV）
验收日期：____-____-____
验收模式：☐ mock  ☐ real
解析：   ☐ A1   ☐ A2
执行：   ☐ A3   ☐ A5
判定：   ☐ A4   ☐ A6
覆盖：   ☐ A7   ☐ A8   ☐ A9
验收结论：☐ 通过  ☐ 附条件通过  ☐ 不通过
问题记录：_______________________________________________
```

---

**最后更新**：2026-08-08
