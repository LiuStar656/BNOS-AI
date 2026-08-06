"""节点子仓库管理脚本 — 统一管理 nodes/ 下所有节点仓库。

用法:
    python scripts/nodes_manage.py status    # 查看所有节点仓库状态
    python scripts/nodes_manage.py commit    # 提交所有节点的改动
    python scripts/nodes_manage.py push      # 推送所有节点到远程
    python scripts/nodes_manage.py pull      # 从远程拉取所有节点
    python scripts/nodes_manage.py log       # 查看所有节点最近提交
    python scripts/nodes_manage.py list      # 列出所有节点及仓库信息
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_NODES_DIR = Path(__file__).resolve().parent.parent / "nodes"
_SHARED_DIR = _NODES_DIR / "shared"


def _run_git(repo_path: Path, *args: str) -> tuple[int, str, str]:
    """在指定仓库执行 git 命令，返回 (returncode, stdout, stderr)。"""
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _discover_node_repos() -> list[Path]:
    """发现 nodes/ 下所有包含 .git 的子目录（排除 shared）。"""
    repos = []
    if not _NODES_DIR.exists():
        return repos
    for d in sorted(_NODES_DIR.iterdir()):
        if not d.is_dir():
            continue
        if d.name == "shared":
            continue
        if (d / ".git").exists():
            repos.append(d)
    return repos


def cmd_status():
    """查看所有节点仓库的 git 状态。"""
    repos = _discover_node_repos()
    if not repos:
        print("未发现任何节点仓库。")
        return

    print(f"{'节点目录':<40} {'分支':<12} {'状态':<8} {'改动'}")
    print("-" * 80)

    for repo in repos:
        node_name = repo.name
        rc, branch, _ = _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        if rc != 0:
            branch = "?"

        rc, status_out, _ = _run_git(repo, "status", "--porcelain")
        changes = len(status_out.splitlines()) if status_out else 0

        rc, ahead_behind, _ = _run_git(repo, "rev-list", "--count", "--left-right", "@{upstream}...HEAD")
        ahead = behind = 0
        if rc == 0 and ahead_behind:
            parts = ahead_behind.split("\t")
            if len(parts) >= 1:
                ahead = int(parts[0]) if parts[0] else 0
            if len(parts) >= 2:
                behind = int(parts[1]) if parts[1] else 0

        state = "clean"
        if changes > 0:
            state = f"{changes} changed"
        if ahead or behind:
            state += f" [ahead {ahead}/behind {behind}]"

        print(f"  {node_name:<38} {branch:<12} {state:<8} {changes} file(s)")


def cmd_log():
    """查看所有节点仓库的最近提交。"""
    repos = _discover_node_repos()
    if not repos:
        print("未发现任何节点仓库。")
        return

    for repo in repos:
        node_name = repo.name
        rc, log_out, _ = _run_git(repo, "log", "--oneline", "-3")
        print(f"\n=== {node_name} ===")
        if log_out:
            for line in log_out.splitlines():
                print(f"  {line}")
        else:
            print("  (无提交记录)")


def cmd_commit():
    """提交所有节点的未暂存改动。"""
    repos = _discover_node_repos()
    if not repos:
        print("未发现任何节点仓库。")
        return

    msg = input("输入提交信息 (留空则跳过): ").strip()
    if not msg:
        print("已取消。")
        return

    for repo in repos:
        node_name = repo.name
        rc, status_out, _ = _run_git(repo, "status", "--porcelain")
        if not status_out:
            print(f"[跳过] {node_name}: 无改动")
            continue

        print(f"\n=== {node_name} ===")
        print(status_out)

        _run_git(repo, "add", "-A")
        rc, commit_out, err = _run_git(repo, "commit", "-m", msg)
        if rc == 0:
            print(f"  ✅ 已提交: {commit_out.splitlines()[0] if commit_out else msg}")
        else:
            print(f"  ❌ 提交失败: {err}")


def cmd_push():
    """推送所有节点到远程。"""
    repos = _discover_node_repos()
    if not repos:
        print("未发现任何节点仓库。")
        return

    for repo in repos:
        node_name = repo.name
        rc, remote, _ = _run_git(repo, "remote", "get-url", "origin")
        if rc != 0:
            print(f"[跳过] {node_name}: 未配置远程 origin")
            continue

        print(f"\n=== {node_name} → {remote} ===")
        rc, out, err = _run_git(repo, "push")
        if rc == 0:
            print(f"  ✅ 推送成功")
        else:
            print(f"  ❌ 推送失败: {err}")


def cmd_pull():
    """从远程拉取所有节点。"""
    repos = _discover_node_repos()
    if not repos:
        print("未发现任何节点仓库。")
        return

    for repo in repos:
        node_name = repo.name
        rc, remote, _ = _run_git(repo, "remote", "get-url", "origin")
        if rc != 0:
            print(f"[跳过] {node_name}: 未配置远程 origin")
            continue

        print(f"\n=== {node_name} ← {remote} ===")
        rc, out, err = _run_git(repo, "pull", "--rebase")
        if rc == 0:
            print(f"  ✅ 拉取成功")
        else:
            print(f"  ❌ 拉取失败: {err}")


def cmd_list():
    """列出所有节点仓库信息。"""
    repos = _discover_node_repos()
    if not repos:
        print("未发现任何节点仓库。")
        return

    print(f"共发现 {len(repos)} 个节点仓库:\n")
    for repo in repos:
        node_name = repo.name
        rc, branch, _ = _run_git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        rc, remote, _ = _run_git(repo, "remote", "get-url", "origin")
        rc, last_commit, _ = _run_git(repo, "log", "--oneline", "-1")
        rc, files, _ = _run_git(repo, "ls-files")

        print(f"  📁 {node_name}/")
        print(f"     分支: {branch if rc == 0 else '?'}")
        print(f"     远程: {remote if rc == 0 else '(无)'}")
        print(f"     文件: {len(files.splitlines())} 个已跟踪文件")
        print(f"     最新: {last_commit}")
        print()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1].lower()
    commands = {
        "status": cmd_status,
        "commit": cmd_commit,
        "push": cmd_push,
        "pull": cmd_pull,
        "log": cmd_log,
        "list": cmd_list,
    }

    if cmd not in commands:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)

    commands[cmd]()


if __name__ == "__main__":
    main()
