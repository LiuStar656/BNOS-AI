"""
BNOS 节点 — 业务逻辑入口

使用方式：
  - listener.py 通过 subprocess 调用: python main.py '<json>'
  - 复合节点模式下通过 import 直接调用: process(data)

输出 JSON 格式：
  {
    "code": 0,
    "data": { ... },           # 业务数据
    "type": "port_name"        # 可选，用于多端口路由，对应 output_ports[*].name
  }

端口路由规则：
  - 返回 dict 中包含 "type" 字段 → 路由到 OUTPUT_PORTS[type]
  - 返回 dict 的 "data" 中包含 "_port" 字段 → 路由到 OUTPUT_PORTS[_port]
  - 无 type / _port → 路由到顶层 OUTPUT_FILE（回退）
"""

import atexit
import json
import os
import signal
import sys


# ════════════════════════════════════════════════════════════════
#  ★ 开发者在此类中编写所有业务逻辑 — 其他代码不要修改 ★
# ════════════════════════════════════════════════════════════════

class MyNode:
    """节点的业务逻辑处理器。"""

    def __init__(self):
        """初始化业务状态（可选覆盖）"""
        pass

    def process(self, data: dict) -> dict:
        """
        框架入口。

        参数:
            data: 上游传入的 dict（已解包，不含包装层）

        返回:
            dict: 业务数据，框架会自动包装为 {"code": 0, "data": <返回值>, "type": <端口名>}
                  如需指定输出端口，在返回 dict 中包含 "_port" 字段：
                  {"result": "xxx", "_port": "status"}  → 走 status 端口
                  {"result": "xxx"}                     → 走 default 端口（顶层回退）
        """
        # ═══ 在此实现你的业务逻辑 ═══
        demo_text = data.get("demo_text", "Hello, BNOS!")
        result = {
            "processed": True,
            "message": f"处理完成: {demo_text}",
            "original": data,
        }
        # ══════════════════════════════
        return result


# ════════════════════════════════════════════════════════════════
#  框架桥接（开发者不要修改）
# ════════════════════════════════════════════════════════════════

NODE_DIR = os.path.dirname(os.path.abspath(__file__))
_node = MyNode()


def process(data: dict) -> dict:
    """框架入口，由 listener.py 或 import 调用。"""
    return _node.process(data)


# ════════════════════════════════════════════════════════════════
#  __main__ 入口（仅直接运行 python main.py 时执行）
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # ── 条件 PID 写入 ─────────────────────────────────
    # 如果同目录没有 listener.py，说明 main.py 被引擎直接拉起（长期进程），需要写 PID
    # 如果有 listener.py，则 listener 负责写 PID，main.py 只是短期子进程
    _pid_file = os.path.join(NODE_DIR, f"{os.path.basename(NODE_DIR)}.pid")
    _has_listener = os.path.exists(os.path.join(NODE_DIR, "listener.py"))
    if not _has_listener:
        def _cleanup_pid():
            try:
                if os.path.exists(_pid_file):
                    os.unlink(_pid_file)
            except OSError:
                pass
        atexit.register(_cleanup_pid)
        signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))
        signal.signal(signal.SIGTERM, lambda s, f: sys.exit(0))
        with open(_pid_file, "w") as f:
            f.write(str(os.getpid()))

    # 读取输入（支持 argv 和 stdin 两种方式）
    input_data = {}
    if len(sys.argv) >= 2:
        try:
            input_data = json.loads(sys.argv[1])
        except Exception:
            pass
    if not input_data:
        try:
            s = sys.stdin.read().strip()
            if s:
                input_data = json.loads(s)
        except Exception:
            pass
    if not input_data:
        print(json.dumps({"code": -1, "error": "no input"}, ensure_ascii=False))
        sys.exit(1)

    # 执行业务逻辑
    result = process(input_data)

    # 输出（含端口路由）
    port = result.pop("_port", None)
    output = {"code": 0, "data": result}
    if port:
        output["type"] = port
    print(json.dumps(output, ensure_ascii=False))
