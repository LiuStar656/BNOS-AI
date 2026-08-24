"""
BNOS — DSH web 服务器启动器（桥接 UI 载体）

启动 `dsh --profile web`（本机浏览器访问的 DSH web UI），并注入桥接所需环境：
- DSH_HOME → 节点内 dsh_home/（web profile 隔离在节点内）
- DEEPSEEK_API_KEY → 从 llm_infer 节点配置复用（运行时注入，不落盘）
- BNOS_SHARED_DIR → nodes/shared/（桥接插件读写 gui_input/gui_reply.json 的目录）

用法：
    python web_server.py            # 随机空闲端口
    python web_server.py 8080       # 指定端口
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

NODE_DIR = Path(__file__).resolve().parent


def _read_llm_key() -> str:
    """复用 llm_infer 节点的 API Key（与 GUI 存储约定一致）。

    读取顺序：llm 节点 local_config.json（GUI 维护）→ node_config.json api_key
    参数 → 环境变量 DEEPSEEK_API_KEY。
    """
    local_cfg = NODE_DIR.parent / "node_python_llm_infer" / "local_config.json"
    try:
        if local_cfg.is_file():
            key = str(json.loads(local_cfg.read_text(encoding="utf-8")).get("api_key", "") or "").strip()
            if key:
                return key
    except (OSError, json.JSONDecodeError):
        pass
    cfg_path = NODE_DIR.parent / "node_python_llm_infer" / "node_config.json"
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        for p in cfg.get("parameters", []):
            if p.get("name") == "api_key":
                return str(p.get("default", "")).strip()
    except (OSError, json.JSONDecodeError):
        pass
    return os.environ.get("DEEPSEEK_API_KEY", "")


def main() -> int:
    key = _read_llm_key()
    if not key:
        print("[web_server] 警告：未找到 DeepSeek API Key（llm 节点 local_config.json 或 DEEPSEEK_API_KEY）")
        print("[web_server] DSH web 界面可启动，但 DSH agent / BNOS 对话链路需要 Key 才能回复")

    bin_js = NODE_DIR / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
    if not bin_js.is_file():
        print("[web_server] DSH 编译包不存在（节点目录运行 start.bat 会自动安装）", file=sys.stderr)
        return 1

    port = sys.argv[1] if len(sys.argv) > 1 else "0"
    env = os.environ.copy()
    env["DSH_HOME"] = str(NODE_DIR / "dsh_home")
    env["DEEPSEEK_API_KEY"] = key
    env["BNOS_SHARED_DIR"] = str(NODE_DIR.parent / "shared")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    cmd = ["node", str(bin_js), "--profile", "web", "--port", port]
    print(f"[web_server] 启动 DSH web: {' '.join(cmd)}")
    print("[web_server] 就绪后浏览器访问输出中的 dsh web 地址")
    proc = subprocess.Popen(
        cmd,
        cwd=str(NODE_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    try:
        for line in proc.stdout:
            line = line.rstrip()
            print(line, flush=True)
            m = re.search(r"http://[0-9.:]+", line)
            if m and "dsh web" in line:
                print(f"[web_server] ✅ 请在浏览器打开: {m.group(0)}", flush=True)
        proc.wait()
    except KeyboardInterrupt:
        print("\n[web_server] 收到中断，正在关闭…")
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, timeout=10)
            else:
                proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
    return proc.returncode or 0


if __name__ == "__main__":
    sys.exit(main())
