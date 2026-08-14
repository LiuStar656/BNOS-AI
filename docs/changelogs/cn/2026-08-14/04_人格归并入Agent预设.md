# 04 人格归并入 Agent 预设（目标/人格 Tab 删除）

## 问题描述

GUI 有独立「目标/人格」标签页，写入全局 `system-prompt.persona`。
用户质疑：人格不是 AAA 统一负责吗？创建 Agent 预设不是 DeepSeek Harness 负责吗？

## 根因分析

- **人格属于预设**是 DSH 官方语义：`dsh-persona`（`@deepseek-ai/dsh-persona`）是
  scope-only 插件行，只能挂进预设组合的 `agent.cordis.yml`，全局挂载会与部署人格冲突
- 原独立 Tab 写全局 `system-prompt.persona` 会静默覆盖所有任务的人格，
  与「人格属预设」语义及 AAA 负责人格都重叠 —— 设计错误

## 修改方案

- 删除 `PersonaTab` 类及「目标/人格」Tab（10 分区 → 9 分区）
- 人格编辑并入「Agent 预设」分区编辑对话框：`read_preset_persona` / `write_preset_persona`
  读写 agent.cordis.yml 的 `id: persona` 行；空文本 = 移除该行（该 Agent 继承部署默认人格）
- `_migrate_drop_global_persona()` 幂等清理 extra.patch.yml 残留的 `system-prompt` 行
  （首次打开本页时执行，避免静默覆盖）
- 预设卡片显示人格摘要（截断 80 字符）
- `!!js` 平台表达式经 `_JsExpr`/`_PresetLoader`/`_PresetDumper` roundtrip 原样保留

## 影响范围

- GUI 分区数 10 → 9；人格入口移至预设编辑对话框
- 无该行（清空）的 Agent 继承部署默认人格，行为与 DSH 官方一致

## 验证方法

- offscreen 实例化：9 Tab、无「目标/人格」、PresetsTab 含人格编辑区
- 人格 roundtrip：写中文人格 → 组合首行 `id: persona` → 清空移除 → 恢复
- `!!js` 表达式写入/读回原样保留；迁移函数幂等
