# 02 Git 仓库初始化与 .gitignore 配置

---

## 摘要

- **核心改动**：初始化主项目 Git 仓库，将 `nodes/` 下的 11 个节点目录分别初始化为独立 Git 仓库，配置 `.gitignore` 屏蔽 `referencees/` 和 `nodes/` 目录
- **根因**：每个节点是独立进程 + 独立 venv 的隔离实体，需要独立的版本控制；`referencees/` 为第三方参考项目合集，不应被主仓库跟踪
- **影响**：主仓库仅跟踪根目录下的框架代码（`gui/`、`bnos_runtime/`、`docs/` 等），节点各自管理自身的版本历史

---

## 详细说明

### 一、问题描述

项目此前未初始化任何 Git 仓库，无法进行版本控制和变更追踪。需要建立符合 BNOS 设计哲学的仓库结构——每个节点拥有独立版本控制，同时避免第三方参考项目混入主仓库。

### 二、实施步骤

#### 1. 检查初始状态

通过 `Get-ChildItem -Directory nodes | ForEach-Object { Test-Path (Join-Path $_.FullName ".git") }` 检查发现：

- **已有 .git**（5 个）：`node_python_aaa_cognition`、`node_python_gui_adapter`、`node_python_gui_bridge`、`node_python_llm_infer`、`node_python_user_input`
- **无 .git**（6 个）：`node_js_live2d_face`、`node_python_asr_input`、`node_python_env_input`、`node_python_logseq_writer`、`node_rust_grok_hands`、`shared`

主仓库根目录也未初始化。

#### 2. 主仓库初始化

```bash
git init
```

创建空的 Git 仓库于 `E:/杂项/BNOS_AI_project/.git/`，默认分支名为 `master`。

#### 3. 节点仓库初始化

对所有 6 个未初始化的节点执行 `git init <node_dir>`，已有 .git 的节点保持原样：

| 节点 | 初始化方式 | 状态 |
|------|-----------|------|
| `node_js_live2d_face` | 新增初始化 | 独立仓库 |
| `node_python_asr_input` | 新增初始化 | 独立仓库 |
| `node_python_env_input` | 新增初始化 | 独立仓库 |
| `node_python_logseq_writer` | 新增初始化 | 独立仓库 |
| `node_rust_grok_hands` | 新增初始化 | 独立仓库 |
| `shared` | 新增初始化 | 独立仓库 |
| `node_python_aaa_cognition` | 已有 | 保持原样 |
| `node_python_gui_adapter` | 已有 | 保持原样 |
| `node_python_gui_bridge` | 已有 | 保持原样 |
| `node_python_llm_infer` | 已有 | 保持原样 |
| `node_python_user_input` | 已有 | 保持原样 |

#### 4. .gitignore 配置

主仓库 `.gitignore` 内容：

```
# Python
__pycache__/
*.pyc
*.pyo
*.egg-info/
dist/
build/
*.egg
.venv/
venv/
env/

# IDE
.idea/
.vscode/
*.swp
*.swo

# Sub-repos — 每个节点独立仓库，不由主仓库跟踪
nodes/

# Reference projects
referencees/

# OS
Thumbs.db
.DS_Store

# Logs
*.log
logs/

# Environment
.env
.env.*
```

关键配置说明：

- **`nodes/`**：使主仓库完全忽略 `nodes/` 目录，避免将嵌套的独立仓库视为子模块或未跟踪文件
- **`referencees/`**：屏蔽第三方参考项目合集，它们仅用于开发时参考，不应进入主仓库版本历史

### 三、验证结果

初始化完成后，`git status` 输出确认 `nodes/` 和 `referencees/` 均不在未跟踪文件列表中：

```
Untracked files:
  .gitignore
  bnos_runtime/
  docs/
  gui/
  pipeline.json
  run.bat
  ...
```

每个节点目录内的 `.git` 彼此独立，互不干扰。

---

## 仓库结构示意

```
E:/杂项/BNOS_AI_project/
├── .git/                    ← 主仓库
├── .gitignore               ← 主仓库忽略规则
├── gui/
├── bnos_runtime/
├── docs/
├── nodes/
│   ├── node_python_aaa_cognition/
│   │   └── .git/           ← 独立仓库
│   ├── node_python_user_input/
│   │   └── .git/           ← 独立仓库
│   ├── ...
│   └── shared/
│       └── .git/           ← 独立仓库
└── referencees/             ← 被主仓库忽略
```

---

## 验证方法

1. 主仓库状态：`git status` 不显示 `nodes/` 和 `referencees/` 相关内容
2. 节点仓库验证：逐个进入 `nodes/*` 目录执行 `git status`，确认各自正常工作
