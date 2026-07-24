"""pipeline.json 解析器。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class NodeDef:
    """pipeline.json 中单个节点的定义。"""

    type: str  # "standalone" | "composite"
    path: str
    entry: str = "main.py"
    exe_entry: str | None = None  # 编译后的 exe 文件名，优先于 entry + venv
    venv: str | None = None  # 预计算的 venv 路径（相对项目根目录）
    parameters: dict[str, Any] = field(default_factory=dict)
    timeout: int = 300
    resource_limit: dict[str, Any] | None = None
    # 复合节点专用
    runtime: str | None = None  # "inprocess" | "process"
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


def load_pipeline(path: Path) -> PipelineDef:
    """加载并解析 pipeline.json 文件。

    Args:
        path: pipeline.json 文件路径。

    Returns:
        PipelineDef 实例。
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    nodes = {}
    for nid, nd in data["nodes"].items():
        nodes[nid] = NodeDef(
            type=nd.get("type", "standalone"),
            path=nd["path"],
            entry=nd.get("entry", "main.py"),
            exe_entry=nd.get("exe_entry"),
            venv=nd.get("venv"),
            parameters=nd.get("parameters", {}),
            timeout=nd.get("timeout", 300),
            resource_limit=nd.get("resource_limit"),
            runtime=nd.get("runtime"),
            sub_nodes=nd.get("sub_nodes", {}),
            internal_edges=nd.get("internal_edges", []),
            external_input=nd.get("external_input", {}),
            external_output=nd.get("external_output", {}),
        )

    return PipelineDef(
        name=data.get("name", "unnamed"),
        nodes=nodes,
        edges=data.get("edges", []),
        generated_at=data.get("generated_at", ""),
        generated_from=data.get("generated_from", ""),
    )
