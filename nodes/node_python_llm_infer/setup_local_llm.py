#!/usr/bin/env python3
"""
setup_local_llm.py — 本地 LLM 环境搭建工具

功能：
  1. 自动检测平台、下载 llama.cpp 预编译二进制
  2. 解压至 llama_cpp_bin/ 目录
  3. 列出推荐的 GGUF 模型下载地址

用法：
  python setup_local_llm.py              # 下载最新版 llama.cpp 二进制
  python setup_local_llm.py --version bXXXX  # 下载指定版本（如 b4656）
  python setup_local_llm.py --list-releases  # 列出最近可用版本
  python setup_local_llm.py --help           # 帮助
"""
import sys
import os
import json
import urllib.request
import urllib.error
import zipfile
import tarfile
import io
import shutil
import re
import tempfile
from pathlib import Path


# ── 常量 ──────────────────────────────────────────────────────

CURRENT_DIR = Path(__file__).parent.resolve()
BIN_DIR = CURRENT_DIR / "llama_cpp_bin"
GH_API = "https://api.github.com/repos/ggml-org/llama.cpp"
GH_RELEASES = f"{GH_API}/releases"
USER_AGENT = "BNOS-node-setup/1.0"


# ── 平台检测 ──────────────────────────────────────────────────

def detect_platform() -> dict:
    """返回 {os, arch, ext, archive_fmt}"""
    system = sys.platform.lower()
    machine = os.uname().machine if hasattr(os, "uname") else (
        "AMD64" if sys.maxsize > 2**32 else "x86"
    )

    if system.startswith("win"):
        os_name = "windows"
        ext = ".exe"
        archive_fmt = "zip"
    elif system.startswith("linux"):
        os_name = "linux"
        ext = ""
        archive_fmt = "tar"
    elif system.startswith("darwin"):
        os_name = "macos"
        ext = ""
        archive_fmt = "tar"
    else:
        os_name = system
        ext = ""
        archive_fmt = "tar"

    # 架构归一化
    arch_map = {
        "amd64": "x86_64", "x86_64": "x86_64", "x64": "x86_64",
        "aarch64": "aarch64", "arm64": "aarch64",
        "armv7l": "armv7", "armv8l": "aarch64",
    }
    arch = arch_map.get(machine.lower(), machine.lower())

    return {"os": os_name, "arch": arch, "ext": ext, "archive_fmt": archive_fmt}


# ── GitHub API ────────────────────────────────────────────────

def _gh_request(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def list_releases(limit: int = 10) -> list:
    """列出最近 limit 个 release"""
    data = _gh_request(f"{GH_RELEASES}?per_page={limit}")
    releases = []
    for r in data:
        tag = r.get("tag_name", "")
        name = r.get("name", "")
        published = r.get("published_at", "")[:10]
        releases.append({"tag": tag, "name": name, "date": published})
    return releases


def find_asset(tag: str, platform: dict) -> dict | None:
    """查找匹配当前平台的 asset"""
    data = _gh_request(f"{GH_RELEASES}/tags/{tag}")
    assets = data.get("assets", [])
    os_name = platform["os"]
    arch = platform["arch"]
    fmt = platform["archive_fmt"]

    # 匹配模式示例:
    #   llama-b4656-bin-win-avx2-x64.zip
    #   llama-b4656-bin-ubuntu-x86_64.tar.gz
    #   llama-b4656-bin-macos-arm64.tar.gz
    keywords = [os_name, arch]
    if os_name == "windows":
        keywords.append("avx2")  # Windows 通用 AVX2
    elif os_name == "macos":
        keywords.append("arm64" if arch == "aarch64" else "x86_64")

    for asset in assets:
        name = asset["name"].lower()
        if not name.endswith(fmt):
            continue
        if all(kw in name for kw in keywords):
            return {
                "name": asset["name"],
                "url": asset["browser_download_url"],
                "size_mb": round(asset["size"] / 1024 / 1024, 1),
            }
    return None


# ── 下载与解压 ────────────────────────────────────────────────

def download_file(url: str, dest: Path, desc: str = ""):
    """下载文件并显示进度"""
    print(f"  ↓ {desc or url.split('/')[-1]}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        chunk_size = 8192
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = int(downloaded * 100 / total)
                    bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                    print(f"\r    [{bar}] {pct}%", end="", flush=True)
    print()


def extract_archive(archive: Path, dest: Path, fmt: str):
    """解压归档到目标目录"""
    print(f"  解压到 {dest}")
    dest.mkdir(parents=True, exist_ok=True)

    if fmt == "zip":
        with zipfile.ZipFile(archive, "r") as zf:
            # 只提取可执行文件和动态库
            exts = {".exe", ".dll", ".so", ".dylib", ""}
            for info in zf.infolist():
                name = Path(info.filename).name
                if not name:  # 目录
                    continue
                ext = Path(name).suffix.lower()
                is_exe = ext in exts or ".exe" in name.lower()
                is_lib = ext in {".dll", ".so", ".dylib"}
                is_main = name.startswith("llama-") and (is_exe or is_lib)
                if is_main or is_exe or is_lib:
                    target = dest / name
                    if not target.exists():
                        with zf.open(info) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        # 保持可执行权限
                        if os.name != "nt":
                            os.chmod(target, 0o755)
                        print(f"    ✓ {name}")

    elif fmt == "tar":
        import tarfile
        with tarfile.open(archive, "r:gz") as tf:
            for member in tf.getmembers():
                name = Path(member.name).name
                if not name:
                    continue
                ext = Path(name).suffix.lower()
                is_exe = ext in {".exe", ""} and name.startswith("llama-")
                is_lib = ext in {".so", ".dylib", ".dll"}
                if is_exe or is_lib:
                    target = dest / name
                    if not target.exists() and member.isfile():
                        with tf.extractfile(member) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        os.chmod(target, 0o755)
                        print(f"    ✓ {name}")


# ── 模型推荐 ──────────────────────────────────────────────────

MODEL_RECOMMENDATIONS = [
    {
        "name": "Qwen3-1.7B-Q4_K_M",
        "url": "https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/main/qwen3-1.7b-q4_k_m.gguf",
        "size": "~1.1 GB",
        "note": "入门推荐，1.7B 参数，Q4_K_M 量化",
    },
    {
        "name": "Qwen3-4B-Q4_K_M",
        "url": "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/qwen3-4b-q4_k_m.gguf",
        "size": "~2.5 GB",
        "note": "均衡选择，4B 参数，Q4_K_M 量化",
    },
    {
        "name": "Qwen3-8B-Q4_K_M",
        "url": "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/qwen3-8b-q4_k_m.gguf",
        "size": "~5.0 GB",
        "note": "高质量，8B 参数，建议 16GB+ 内存",
    },
    {
        "name": "Llama-3.2-3B-Instruct-Q4_K_M",
        "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "size": "~2.0 GB",
        "note": "Meta Llama 3.2 指令优化版",
    },
    {
        "name": "gemma-2-2b-it-Q4_K_M",
        "url": "https://huggingface.co/bartowski/gemma-2-2b-it-GGUF/resolve/main/gemma-2-2b-it-Q4_K_M.gguf",
        "size": "~1.5 GB",
        "note": "Google Gemma 2 指令优化版",
    },
]


def print_model_recommendations(target_dir: Path):
    """打印推荐模型列表"""
    print(f"""
╔══════════════════════════════════════════════════╗
║         推荐 GGUF 模型（下载到 models/）          ║
╚══════════════════════════════════════════════════╝

将 .gguf 文件放入: {target_dir}

推荐列表（从轻到重）:
""")
    for i, m in enumerate(MODEL_RECOMMENDATIONS, 1):
        print(f"  [{i}] {m['name']}")
        print(f"      大小: {m['size']}")
        print(f"      说明: {m['note']}")
        print(f"      下载: {m['url']}")
        print()

    print("""💡 下载方式示例（在 models/ 目录下）:
    # 用 axel 多线程下载（推荐）
    axel -n 4 <url>

    # 用 curl
    curl -L -O <url>

    # 用 aria2c
    aria2c -x 4 -s 4 <url>
""")


# ── 主流程 ────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="BNOS 本地 LLM 环境搭建工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python setup_local_llm.py                    # 下载最新 llama.cpp 二进制
  python setup_local_llm.py --version b4656    # 指定版本
  python setup_local_llm.py --list-releases    # 列出可用版本
        """,
    )
    parser.add_argument(
        "--version", type=str, default=None,
        help="llama.cpp 版本标签（如 b4656），不指定则使用最新版",
    )
    parser.add_argument(
        "--list-releases", action="store_true",
        help="列出最近可用版本",
    )
    args = parser.parse_args()

    # 仅列出版本
    if args.list_releases:
        print("正在查询 GitHub 版本列表...")
        try:
            releases = list_releases(15)
            print(f"\n最近 {len(releases)} 个版本:\n")
            for r in releases:
                print(f"  {r['tag']:12s}  {r['date']}  {r['name']}")
            print(f"\n指定版本下载: python setup_local_llm.py --version <tag>")
        except Exception as e:
            print(f"❌ 查询失败: {e}", file=sys.stderr)
            sys.exit(1)
        return

    # ── 下载流程 ──
    platform = detect_platform()
    print(f"""
╔══════════════════════════════════════════════════╗
║        BNOS 本地 LLM 环境搭建                    ║
╚══════════════════════════════════════════════════╝

  平台: {platform['os']} / {platform['arch']}
  目标: {BIN_DIR}
""")

    tag = args.version
    if tag:
        print(f"  指定版本: {tag}")
    else:
        print("  版本: 最新 (latest)")

    # 查询 GitHub release
    print("\n⏳ 查询 GitHub Release...")
    try:
        if tag:
            release_data = _gh_request(f"{GH_RELEASES}/tags/{tag}")
        else:
            release_data = _gh_request(f"{GH_RELEASES}/latest")
    except urllib.error.HTTPError as e:
        print(f"❌ 查询失败 (HTTP {e.code}): 版本 {tag or 'latest'} 不存在", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"❌ 网络错误: {e}", file=sys.stderr)
        # 降级：跳过二进制下载，只打印模型推荐
        print("\n⚠️  无法连接 GitHub，跳过二进制下载")
        print_model_recommendations(CURRENT_DIR / "models")
        sys.exit(1)

    actual_tag = release_data.get("tag_name", tag or "latest")
    print(f"  找到版本: {actual_tag}")

    # 查找匹配平台的 asset
    asset = find_asset(actual_tag, platform)
    if not asset:
        print(f"❌ 未找到匹配 {platform['os']}-{platform['arch']} 的 asset", file=sys.stderr)
        print("   可尝试 --list-releases 查看其他版本")
        sys.exit(1)

    print(f"  匹配文件: {asset['name']} ({asset['size_mb']} MB)")

    # 下载
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    fmt = platform["archive_fmt"]
    suffix = ".zip" if fmt == "zip" else ".tar.gz"
    archive_path = BIN_DIR / f"llama{actual_tag}{suffix}"

    try:
        download_file(asset["url"], archive_path, asset["name"])
    except Exception as e:
        print(f"❌ 下载失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 解压
    try:
        extract_archive(archive_path, BIN_DIR, fmt)
    except Exception as e:
        print(f"❌ 解压失败: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        # 清理归档文件
        if archive_path.exists():
            os.remove(archive_path)
            print(f"  🗑  清理临时文件: {archive_path.name}")

    # 列出已下载文件
    files = sorted(BIN_DIR.iterdir())
    exe_files = [f for f in files if f.is_file() and f.name != ".gitkeep"]
    print(f"\n✅ 已下载 {len(exe_files)} 个文件到 {BIN_DIR}:")
    for f in exe_files:
        size_kb = f.stat().st_size / 1024
        print(f"    {f.name:30s}  {size_kb:>8.1f} KB")

    # 打印模型推荐
    print_model_recommendations(CURRENT_DIR / "models")

    print("""
✅ 本地 LLM 环境就绪！接下来:
  1. 下载 GGUF 模型放入 models/
  2. 启动节点（start.bat / start.sh）
  3. 在 node_config.json 中设置 model_path
""")

    # 验证
    has_server = any("llama-server" in f.name for f in exe_files)
    has_cli = any("llama-cli" in f.name for f in exe_files)
    if has_server and has_cli:
        print("   ✓ llama-server + llama-cli 已就绪，可以开始推理！")
    elif has_server:
        print("   ✓ llama-server 已就绪（CLI 模式暂不可用）")
    elif has_cli:
        print("   ✓ llama-cli 已就绪（HTTP 服务模式暂不可用）")
    else:
        print("   ⚠️  未检测到 llama 可执行文件，请检查下载内容")


if __name__ == "__main__":
    main()
