"""
配置加载模块 - 惰性加载 node_config.json
"""
import json
import os

NODE_DIR = os.path.dirname(os.path.abspath(__file__))

_config = None


def load_config():
    """惰性加载 node_config.json"""
    global _config
    if _config is not None:
        return _config
    path = os.path.join(NODE_DIR, "node_config.json")
    _config = json.load(open(path, "r", encoding="utf-8")) if os.path.exists(path) else {}
    return _config


def resolve(p):
    """将相对路径转为绝对路径（以 NODE_DIR 为基准）"""
    return os.path.normpath(os.path.join(NODE_DIR, p)) if not os.path.isabs(p) else p
