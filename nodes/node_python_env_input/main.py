"""环境数据采集节点（Phase 2+）"""
import sys
import json
import os
from datetime import datetime

def process(data):
    return data

def collect_env():
    """采集环境数据（Phase 2 实现）"""
    env = {"source": "env", "data_type": "text"}
    # TODO: Phase 2 添加 CPU/内存/天气/时间等采集
    return env

if __name__ == "__main__":
    if getattr(sys, 'frozen', False) or sys.argv[0].lower().endswith('.exe'):
        NODE_DIR = os.getcwd()
    else:
        NODE_DIR = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(NODE_DIR, "node_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if len(sys.argv) < 2:
        print(json.dumps({"code": -1, "error": "no input"}))
        sys.exit(1)
    input_data = json.loads(sys.argv[1])
    result = process(input_data)
    print(json.dumps({"code": 0, "type": cfg["output_type"], "data": result}, ensure_ascii=False))
