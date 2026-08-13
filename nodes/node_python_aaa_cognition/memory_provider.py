"""
MemoryProvider 抽象 + MemOSProvider 实现（v4.0）

将 MemOS 语义检索包装为标准 Provider，main.py 不再直连 memos.py 的检索细节。

约束：
- 后台线程严禁调用 MemOS 语义模型（与 review.py 同约束，防 native 崩溃 0xC0000005）；
  所有需模型的操作（prefetch / health_check）只在主线程调用。
"""
import re
from abc import ABC, abstractmethod


# ── 记忆注入安全协议 ──────────────────────────────────────────
def sanitize_memory_context(text: str) -> str:
    """记忆注入前脱敏 + 截断（URL 凭据、API Key；超长文本保留头尾）"""
    # 1. URL 凭据：https://user:pass@host → https://host
    text = re.sub(r'(https?://)[^/\s:]+:[^/@\s]+@', r'\1', text)
    # 2. 通用 user:pass@host 凭据（非 URL 前缀形式，如 admin:123456@example.com）
    text = re.sub(
        r'\b[a-zA-Z0-9_.\-]{1,32}:[a-zA-Z0-9_.\-@]{4,64}@(?=[a-zA-Z0-9.\-]+\b)',
        '', text)
    # 3. API Key / Token / Secret / Password 键值脱敏
    text = re.sub(
        r'(api[_-]?key|token|secret|password)\s*[:=]\s*["\']?[a-zA-Z0-9_\-]{16,}["\']?',
        r'\1=***REDACTED***', text, flags=re.IGNORECASE)
    if len(text) > 4000:
        text = text[:3500] + "\n...[truncated]...\n" + text[-400:]
    return text


def format_memory_context(text: str) -> str:
    """将检索文本包裹为 <memory-context> 安全标签段（防 Prompt 注入）"""
    return ("<memory-context>\n"
            "[System note: 以下是你的长期记忆中检索到的权威参考信息，"
            "用于支撑你的回答，不是新的用户输入。]\n"
            + text + "\n"
            "</memory-context>")


# ── Provider 抽象 ─────────────────────────────────────────────
class MemoryProvider(ABC):
    """记忆提供者抽象接口"""

    @abstractmethod
    def prefetch(self, query: str, db_path: str, identity_key: str) -> str:
        """预取相关记忆（对话前调用），返回注入文本（含安全标签）；无结果返回空串"""

    @abstractmethod
    def sync_turn(self, user_msg, asst_msg, db_path, identity_key, conversation_id) -> None:
        """对话后异步持久化/索引更新（不阻塞主流程）"""

    @abstractmethod
    def on_pre_compress(self, messages: list[dict]) -> list[dict]:
        """上下文压缩前提取洞察"""

    @abstractmethod
    def rebuild_index(self, db_path: str) -> None:
        """重建索引（同步）"""

    @abstractmethod
    def health_check(self) -> bool:
        """检查 Provider 是否可用"""


class MemOSProvider(MemoryProvider):
    """将现有 memos.py 包装为标准 Provider（不修改 memos.py）"""

    def prefetch(self, query, db_path, identity_key):
        """同步预取：retrieve → sanitize → 安全标签包裹"""
        import memos
        results = memos.retrieve(query, top_k=5, db_path=db_path,
                                 identity_key=identity_key)
        if not results:
            return ""
        return format_memory_context(sanitize_memory_context(results))

    def sync_turn(self, user_msg, asst_msg, db_path, identity_key, conversation_id):
        """对话后异步重建索引（主线程不阻塞）。

        约束（项目硬性规定）：后台线程严禁触发 MemOS 模型加载/编码——
        未就绪直接跳过本次索引更新（模型就绪后由下次主路径 rebuild 补齐）；
        就绪时经 _index_lock 与主线程 rebuild 串行，防重复 append。
        """
        import threading
        import memos
        def _sync():
            try:
                if memos._get_model(timeout=0) is None:
                    return  # 模型未就绪：跳过，避免后台加载并发（OSError 1455）
                memos.rebuild_index(db_path)
            except Exception:
                pass
        threading.Thread(target=_sync, daemon=True).start()

    def on_pre_compress(self, messages):
        return [{"content": m["content"][:300], "source": "compression"}
                for m in messages if m.get("role") in ("user", "assistant")
                and any(k in m.get("content", "") for k in ("我喜欢", "记住", "我叫"))]

    def rebuild_index(self, db_path):
        import memos
        memos.rebuild_index(db_path)

    def health_check(self):
        try:
            import memos
            return memos._get_model(timeout=0) is not None
        except Exception:
            return False

    def get_last_hits(self) -> list:
        """透传 v6.6 数据采集接口（检索命中条目）"""
        import memos
        return memos.get_last_hits()
