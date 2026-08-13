"""
ContextEngine 上下文压缩管理（v4.0）

按会话跟踪对话历史 Token，超阈值时：
1. on_pre_compress：压缩前提取含持久化价值的洞察并立即写库（long_term_memory）
2. 生成历史摘要 + 保留最近 N 条完整消息

约束：只做 sqlite 写入（独立连接），严禁调用 memos / 语义模型
（与 review.py 同约束，防后台线程触发 OSError 1455 / native 崩溃）。
"""
import sqlite3
from datetime import datetime

# 含持久化价值的触发词（消息命中则压缩前抢救入库）
_DURABLE_KEYWORDS = ("我喜欢", "我讨厌", "我希望", "记住", "叫我", "我通常",
                     "我总是", "我从不", "我的名字", "我偏爱")


class ContextEngine:
    """上下文压缩管理：Token 估算 → 阈值判定 → 压缩前抢救 + 摘要"""

    def __init__(self, max_tokens: int = 128000,
                 threshold_percent: float = 0.75,
                 protect_last_n: int = 6):
        self.max_tokens = max_tokens
        self.threshold = threshold_percent
        self.protect_last_n = protect_last_n
        self._compression_log: list[dict] = []

    def estimate_tokens(self, messages: list[dict]) -> int:
        """粗略估算：中文 1.5 token/字，英文 0.25 token/字"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            cn = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
            total += int(cn * 1.5 + (len(content) - cn) * 0.25)
        return total

    def should_compress(self, current_tokens: int) -> bool:
        return (current_tokens / self.max_tokens) >= self.threshold

    def compress(self, messages: list[dict], db_path: str = "",
                 identity_key: str = "") -> list[dict]:
        """压缩前抢救洞察（写 long_term_memory）→ 生成摘要 → 返回压缩结果"""
        old = messages[:-self.protect_last_n] if len(messages) > self.protect_last_n else []
        insights = self._extract_insights_before_compression(
            old, db_path, identity_key)
        summary = self._generate_summary(messages)
        self._compression_log.append({
            "timestamp": datetime.now().isoformat(),
            "original_count": len(messages),
            "insights_extracted": len(insights),
        })
        keep = messages[-self.protect_last_n:]
        return [summary] + keep

    def _extract_insights_before_compression(self, messages, db_path, identity_key):
        """启发式提取含持久化价值的消息 → 立即写库"""
        insights = []
        for msg in messages:
            content = msg.get("content", "")
            if not content:
                continue
            if any(kw in content for kw in _DURABLE_KEYWORDS):
                snippet = content[:300]
                insights.append({"content": snippet, "source": "compression_recovery"})
                if db_path:
                    self._save_insight_to_db(snippet, db_path, identity_key)
        return insights

    def _generate_summary(self, messages) -> dict:
        """拼接最近消息要点为摘要消息"""
        points = [f"[{m.get('role')}]: {(m.get('content') or '')[:100]}"
                  for m in messages[-20:] if m.get("content")]
        return {"role": "system",
                "content": "【历史摘要（自动生成）】\n" + "\n".join(points[-10:]),
                "is_summary": True}

    def _save_insight_to_db(self, content, db_path, identity_key):
        """独立 sqlite 连接写库（不依赖 MemOS）"""
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO long_term_memory(conversation_id, identity_key, "
                "source, role, content, importance, source_confidence, created_at) "
                "VALUES('default', ?, 'compression_recovery', 'memory', ?, 4, 4, "
                "datetime('now','localtime'))",
                (identity_key, content))
            conn.commit()
        finally:
            conn.close()

    def get_compression_stats(self) -> dict:
        return {"total_compressions": len(self._compression_log),
                "last_compression": (self._compression_log[-1]
                                     if self._compression_log else None)}
