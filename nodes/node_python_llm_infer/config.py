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


def extract_params(config=None):
    """从 config 的 parameters 中提取 {name: default} 字典"""
    if config is None:
        config = load_config()
    return {p["name"]: p.get("default") for p in config.get("parameters", [])}


def resolve(p):
    """将相对路径转为绝对路径（以 NODE_DIR 为基准）"""
    return os.path.normpath(os.path.join(NODE_DIR, p)) if not os.path.isabs(p) else p


# ── 本地密钥文件（local_config.json，不提交不追踪）──────────────────
# 密钥等敏感配置单独存放于此文件；缺失时初始化生成空模板。
_LOCAL_CONFIG_NAME = "local_config.json"


def local_config_path():
    return os.path.join(NODE_DIR, _LOCAL_CONFIG_NAME)


def ensure_local_config():
    """初始化本地密钥文件（不存在则生成空模板）。"""
    path = local_config_path()
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"api_key": "", "updated_at": ""}, f, ensure_ascii=False, indent=2)
    return path


def load_local_config():
    """读取本地密钥文件；缺失时先初始化。"""
    path = ensure_local_config()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"api_key": ""}


def save_local_config(data: dict) -> None:
    """原子写本地密钥文件（tmp + replace），data 需为可 JSON 序列化 dict。"""
    path = ensure_local_config()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def get_local_api_key() -> str:
    """从本地密钥文件读取 api_key（不回退环境变量，只读文件）。"""
    data = load_local_config()
    return str(data.get("api_key", "") or "").strip()
