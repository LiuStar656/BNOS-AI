"""pipeline.json 生成器 — 从画布状态（canvas_layout.json + node_clusters.json）生成管线定义。"""

from __future__ import annotations

import json
import platform
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from bnos_runtime.orchestrator import topological_sort


# ──────────────────────────────────────────────
# 5.3 节点类型检测
# ──────────────────────────────────────────────


def classify_nodes(
    canvas_nodes: dict,
    node_clusters: dict,
) -> dict[str, str]:
    """将画布上的节点分为 standalone 和 composite 两类。

    检测规则（优先级从高到低）：
    1. node_clusters.json 中 composites[comp_id].nodes 包含该节点
       → 该节点是 composite 的子节点，不属于顶层 pipeline
    2. node_clusters.json 中 composites 的 comp_id 等于该节点名
       → 该节点本身是 composite 节点
    3. 否则 → standalone 节点
    """
    composite_child_nodes: set[str] = set()
    composite_ids: set[str] = set()
    for comp_id, comp in node_clusters.get("composites", {}).items():
        composite_ids.add(comp_id)
        for child_name in comp.get("nodes", []):
            composite_child_nodes.add(child_name)

    result: dict[str, str] = {}
    for node_name in canvas_nodes:
        if node_name in composite_ids:
            result[node_name] = "composite"
        elif node_name in composite_child_nodes:
            continue  # 跳过：复合节点内部子节点
        else:
            result[node_name] = "standalone"
    return result


# ──────────────────────────────────────────────
# 5.4 连线（edges）生成
# ──────────────────────────────────────────────


def build_pipeline_edges(
    canvas_edges: list[dict],
    composite_child_nodes: set[str],
    composite_ids: set[str],
    node_clusters: dict,
) -> tuple[list[dict], dict[str, list[dict]]]:
    """将画布 edges 拆分为顶层 edges 和复合节点 internal_edges。

    Returns:
        (top_edges, comp_internal_edges)
    """
    top_edges: list[dict] = []
    comp_internal_edges: dict[str, list[dict]] = defaultdict(list)

    for edge in canvas_edges:
        src = edge["source"]
        tgt = edge["target"]
        src_port = edge.get("source_port", "default")
        tgt_port = edge.get("target_port", "default")

        src_is_child = src in composite_child_nodes
        tgt_is_child = tgt in composite_child_nodes
        src_is_comp = src in composite_ids
        tgt_is_comp = tgt in composite_ids

        if src_is_child and tgt_is_child:
            # 两个都在复合内部 → 属于某个复合节点的 internal_edge
            comp_id = _find_parent_composite(src, node_clusters)
            if comp_id:
                comp_internal_edges[comp_id].append({
                    "from": src, "to": tgt,
                    "source_port": src_port, "target_port": tgt_port,
                })

        elif src_is_child and not tgt_is_child:
            # 复合内部 → 外部：合并为复合节点 → 外部
            comp_id = _find_parent_composite(src, node_clusters)
            if comp_id and comp_id != tgt:
                top_edges.append({
                    "from": comp_id, "to": tgt,
                    "source_port": src_port, "target_port": tgt_port,
                })

        elif not src_is_child and tgt_is_child:
            # 外部 → 复合内部：合并为外部 → 复合节点
            comp_id = _find_parent_composite(tgt, node_clusters)
            if comp_id and comp_id != src:
                top_edges.append({
                    "from": src, "to": comp_id,
                    "source_port": src_port, "target_port": tgt_port,
                })

        else:
            # 两个都是顶层 → 直接保留
            top_edges.append({
                "from": src, "to": tgt,
                "source_port": src_port, "target_port": tgt_port,
            })

    top_edges = _deduplicate_edges(top_edges)
    return top_edges, dict(comp_internal_edges)


def _find_parent_composite(node_name: str, node_clusters: dict) -> str | None:
    """查找节点所属的复合节点 ID。"""
    for comp_id, comp in node_clusters.get("composites", {}).items():
        if node_name in comp.get("nodes", []):
            return comp_id
    return None


def _deduplicate_edges(edges: list[dict]) -> list[dict]:
    """合并去重：同一对 (from, to) 只保留一条。"""
    seen: dict[tuple[str, str], dict] = {}
    for e in edges:
        key = (e["from"], e["to"])
        if key not in seen:
            seen[key] = e
    return list(seen.values())


# ──────────────────────────────────────────────
# 5.5 独立节点详情提取
# ──────────────────────────────────────────────


def extract_standalone_node(node_name: str, project_root: Path) -> dict:
    """从 node_config.json 提取独立节点的引擎配置。"""
    config_path = project_root / "nodes" / node_name / "node_config.json"
    config: dict[str, Any] = {}
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)

    # 推断 entry：根据 language 字段
    lang = config.get("language", "python")
    entry_map: dict[str, str] = {
        "python": "main.py",
        "rust": "main.rs",
        "javascript": "main.js",
        "go": "main.go",
        "shell": "main.sh",
    }
    entry = config.get("entry") or entry_map.get(lang.lower(), "main.py")

    # 探测 venv
    node_dir = project_root / "nodes" / node_name
    venv = _detect_venv(node_dir, project_root)

    # 提取参数
    parameters: dict[str, Any] = {}
    for param in config.get("parameters", []):
        param_name = param.get("name")
        param_value = param.get("default")
        if param_name:
            parameters[param_name] = param_value

    result: dict[str, Any] = {
        "type": "standalone",
        "path": f"nodes/{node_name}",
        "entry": entry,
        "exe_entry": _detect_exe(node_dir, node_name),
        "venv": str(venv.relative_to(project_root)) if venv else None,
        "parameters": parameters,
        "timeout": config.get("timeout", 300),
    }

    # 可选资源限制
    resource_limit = config.get("resource_limit")
    if resource_limit:
        result["resource_limit"] = resource_limit

    return result


def _detect_venv(node_dir: Path, project_root: Path) -> Path | None:
    """按优先级探测节点的 Python venv 路径。"""
    is_win = platform.system() == "Windows"

    candidates = [
        # 1) 节点自身 .venv
        node_dir / ".venv" / ("Scripts" if is_win else "bin") / ("python.exe" if is_win else "python3"),
        # 2) 项目级 venv
        project_root / "venv" / ("Scripts" if is_win else "bin") / ("python.exe" if is_win else "python3"),
    ]

    for c in candidates:
        if c.exists():
            return c.parent.parent  # 返回 .venv 目录路径
    return None  # 引擎运行时 fallback 到 sys.executable


def _detect_exe(node_dir: Path, node_name: str) -> str | None:
    """检测节点是否有 BNOS Studio 编译好的 exe。

    编译产物命名规范：<short_name>_node.exe（如 fetch_data_node.exe）。
    """
    try:
        from ui.core.node_build.base import extract_node_short_name

        short = extract_node_short_name(node_name)
        exe_name = f"{short}_node.exe"
        exe_path = node_dir / exe_name
        return exe_name if exe_path.exists() else None
    except ImportError:
        return None


# ──────────────────────────────────────────────
# 5.8 复合节点定义构建
# ──────────────────────────────────────────────


def build_composite_node_def(
    comp_id: str,
    comp: dict,
    internal_edges: list[dict],
    project_root: Path,
) -> dict:
    """从 node_clusters.json 条目构建复合节点的 pipeline 定义。"""
    child_nodes = comp.get("nodes", [])
    runtime_mode = comp.get("runtime", "inprocess")
    port_routing = comp.get("_port_routing", {})

    # 构建子节点定义
    sub_nodes: dict[str, dict[str, Any]] = {}
    for child_name in child_nodes:
        sub_path = f"nodes/{comp_id}/sub_nodes/{child_name}"
        sub_nodes[child_name] = {
            "path": sub_path,
            "entry": "main.py",
        }

    # 构建外部输入/输出映射
    ext_input: dict[str, list[str]] = {}
    for _port_name, routing in port_routing.get("input", {}).items():
        target_node = routing.get("target_node", child_nodes[0] if child_nodes else "")
        ext_input.setdefault(target_node, []).append("input.json")

    ext_output: dict[str, list[str]] = {}
    for _port_name, routing in port_routing.get("output", {}).items():
        src_node = routing.get("target_node", child_nodes[-1] if child_nodes else "")
        ext_output.setdefault(src_node, []).append("output.json")

    # 探测 venv
    comp_venv_dir = project_root / "composite_nodes" / comp_id / ".venv"
    venv = str(comp_venv_dir.relative_to(project_root)) if comp_venv_dir.exists() else None

    return {
        "type": "composite",
        "path": f"nodes/{comp_id}",
        "runtime": runtime_mode,
        "entry": "orchestrator.py",
        "venv": venv,
        "timeout": comp.get("timeout", 600),
        "sub_nodes": sub_nodes,
        "internal_edges": internal_edges,
        "external_input": ext_input,
        "external_output": ext_output,
    }


# ──────────────────────────────────────────────
# 5.7 pipeline.json 生成主函数
# ──────────────────────────────────────────────


def generate_pipeline(
    project_root: Path,
    output_path: Path,
    canvas_layout: dict,
    node_clusters: dict,
) -> dict:
    """从画布状态生成 pipeline.json。

    Args:
        project_root: 项目根目录。
        output_path: pipeline.json 输出路径。
        canvas_layout: canvas_layout.json 内容。
        node_clusters: node_clusters.json 内容（可能不存在）。

    Returns:
        生成的 pipeline dict。
    """
    composites = node_clusters.get("composites", {})

    # 1. 分类节点
    classified = classify_nodes(canvas_layout.get("nodes", {}), node_clusters)

    # 2. 收集复合节点子节点
    composite_child_nodes: set[str] = set()
    for comp_id, comp in composites.items():
        for child_name in comp.get("nodes", []):
            composite_child_nodes.add(child_name)

    # 3. 生成顶层 edges + 复合 internal_edges
    top_edges, comp_internal = build_pipeline_edges(
        canvas_layout.get("edges", []),
        composite_child_nodes,
        set(composites.keys()),
        node_clusters,
    )

    # 4. 构建节点定义
    nodes_def: dict[str, Any] = {}
    for node_name, node_type in classified.items():
        if node_type == "composite":
            comp = composites.get(node_name, {})
            nodes_def[node_name] = build_composite_node_def(
                node_name, comp, comp_internal.get(node_name, []), project_root,
            )
        else:
            nodes_def[node_name] = extract_standalone_node(node_name, project_root)

    # 5. 组装输出
    pipeline: dict[str, Any] = {
        "name": project_root.name,
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "generated_from": "canvas_layout.json + node_config.json",
        "nodes": nodes_def,
        "edges": top_edges,
    }

    # 写入文件
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(pipeline, f, ensure_ascii=False, indent=2)

    return pipeline


# ──────────────────────────────────────────────
# 5.9 build 时验证
# ──────────────────────────────────────────────


def validate_pipeline(pipeline: dict, project_root: Path) -> list[str]:
    """验证生成的 pipeline 是否合法。

    Returns:
        错误/警告信息列表。空列表表示完全通过。
    """
    errors: list[str] = []

    nodes = pipeline.get("nodes", {})
    edges = pipeline.get("edges", [])

    # 1. 节点入口文件存在
    for node_name, nd in nodes.items():
        entry = nd.get("entry", "main.py")
        node_path = project_root / nd["path"]
        entry_path = node_path / entry
        if not entry_path.exists():
            errors.append(f"[WARN] Node '{node_name}': entry file not found: {entry_path}")

    # 2. edges 完整性
    for edge in edges:
        src = edge["from"]
        tgt = edge["to"]
        if src not in nodes:
            errors.append(f"[WARN] Edge source '{src}' not found in nodes, skipping")
        if tgt not in nodes:
            errors.append(f"[WARN] Edge target '{tgt}' not found in nodes, skipping")

    # 5. 循环依赖检测（BNOS 支持双向数据流，循环节点将并行启动）
    try:
        topological_sort(list(nodes.keys()), edges)
    except ValueError as e:
        errors.append(f"[INFO] {e}")

    # 6. 孤立节点提示
    connected_nodes: set[str] = set()
    for edge in edges:
        connected_nodes.add(edge["from"])
        connected_nodes.add(edge["to"])
    for node_name in nodes:
        if node_name not in connected_nodes:
            errors.append(f"[INFO] Node '{node_name}' is isolated (no connections).")

    return errors
