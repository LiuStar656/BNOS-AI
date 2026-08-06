# 节点仓库说明

`nodes/` 目录下的每个子目录都是**独立的 Git 仓库**，不由主仓库（BNOS_AI_project）直接管理。

## 仓库列表

| 节点 | 语言 | 说明 |
|------|------|------|
| `node_python_aaa_cognition` | Python | 中枢认知（记忆/提示词/对话管理） |
| `node_python_asr_input` | Python | 语音识别输入 |
| `node_python_env_input` | Python | 环境感知输入 |
| `node_python_llm_infer` | Python | LLM 推理（云端/本地） |
| `node_python_tts` | Python | 语音合成输出 |
| `node_rust_grok_hands` | Rust | Grok 手势识别 |
| `python_node_demo` | Python | 节点开发模板/Demo |
| `shared` | — | 共享资源（数据库、配置文件等，非仓库） |

## 管理命令

使用 `scripts/nodes_manage.py` 统一管理所有节点仓库：

```bash
# 查看所有节点状态
python scripts/nodes_manage.py status

# 查看所有节点最近提交
python scripts/nodes_manage.py log

# 列出所有节点仓库详情
python scripts/nodes_manage.py list

# 批量提交所有节点改动
python scripts/nodes_manage.py commit

# 批量推送/拉取
python scripts/nodes_manage.py push
python scripts/nodes_manage.py pull
```

## 如何为节点添加远程仓库

```bash
cd nodes/node_xxx
git remote add origin https://github.com/your-org/node_xxx.git
git push -u origin master
```

## 主仓库与子仓库的关系

- **主仓库** (`BNOS_AI_project`)：包含 GUI、引擎、文档等基础设施
- **节点仓库** (`nodes/node_xxx`)：每个节点独立版本管理，可独立开发、提交、发布
- 主仓库通过 `.gitignore` 排除 `nodes/` 目录，不跟踪节点文件
- 节点仓库之间通过文件协议（JSON）通信，不直接 import 彼此代码
