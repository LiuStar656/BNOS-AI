# -*- coding: utf-8 -*-
"""@ 点名路由（对齐 Lumi_Nox pick_speaker）。

- @ 了单个 Agent → 该 Agent 优先处理该批消息。
- @ 了多个 Agent → 按点名出现顺序。
- 无 @ → 全部 Agent 独立评估（各自决定要不要回应，由仲裁器收敛最终发言者）。

点名语法：`@agent_id` 或 `@身份别名`（identity_key 的 `:` 后半段）。
"""


def find_mentions(text, agent_ids, mention_prefix="@"):
    """返回文本中点名到的 agent_id 列表（按出现顺序，去重）。"""
    found = []
    for aid in agent_ids:
        aliases = (mention_prefix + aid, mention_prefix + aid.split(":")[-1])
        if any(alias in text for alias in aliases):
            found.append(aid)
    return found


def pick_speaker(messages, agent_ids, mention_prefix="@"):
    """路由一批消息。

    Args:
        messages: list[Message] 或 list[dict]（含 text/content 字段）
        agent_ids: list[str] 全部 Agent 的 agent_id

    Returns:
        (target_agents, mentioned)
        - target_agents: 本轮派发顺序（被点名的在前，其余按 agent_ids 原序）
        - mentioned: 被点名到的 agent_id 列表（可为空）
    """
    mentioned = []
    for m in messages:
        text = m.text if hasattr(m, "text") else m.get("text", m.get("content", ""))
        for aid in find_mentions(text, agent_ids, mention_prefix):
            if aid not in mentioned:
                mentioned.append(aid)
    if mentioned:
        rest = [a for a in agent_ids if a not in mentioned]
        return mentioned + rest, mentioned
    return list(agent_ids), []
