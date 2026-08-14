# 02 DSH 设置/控制组件接入 GUI（DSH 管理页）

## 问题描述

DSH（DeepSeek Harness）的模型配置/会话/任务/插件/工具/工作区/Agent 预设等
设置与操作只能进入 DSH（CLI/web）完成。用户要求：**不是内嵌 DSH web 面板**，
而是把需要设置、修改、控制的组件做成 BNOS GUI 原生表单，不进入 DSH 即可操作。

## 根因分析

- 原「DSH 配置」页仅覆盖模型配置，可控面过窄（用户反馈"DSH 可控没有涵盖所有功能控件，是空的"）
- 启动闪屏缺 node_dsh 节点显示（用户反馈"启动快闪里没有 dsh 节点的启动"）

## 修改方案

「DSH 管理」页（`gui/pages/dsh_manage_page.py`，`page.dsh_manage`）**9 个分区**：

| 分区 | 内容 |
|---|---|
| 模型配置 | provider baseURL / 默认模型 / 模型列表 / 最大 Token（headless+web 双 patch 同步写回） |
| 会话 | dsh_home/sessions 列表（继续/复制 id/导出 zip/删除/清理） |
| 任务 | 提交任务（同步等待）/取消任务/最近结果 |
| 工具开关 | base/headless bundle 合并 `tool-*` 清单（18 个），每行启用/禁用 |
| 插件 | `dsh plugin add/remove` 封装（子线程防冻结）+ 已装插件组合清单 |
| 工作区 | `nodes/shared/dsh_workspace` 文件浏览/新建/重命名/删除（路径安全校验） |
| 运行参数 | extra.patch.yml 编辑（YAML 校验 + 原子写回） |
| 通用/安全 | 沙箱权限模式 + 会话遥测 + 默认温度 |
| Agent 预设 | 默认预设 + 复制创建自定义 Agent + 人格 + agent.cordis.yml/preset.yml 编辑 + 删除 |

配套链路：runtime.json `preset`/`temperature` → node_dsh main.py 注入 `DSH_PRESET`/
`DSH_TEMPERATURE` → headless roster 挂载 + `agent/request` 合并；extra.patch.yml 经
`--patch` 加载（`_patch_has_entries()` 跳过空 patch）。

## 影响范围

- `pipeline.json` 引擎管线增加 `node_dsh` 节点；启动闪屏显示「DSH 执行」
- 会话管理「继续」自动填任务页 session_id；工作区文件可被任务引用

## 验证方法

- 9 分区 offscreen 实例化；`!!js` 平台表达式 roundtrip
- dump-config 合成验证 sandbox/telemetry/persona 被 extra.patch 覆盖
- 真实任务端到端：temperature 注入、persona 进 system、preset header 记录
