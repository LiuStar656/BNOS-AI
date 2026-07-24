"""pipeline.json 解析器。

pipeline.json 只描述拓扑关系（哪些节点、怎么连），
节点自身的配置（entry、parameters、resource_limit 等）
存储在各自的 node_config.json 中。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class NodeDef:
    """pipeline.json 中单个节点的定义。"""

    type: str = "standalone"  # "standalone" | "composite"
    path: str = ""  # 节点目录，相对项目根目录
    entry: str = "main.py"
    exe_entry: str | None = None
    venv: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    timeout: int = 300
    resource_limit: dict[str, Any] | None = None
    # 复合节点专用（旧格式兼容）
    runtime: str | None = None
    sub_nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    internal_edges: list[dict[str, str]] = field(default_factory=list)
    external_input: dict[str, list[str]] = field(default_factory=dict)
    external_output: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class PipelineDef:
    """pipeline.json 的完整定义。"""

    name: str
    nodes: dict[str, NodeDef]
    edges: list[dict[str, str]]
    generated_at: str = ""
    generated_from: str = ""


def _load_node_config(node_dir: Path) -> dict:
    """读取节点的 node_config.json，返回原始 dict，不存在时返回空 dict。"""
    cfg_path = node_dir / "node_config.json"
    if cfg_path.exists():
        try:
            with open(cfg_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _node_def_from_config(node_name: str, project_root: Path) -> NodeDef:
    """从 node_config.json + 约定推导 NodeDef。"""
    node_rel = f"nodes/{node_name}"
    node_dir = project_root / node_rel
    cfg = _load_node_config(node_dir)

    # node_config.json 的 parameters 是数组 [{name, type, default, ...}]
    # 转为引擎需要的 {name: default} 字典格式
    raw_params = cfg.get("parameters", [])
    if isinstance(raw_params, list):
        params = {}
        for p in raw_params:
            if isinstance(p, dict) and "name" in p:
                params[p["name"]] = p.get("default", "")
    elif isinstance(raw_params, dict):
        params = raw_params
    else:
        params = {}

    return NodeDef(
        type="standalone",
        path=node_rel,
        entry=cfg.get("entry", "main.py"),
        exe_entry=cfg.get("exe_entry"),
        parameters=params,
        resource_limit=cfg.get("resource_limit"),
    )


def load_pipeline(path: Path) -> PipelineDef:
    """加载并解析 pipeline.json 文件。

    Args:
        path: pipeline.json 文件路径。

    Returns:
        PipelineDef 实例。
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    project_root = path.parent
    nodes_raw = data.get("nodes", {})

    nodes = {}
    if isinstance(nodes_raw, list):
        # 新格式：nodes 是节点名列表
        for node_name in nodes_raw:
            nd = _node_def_from_config(node_name, project_root)
            nodes[node_name] = nd
    elif isinstance(nodes_raw, dict):
        # 旧格式兼容：nodes 是 {name: {...}} 字典（canvas 生成格式）
        # 缺失的字段从 node_config.json 补齐
        for nid, nd in nodes_raw.items():
            node_rel = nd.get("path", f"nodes/{nid}")
            node_dir = project_root / node_rel
            cfg = _load_node_config(node_dir)

            nodes[nid] = NodeDef(
                type=nd.get("type", "standalone"),
                path=node_rel,
                entry=nd.get("entry") or cfg.get("entry", "main.py"),
                exe_entry=nd.get("exe_entry"),
                venv=nd.get("venv"),
                parameters=nd.get("parameters", {}),
                timeout=nd.get("timeout", 300),
                resource_limit=nd.get("resource_limit") or cfg.get("resource_limit"),
            )

    return PipelineDef(
        name=data.get("name", "unnamed"),
        nodes=nodes,
        edges=data.get("edges", []),
        generated_at=data.get("generated_at", ""),
        generated_from=data.get("generated_from", ""),
    )
