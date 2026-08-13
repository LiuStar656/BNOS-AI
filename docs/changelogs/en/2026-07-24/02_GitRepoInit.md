# 02 Git Repository Initialization and .gitignore Configuration

---

## Summary

- **Core Change**: Initialized the main project Git repository, initialized 11 node directories under `nodes/` as independent Git repos, configured `.gitignore` to exclude `referencees/` and `nodes/`
- **Root Cause**: Each node is an isolated entity (independent process + independent venv) requiring separate version control; `referencees/` is a collection of third-party reference projects that should not be tracked by the main repo
- **Impact**: The main repo only tracks framework code at the root level (`gui/`, `bnos_runtime/`, `docs/`, etc.), while nodes manage their own version histories independently

---

## Details

### 1. Initial State

- **With .git** (5): `node_python_aaa_cognition`, `node_python_gui_adapter`, `node_python_gui_bridge`, `node_python_llm_infer`, `node_python_user_input`
- **Without .git** (6): `node_js_live2d_face`, `node_python_asr_input`, `node_python_env_input`, `node_python_logseq_writer`, `node_rust_grok_hands`, `shared`

### 2. Repository Layout

```
E:/BNOS_AI_project/
├── .git/                    ← Main repo
├── .gitignore               ← Main repo ignore rules
├── gui/
├── bnos_runtime/
├── docs/
├── nodes/
│   ├── node_python_aaa_cognition/
│   │   └── .git/           ← Independent repo
│   ├── node_python_user_input/
│   │   └── .git/           ← Independent repo
│   ├── ...
│   └── shared/
│       └── .git/           ← Independent repo
└── referencees/             ← Ignored by main repo
```

### 3. Key .gitignore Entries

- **`nodes/`**: Prevents the main repo from treating nested independent repos as submodules or untracked files
- **`referencees/`**: Excludes third-party reference project collection from main repo version history

---

## Verification

1. `git status` — `nodes/` and `referencees/` do not appear in untracked files
2. `git -C nodes/<node_name> status` — each node repo works independently
