# 节点管理说明

`nodes/` 目录下包含所有 BNOS AI 节点的源代码，统一由主仓库 (`BNOS-AI`) 管理。

## 架构

```
BNOS-AI 主仓库
├── main 分支          ← 汇总所有节点 + GUI/引擎
├── node/aaa           ← 中枢认知节点开发分支
├── node/asr           ← 语音识别节点开发分支
├── node/env           ← 环境感知节点开发分支
├── node/llm           ← LLM 推理节点开发分支
├── node/tts           ← 语音合成节点开发分支
├── node/hands         ← 手势识别节点开发分支
└── node/demo          ← 节点模板开发分支
```

## 节点列表

| 目录 | 分支 | 类型 | 说明 |
|------|------|------|------|
| `node_python_aaa_cognition` | `node/aaa` | Python | 中枢认知（记忆/提示词/对话管理） |
| `node_python_asr_input` | `node/asr` | Python | 语音识别输入 |
| `node_python_env_input` | `node/env` | Python | 环境感知输入 |
| `node_python_llm_infer` | `node/llm` | Python | LLM 推理（云端/本地） |
| `node_python_tts` | `node/tts` | Python | 语音合成输出 |
| `node_rust_grok_hands` | `node/hands` | Rust | Grok 手势识别 |
| `python_node_demo` | `node/demo` | Python | 节点开发模板/Demo |
| `shared` | — | — | 共享运行时数据（数据库、索引文件等） |

## 管理命令

使用 `scripts/nodes_manage.py` 统一管理节点：

```bash
# 查看所有节点分支状态
python scripts/nodes_manage.py status

# 查看所有节点最近提交
python scripts/nodes_manage.py log
python scripts/nodes_manage.py log tts           # 只看某个节点

# 列出所有节点信息
python scripts/nodes_manage.py list

# 切换到节点开发分支
python scripts/nodes_manage.py switch tts         # 短名即可

# 在节点分支上提交改动
python scripts/nodes_manage.py commit "feat: xxx"

# 推送所有节点分支到远程
python scripts/nodes_manage.py push

# 拉取所有节点分支
python scripts/nodes_manage.py pull

# 将节点分支合并回 main
python scripts/nodes_manage.py merge tts
```

## 开发工作流

1. **开发节点**：切换到对应节点分支 → 编码 → 提交
   ```bash
   python scripts/nodes_manage.py switch tts
   # 编辑代码...
   python scripts/nodes_manage.py commit "feat: 添加新的 TTS 引擎"
   ```

2. **完成后合并回主分支**
   ```bash
   python scripts/nodes_manage.py merge tts
   ```

3. **主分支始终可运行**，每个节点分支独立提交历史，互不干扰。

## 节点间通信

节点之间通过文件协议（JSON）通信，不直接 import 彼此代码。运行时数据存放在 `shared/` 目录。
