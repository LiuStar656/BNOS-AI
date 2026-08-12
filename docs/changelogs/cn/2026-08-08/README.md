# 2026-08-08 更新总览

[返回总索引](../README.md)

---

## 更新目录

- [01 消息池多用户交互实验基础设施](#01-消息池多用户交互实验基础设施)
- [02 消息池实验数据收集设施与多 Agent 启动脚本](#02-消息池实验数据收集设施与多-agent-启动脚本)
- [03 定位逆地理编码县级精度修复](#03-定位逆地理编码县级精度修复)
- [04 Qt 定位正常时抑制 IP 兜底](#04-qt-定位正常时抑制-ip-兜底)
- [05 定位历史同坐标去重](#05-定位历史同坐标去重)
- [06 数据浏览"仅冒号"占位修复](#06-数据浏览仅冒号占位修复)

---

## 摘要

| # | 核心改动 | 根因 | 影响 |
|---|---------|------|------|
| 01 | 按 `[PLAN] 消息池与弹幕式消息处理方案` 开发多用户交互实验基础设施（F1–F8，先不做实验）：AAA 侧新增 `_on_pool_batch` 批量入口与 `batch_mode` 显式 `{action: reply|silent}` 决策、v6.0 user_id 维度迁移与多用户认知检索隔离；平台侧新增 `tests/message_pool/` 包（事件总线 / 弹幕消息池 / @ 点名路由 / 发言仲裁器 / 数据采集器 / Agent 桥接 / 平台编排） | 多 Agent 弹幕场景需要批量消费、区分说话用户、认知隔离、静默处理、单一发言权与结构化数据采集，现有 `_on_text` 单条路径与无用户维度记忆无法支撑 | GUI 直连与既有测试不受影响（新参数带默认值）；消息池实验可复用平台包编排多 Agent 并采集 events/decisions/evolution 数据 |
| 02 | 补齐实验数据收集与启动：新增 `data_export.py`（每个 Agent 原始数据库按表分类导出 + 聊天历史 md 渲染）、`collector.py`/`platform_runner.py` 增加 `chat_history.jsonl`（用户弹幕 + Agent 广播）、新增 `run_pool_experiment.py` 启动脚本（`--agents` 默认 5，按需调整数量） | 实验需要"原始 DB 按表分类 + 消息池聊天历史 + 一键拉起多 Agent"，原平台仅有 events/decisions/evolution，DB 导出逻辑散落在旧验收脚本且未集成 | 每次运行独立时间戳留档（runs/ 目录），产物含 db/{agent}_final/ 各表 JSON + sqlite、chat_history、events/decisions/evolution、_run_meta |
| 03 | 定位逆地理编码由单源（Photon）改为双源合并：city 取 BigDataCloud 的县级 `locality`（习水县），street/district 取 Photon 的街道级（赤水西路/杉王街道） | Photon 的 `city` 是地级市（遵义市），县级名（习水县）仅在 Photon 失败时兜底，导致定位显示市级而非县级 | 定位历史与日志显示"习水县, 贵州省"（县级）+ 街道；location_history 中 qt_ 记录已清空行政信息，下次读取自动补全 |
| 04 | `get_location()` 决策重构：Qt 定位记录新鲜时，无论 `force_refresh` 与否都直接返回，不再触发 IP 兜底 | GUI 定位页手动刷新用 `force_refresh=True`，旧逻辑会跳过数据库新鲜 Qt 记录直接进入 IP 多源兜底 → Qt 正常时 ipapi.co 仍被请求（403） | 只要 Qt 定位在更新，日志不再出现 `ipapi.co 获取失败` WARNING；仅 Qt 记录缺失/过期时才走 IP |
| 05 | GUI `_write_to_db` 加同坐标去重：同坐标（约 330m 容差）+ 近 30 分钟有 active 记录 → 只更新时间戳/精度，不插入新记录 | Qt 每 5 分钟回调一次，人在原地时坐标基本不变，每次回调都 INSERT → 定位历史堆积同坐标重复记录（界面出现"一条坐标、一条城市名"） | 定位历史只保留"去过的位置"，原地停留不再堆积；位移超容差才插入新记录保留移动轨迹 |
| 06 | 数据浏览"仅冒号"占位修复：`db.py` 空 user 消息不入库（v5.5）+ `knowledge_panel.py` 显示层解析 JSON 包装消息、空内容整条跳过（v1.6） | `_write` 在 content 为空时把整个消息 dict JSON 序列化写入 user_messages，产生 `{"data_type":"text","content":"",...}` 垃圾记录，显示为 `"content": ""` | 8 条存量 JSON 垃圾记录不再显示；后续不再产生空消息 JSON 记录 |

---

### 01 消息池多用户交互实验基础设施

详见 [01_消息池多用户交互实验基础设施.md](./01_消息池多用户交互实验基础设施.md)。

### 02 消息池实验数据收集设施与多 Agent 启动脚本

详见 [02_消息池实验数据收集与多Agent启动脚本.md](./02_消息池实验数据收集与多Agent启动脚本.md)。

### 03 定位逆地理编码县级精度修复

详见 [03_定位逆地理编码县级精度修复.md](./03_定位逆地理编码县级精度修复.md)。

### 04 Qt 定位正常时抑制 IP 兜底

详见 [04_Qt定位正常时抑制IP兜底.md](./04_Qt定位正常时抑制IP兜底.md)。

### 05 定位历史同坐标去重

详见 [05_定位历史同坐标去重.md](./05_定位历史同坐标去重.md)。

### 06 数据浏览"仅冒号"占位修复

详见 [06_数据浏览冒号占位修复.md](./06_数据浏览冒号占位修复.md)。

---

## 修改文件清单

### 新增文件

| 文件 | 所属 |
|------|------|
| `tests/message_pool/__init__.py` | #01 |
| `tests/message_pool/event_bus.py` | #01 |
| `tests/message_pool/message_pool.py` | #01 |
| `tests/message_pool/router.py` | #01 |
| `tests/message_pool/arbiter.py` | #01 |
| `tests/message_pool/collector.py` | #01、#02 |
| `tests/message_pool/agent_bridge.py` | #01 |
| `tests/message_pool/platform_runner.py` | #01、#02 |
| `tests/message_pool/data_export.py` | #02 |
| `tests/message_pool/run_pool_experiment.py` | #02 |
| `tests/message_pool/infra_acceptance_test.py` | #01、#02 |
| `tests/message_pool/README.md` | #01、#02 |

### 重大修改文件

| 文件 | 改动 | 所属 |
|------|------|------|
| `nodes/node_python_aaa_cognition/db.py` | v6.0 user_id 列迁移（user_messages / event_summary / other_cognition / user_facts）；`_dedup_and_merge` / `_write` / `_write_parsed` 增加 user_id 维度；新增 `g_where_identity_user` 检索（用户专属优先、全局兜底） | #01 |
| `nodes/node_python_aaa_cognition/main.py` | 新增 `_on_pool_batch` 批量入口（批量写库 + F5 合并上下文 + `_observe_counter` 静默观察计数）；`_on_parsed` 增加 `batch_mode` 显式决策返回；`_gather_context` 增加 `user_id` / `batch_items` / `pool_batch_section`；修复反思轮 pending 上下文丢失 | #01 |
| `nodes/node_python_aaa_cognition/prompt.py` | `_CONTEXT_HEADER` 他人认知标签与用户文本改为占位符，支持按 user_id 渲染与批量输入段 | #01 |
| `tests/message_pool/collector.py` | 新增 chat_history.jsonl 输出与 `chat()` 方法 | #02 |
| `tests/message_pool/platform_runner.py` | inject/step/drain_queue 记录聊天历史（role=user / agent） | #02 |
| `nodes/node_python_aaa_cognition/location.py` | `_reverse_geocode` 双源合并：city 取 BigDataCloud 县级 locality，street/district 取 Photon 街道级（v1.5.1）；`get_location` Qt 新鲜优先、force_refresh 不再绕过 Qt 记录（v1.5.2） | #03、#04 |
| `gui/core/location_provider.py` | `_write_to_db` 同坐标 + 近 30 分钟去重：仅更新时间戳/精度，不插入（v1.5.3） | #05 |
| `nodes/node_python_aaa_cognition/db.py` | `_write` 空 user 消息直接返回不入库（v5.5） | #06 |
| `gui/widgets/knowledge_panel.py` | `_read_db` 解析 JSON 包装消息、空内容整条跳过（v1.6） | #06 |

---

**最后更新**：2026-08-08
