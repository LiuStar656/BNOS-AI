"""DAG 拓扑排序工具 — Kahn 算法。"""

from __future__ import annotations

from collections import defaultdict, deque


def topological_sort(nodes: list[str], edges: list[dict[str, str]]) -> list[list[str]]:
    """Kahn 拓扑排序，返回按依赖层级分组的批次。

    Args:
        nodes: 所有节点 ID 列表。
        edges: 边列表，每项包含 {"from": src, "to": tgt}。

    Returns:
        按执行顺序分组的批次列表。同一批次内的节点可并行执行。

    Raises:
        ValueError: 如果存在循环依赖。
    """
    in_degree: dict[str, int] = {n: 0 for n in nodes}
    children: dict[str, list[str]] = defaultdict(list)

    for edge in edges:
        src = edge["from"]
        tgt = edge["to"]
        if src in in_degree and tgt in in_degree:
            in_degree[tgt] += 1
            children[src].append(tgt)

    batches: list[list[str]] = []
    queue = deque(n for n, d in in_degree.items() if d == 0)

    visited_count = 0
    while queue:
        batch = []
        for _ in range(len(queue)):
            n = queue.popleft()
            batch.append(n)
            visited_count += 1
            for child in children[n]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)
        batches.append(batch)

    if visited_count != len(nodes):
        cycle_nodes = [n for n, d in in_degree.items() if d > 0]
        raise ValueError(
            f"Circular dependency detected among nodes: {cycle_nodes}"
        )

    return batches
