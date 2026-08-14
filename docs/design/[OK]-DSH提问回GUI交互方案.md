# DSH 提问回 GUI 交互方案

> 日期：2026-08-14 | 版本：v1.0 | 状态：[OK]（已实施，无更新日志要求）

## 一、背景与现状

### 1.1 用户诉求

DSH agent 执行任务中途需要向用户确认/选择/补信息时（`ask_user_question` 工具），
目前**无法在 GUI 上看到问题、也无法回答**——headless 模式链路是断的。

### 1.2 现状（已查证）

- DSH 提问机制：`ask_user_question` 工具 → `ctx.userQuestions.ask(request)` →
  等待"UI provider"返回人工答案后喂回 agent loop（[tool-ask-user/src/index.ts](file:///e:/杂项/BNOS_AI_project/nodes/node_dsh/harness/packages/interaction/tool-ask-user/src/index.ts)）
- **没有注册 provider 时 `ask()` 直接抛 `NO_PROVIDER`**（[user-questions/src/index.ts](file:///e:/杂项/BNOS_AI_project/nodes/node_dsh/harness/packages/interaction/user-questions/src/index.ts#L136-L139)）
- node_dsh 用 `--profile headless` 跑（无 UI、无 provider）→ agent 提问即任务失败
- headless runner 是 node_dsh 已 fork 的源码（[headless/src/index.ts](file:///e:/杂项/BNOS_AI_project/nodes/node_dsh/harness/packages/bundle/headless/src/index.ts)，
  已定制会话续接/预设/温度/工作目录），**注入自定义 provider 有现成挂载点**
- GUI 侧已有文件通道轮询先例（chat_page 轮询 mode.json、message_manager 轮询 gui_reply.json）

### 1.3 目标

DSH 提问 → 问题经共享文件回 GUI → 聊天页渲染"DSH 提问"气泡（文字 + 选项按钮 + 自由输入）
→ 用户回答 → 答案回传 DSH 继续执行 → 最终结果照旧推送。

## 二、链路设计

```
┌─ node_dsh（headless fork runner）─────────────────────────┐
│ run(): ctx.userQuestions.registerProvider(bnosProvider)    │
│                                                             │
│ bnosProvider.ask(request):                                  │
│   1) qid = uuid4；写 nodes/shared/dsh_question_in.json     │
│      {qid, questions:[{id, question, header, options,      │
│                        multiSelect}]}                       │
│   2) 轮询 nodes/shared/dsh_answer_out.json（匹配 qid）     │
│   3) 拿到答案 resolve → agent loop 继续执行                 │
│   4) 超时（默认 600s 同 DSH_TIMEOUT）→ reject → agent 容错  │
└─────────────────────────────────────────────────────────────┘
                      ▲ 写问题            ▲ 读答案
                      │                   │
          nodes/shared/dsh_question_in.json / dsh_answer_out.json
                      │                   │
                      ▼ 读问题            ▼ 写答案
┌─ GUI（chat_page）─────────────────────────────────────────┐
│ QTimer 轮询 dsh_question_in.json（mtime+md5 判新，记 qid） │
│   新 qid → 渲染"DSH 提问"气泡（AI 侧白底）                 │
│   每个 question：文字 + 选项按钮（multiSelect 决定多选/单选）│
│                  + 自由输入框 + 提交                        │
│ 用户回答 → 写 dsh_answer_out.json（原子写）→ 回答入会话      │
└─────────────────────────────────────────────────────────────┘
```

要点：
- **GUI 直连文件通道**（同 mode.json 轮询模式），AAA 不参与本次交互；
  DSH 任务由 node_dsh 提交，问题也由 node_dsh 的 provider 发起，两侧都是节点侧文件
- 多轮提问自然支持：每次 `ask()` 生成新 qid，重复上述流程
- 任务超时语义保持：DSH 等待答案计入 `DSH_TIMEOUT`（默认 600s），与现有超时一致

## 三、文件协议

| 文件 | 方向 | 内容 |
|------|------|------|
| `nodes/shared/dsh_question_in.json` | node_dsh → GUI | `{"qid", "created_at", "questions": [{"id", "question", "header"?, "options"?: [{"label","description"}], "multiSelect"?}]}` |
| `nodes/shared/dsh_answer_out.json` | GUI → node_dsh | `{"qid", "created_at", "answers": [{"id", "selected": [label...], "custom"}]}` |

- 均**原子写**（tmp + replace）；判新用 qid（GUI 记已处理 qid 集；provider 精确匹配 qid）
- 不沿用旧文件的"最近一次"读取，qid 是交互批次唯一标识（与 request_id/task_id 同族）

## 四、实施计划

### Phase 1：provider 注入（node_dsh fork runner）

- 在 `headless/src/index.ts` 新增 `bnosQuestionsProvider`：
  - `ask(request)` 写问题文件 + 轮询答案（`setInterval` 或 while+sleep，超时 reject）
  - 答案文件读到 qid 匹配 → 组装 `{answers: [{id, selected, custom}]}` resolve
- `run()` 里 `ctx.get('userQuestions')?.registerProvider(provider)`（`userQuestions` 缺失则跳过，保持原行为）

### Phase 2：GUI 提问气泡（chat_page）

- 新增轮询 QTimer（与现有 mode 轮询并列）：`_poll_question()` 读
  `dsh_question_in.json`，mtime/内容判新 → 渲染
- 气泡渲染（chat_page 内复用聊天流）：
  - AI 侧气泡：标题「DSH 需要确认」+ 每个 question 的正文 + 选项按钮（QCheckBox 多选/
    QPushButton 单选，`multiSelect` 决定）+ 自由输入 QLineEdit + 提交按钮
  - 提交 → 组装 answers → 原子写 `dsh_answer_out.json` → 回答以用户气泡入会话 →
    问题气泡标记「已回答 ✓」并禁用交互
- 与既有聊天流一致：走 `_add_message`/气泡组件，遵守微信风规范

### Phase 3：验证与收尾

- 链路自动验证：脚本触发 headless 任务（提示词要求先 `ask_user_question`）→
  等 `dsh_question_in.json` 出现 → 写答案 → 等最终回答含用户选择
- `run.bat` 启动无报错
- GUI 规范 2.5 通信协议表登记两个新文件（规范同步）

## 五、风险评估

| 风险 | 缓解 |
|------|------|
| headless 默认 preset 不含 `ask_user_question` 工具（agent 永不提问） | provider 注册无副作用；需要时经 DSH 管理页 extra.patch.yml / 预设挂载该工具 |
| 用户长时间不回答 → DSH 阻塞 | 超时后 reject，agent 按工具错误容错（描述现有任务失败信息）；qid 孤儿气泡标「已超时」 |
| GUI 重启后 dsh_question_in.json 残留旧 qid | 判新用「已处理 qid 集合 + mtime」，重启后不处理历史 qid |
| 与 gui_reply 消息流混用 | 提问气泡独立标识（DSH 提问卡片），回答作为普通用户气泡，不污染对话语义 |

## 六、测试计划

- 单测：provider 写文件格式正确；GUI 轮询判新（重复轮询不重复渲染）；qid 匹配
- 链路：headless 任务含提问 → 问题文件出现 → 脚本写答案 → 最终回答含选择（端到端）
- 回归：`run.bat` 启动无报错；日常对话/工作模式不受影响（provider 无副作用）

## 七、影响范围

| 文件 | 改动 |
|------|------|
| `nodes/node_dsh/harness/packages/bundle/headless/src/index.ts` | 注册 bnosQuestionsProvider（写问题/轮询答案/超时） |
| `gui/pages/chat_page.py` | 轮询 dsh_question_in.json + 渲染提问气泡 + 回答写回 |
| `docs/design/[OK]-GUI开发规范.md` | 2.5 通信协议表登记 dsh_question_in/out 两文件 |
| （新增）`nodes/shared/dsh_question_in.json`、`dsh_answer_out.json` | 运行时协议文件（不入库，规范 4.3 类） |
