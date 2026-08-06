"""节点管理脚本 — 统一管理主仓库中各节点的分支与代码。

架构说明:
    所有节点代码统一在主仓库 (BNOS-AI) 中管理。
    每个节点拥有独立的开发分支 (node/xxx)，主分支 main 汇总所有节点。

用法:
    python scripts/nodes_manage.py status              # 查看所有节点分支状态
    python scripts/nodes_manage.py log [node]           # 查看节点最近提交 (可指定节点)
    python scripts/nodes_manage.py list                 # 列出所有节点信息
    python scripts/nodes_manage.py switch <node>        # 切换到节点开发分支
    python scripts/nodes_manage.py commit [msg]         # 提交当前分支改动
    python scripts/nodes_manage.py push                 # 推送所有节点分支
    python scripts/nodes_manage.py pull                 # 拉取所有节点分支
    python scripts/nodes_manage.py merge <node>         # 将节点分支合并回 main
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_NODES_DIR = _REPO_ROOT / "nodes"

# 节点目录 → 分支名 映射
_NODE_MAP: dict[str, str] = {
    "node_python_aaa_cognition": "node/aaa",
    "node_python_asr_input": "node/asr",
    "node_python_env_input": "node/env",
    "node_python_llm_infer": "node/llm",
    "node_python_tts": "node/tts",
    "node_rust_grok_hands": "node/hands",
    "python_node_demo": "node/demo",
}

# 短名 → 分支名 映射 (方便用户输入)
_SHORT_MAP: dict[str, str] = {
    "aaa": "node/aaa",
    "asr": "node/asr",
    "env": "node/env",
    "llm": "node/llm",
    "tts": "node/tts",
    "hands": "node/hands",
    "demo": "node/demo",
}

_NODE_NAMES = list(_SHORT_MAP.keys())


def _resolve_node(name: str) -> str | None:
    """将节点名解析为分支名。支持短名、目录名或分支名。"""
    if name in _NODE_MAP:
        return _NODE_MAP[name]
    if name in _SHORT_MAP:
        return _SHORT_MAP[name]
    if name.startswith("node/"):
        return name
    return None


def _branch_to_dir(branch: str) -> str:
    for d, b in _NODE_MAP.items():
        if b == branch:
            return d
    return branch


def _run_git(*args: str) -> tuple[int, str, str]:
    """在主仓库根目录执行 git 命令。"""
    result = subprocess.run(
        ["git", *args],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _current_branch() -> str:
    _, out, _ = _run_git("rev-parse", "--abbrev-ref", "HEAD")
    return out


def _node_dirs() -> list[str]:
    """发现 nodes/ 下的所有节点目录（排除 shared）。"""
    dirs = []
    if not _NODES_DIR.exists():
        return dirs
    for d in sorted(_NODES_DIR.iterdir()):
        if not d.is_dir():
            continue
        if d.name == "shared":
            continue
        dirs.append(d.name)
    return dirs


def cmd_status():
    """查看所有节点分支状态。"""
    current = _current_branch()
    print(f"当前分支: {current}\n")

    dirs = _node_dirs()
    if not dirs:
        print("未发现任何节点。")
        return

    print(f"{'节点目录':<30} {'分支':<15} {'远程':<8} {'状态'}")
    print("-" * 80)

    for dname in dirs:
        branch = _NODE_MAP.get(dname, f"node/{dname}")
        is_current = (current == branch)

        # 检查远程是否存在
        rc, remote_check, _ = _run_git("ls-remote", "--heads", "origin", branch)
        has_remote = rc == 0 and bool(remote_check)

        # 分支状态
        rc, ahead_behind, _ = _run_git(
            "rev-list", "--count", "--left-right", f"origin/{branch}...{branch}"
        )
        ahead = behind = 0
        if rc == 0 and ahead_behind:
            parts = ahead_behind.split("\t")
            if len(parts) >= 1 and parts[0]:
                ahead = int(parts[0])
            if len(parts) >= 2 and parts[1]:
                behind = int(parts[1])

        # 工作区改动
        rc, status_out, _ = _run_git("diff", "--name-only")
        has_changes = bool(status_out) if is_current else False

        marker = "👉 " if is_current else "   "
        remote_str = "✅" if has_remote else "❌"
        if has_changes:
            state = f"⚠️ 有未提交改动"
        elif ahead or behind:
            state = f"[ahead {ahead}/behind {behind}]"
        else:
            state = "clean"

        print(f"{marker}{dname:<28} {branch:<15} {remote_str:<8} {state}")


def cmd_log(node_name: str | None = None):
    """查看节点分支最近提交。"""
    if node_name:
        branch = _resolve_node(node_name)
        if branch is None:
            print(f"未知节点: {node_name}")
            print(f"可用: {', '.join(_NODE_NAMES)}")
            return
        branches = [branch]
    else:
        branches = list(_SHORT_MAP.values())

    for branch in branches:
        dirname = _branch_to_dir(branch)
        rc, log_out, _ = _run_git("log", branch, "--oneline", "-3", "--", f"nodes/{dirname}")
        print(f"\n=== {dirname} ({branch}) ===")
        if log_out:
            for line in log_out.splitlines():
                print(f"  {line}")
        else:
            print("  (无提交记录)")


def cmd_list():
    """列出所有节点信息。"""
    dirs = _node_dirs()
    if not dirs:
        print("未发现任何节点。")
        return

    print(f"共发现 {len(dirs)} 个节点:\n")
    for dname in dirs:
        branch = _NODE_MAP.get(dname, f"node/{dname}")
        rc, last_commit, _ = _run_git("log", branch, "--oneline", "-1", "--", f"nodes/{dname}")
        rc, files, _ = _run_git("ls-tree", "-r", "--name-only", branch, f"nodes/{dname}")
        file_count = len([f for f in files.splitlines() if f.strip()])

        # 节点配置
        config_path = _NODES_DIR / dname / "node_config.json"
        node_type = "?"
        if config_path.exists():
            try:
                with open(config_path, encoding="utf-8") as f:
                    cfg = json.load(f)
                node_type = cfg.get("type", "?")
            except Exception:
                pass

        print(f"  📁 {dname}/")
        print(f"     分支: {branch}")
        print(f"     类型: {node_type}")
        print(f"     文件: {file_count} 个")
        print(f"     最新: {last_commit}")
        print()


def cmd_switch(node_name: str):
    """切换到节点开发分支。"""
    branch = _resolve_node(node_name)
    if branch is None:
        print(f"未知节点: {node_name}")
        print(f"可用: {', '.join(_NODE_NAMES)}")
        return

    current = _current_branch()
    if current == branch:
        print(f"已在 {branch} 分支。")
        return

    # 保存当前改动
    rc, status_out, _ = _run_git("status", "--porcelain")
    if status_out:
        print("检测到未提交改动，自动 stash...")
        _run_git("stash", "save", "auto-stash before branch switch")

    # 确保分支存在
    rc, out, _ = _run_git("branch", "--list", branch)
    if not out:
        print(f"分支 {branch} 不存在，基于 main 创建...")
        _run_git("branch", branch, "main")

    rc, out, err = _run_git("checkout", branch)
    if rc == 0:
        print(f"✅ 已切换到 {branch}")
    else:
        print(f"❌ 切换失败: {err}")


def cmd_commit(msg: str | None = None):
    """提交当前分支改动。"""
    current = _current_branch()
    if current == "main":
        print("⚠️  当前在 main 分支，建议在节点分支上提交。")
        print("   使用: python scripts/nodes_manage.py switch <node>")
        return

    if msg is None:
        msg = input("输入提交信息 (留空则跳过): ").strip()
    if not msg:
        print("已取消。")
        return

    rc, status_out, _ = _run_git("status", "--porcelain")
    if not status_out:
        print("无改动可提交。")
        return

    print(status_out)
    _run_git("add", "-A")
    rc, out, err = _run_git("commit", "-m", msg)
    if rc == 0:
        first_line = out.splitlines()[0] if out else msg
        print(f"✅ 已提交: {first_line}")
    else:
        print(f"❌ 提交失败: {err}")


def cmd_push():
    """推送所有节点分支到远程。"""
    dirs = _node_dirs()
    for dname in dirs:
        branch = _NODE_MAP.get(dname, f"node/{dname}")
        print(f"\n=== 推送 {branch} ===")
        rc, out, err = _run_git("push", "-u", "origin", branch)
        if rc == 0:
            print("✅ 推送成功")
        else:
            print(f"❌ 推送: {err}")


def cmd_pull():
    """从远程拉取所有节点分支。"""
    dirs = _node_dirs()
    current = _current_branch()

    for dname in dirs:
        branch = _NODE_MAP.get(dname, f"node/{dname}")
        print(f"\n=== 拉取 {branch} ===")
        _run_git("checkout", branch)
        rc, out, err = _run_git("pull", "--rebase")
        if rc == 0:
            print("✅ 拉取成功")
        else:
            print(f"❌ 拉取: {err}")

    # 切回原分支
    _run_git("checkout", current)


def cmd_merge(node_name: str):
    """将节点分支合并回 main。"""
    branch = _resolve_node(node_name)
    if branch is None:
        print(f"未知节点: {node_name}")
        print(f"可用: {', '.join(_NODE_NAMES)}")
        return

    current = _current_branch()

    # 切到 main
    _run_git("checkout", "main")

    # 拉取远程最新
    _run_git("pull", "origin", "main")

    # 合并
    print(f"合并 {branch} → main ...")
    rc, out, err = _run_git("merge", branch, "--no-edit")
    if rc == 0:
        print("✅ 合并成功")
        rc, push_out, _ = _run_git("push", "origin", "main")
        if rc == 0:
            print("✅ 已推送到远程")
    else:
        print(f"❌ 合并冲突: {err}")
        print("   请手动解决冲突后执行 git commit")
        # 切回原分支
        _run_git("checkout", current)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "status":
        cmd_status()
    elif cmd == "log":
        node = sys.argv[2] if len(sys.argv) > 2 else None
        cmd_log(node)
    elif cmd == "list":
        cmd_list()
    elif cmd == "switch":
        if len(sys.argv) < 3:
            print("用法: python scripts/nodes_manage.py switch <node>")
            print(f"节点: {', '.join(_NODE_NAMES)}")
            sys.exit(1)
        cmd_switch(sys.argv[2])
    elif cmd == "commit":
        msg = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else None
        cmd_commit(msg)
    elif cmd == "push":
        cmd_push()
    elif cmd == "pull":
        cmd_pull()
    elif cmd == "merge":
        if len(sys.argv) < 3:
            print("用法: python scripts/nodes_manage.py merge <node>")
            sys.exit(1)
        cmd_merge(sys.argv[2])
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
