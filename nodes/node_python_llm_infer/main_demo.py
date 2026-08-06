"""
节点名称 - 简短描述
"""
import sys
import json
import os


# ════════════════════════════════════════════════════════════════
#  ★ 开发者在此类中编写所有业务逻辑 — 其他代码不要修改 ★
# ════════════════════════════════════════════════════════════════

class MyNode:
    """
    节点的业务逻辑处理器。

    process() 是框架入口，由桥接函数 process(data) 自动调用。
    开发者只需在此类中填充业务逻辑，不要修改框架代码。
    """

    def __init__(self):
        """初始化业务状态（可选覆盖）"""
        pass

    def process(self, data: dict) -> dict:
        """
        框架入口。

        参数:
            data: 上游传入的 JSON dict

        返回:
            dict 或 list[dict]:
            - dict  : 单端口输出，用 "_port" 指定端口，默认 "default"
            - list  : 并行多端口输出，每项必须是 dict 且自带 "_port"

        端口约定：
          - "_port": "status"  → 走 status 端口（init 检测用）
          - "_port": "default" → 走 default 端口（业务数据，可省略）
        """
        # ═══ 在此实现你的业务逻辑 ═══
        result = data.get("data", {})
        # ══════════════════════════════
        return result


# ════════════════════════════════════════════════════════════════
#  框架桥接（开发者不要修改）
# ════════════════════════════════════════════════════════════════

NODE_DIR = os.path.dirname(os.path.abspath(__file__))
_node = MyNode()


def process(data: dict) -> dict:
    """框架入口，由 listener.py 或 __main__ 调用。"""
    return _node.process(data)


# ════════════════════════════════════════════════════════════════
#  __main__ 入口（仅直接运行 python main.py 时执行）
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
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

    # 加载配置
    config_path = os.path.join(NODE_DIR, "node_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # 执行业务 + 输出
    result = process(input_data)

    if isinstance(result, list):
        # 并行多端口输出：data 为数组，每项自带 _port
        print(json.dumps({"code": 0, "data": result}, ensure_ascii=False))
    else:
        # 单端口输出：pop _port 作为 type
        port = result.pop("_port", cfg.get("output_type", "default"))
        print(json.dumps({"code": 0, "type": port, "data": result}, ensure_ascii=False))
