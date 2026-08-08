# -*- coding: utf-8 -*-
"""AAA 认知节点子进程常驻服务（F9 专用，实验基础设施）。

职责：让一个 AAA 认知节点以「常驻子进程」方式运行，供消息池实验平台
以 stdin/stdout JSON 协议驱动（每 Agent 一个独立进程 → 进程级隔离 +
memOS 索引隔离 + 并行决策）。

协议（每行一个 JSON 请求 / 响应）：
    请求：
        {"type": "ping"}                                        # 探活
        {"type": "pool_batch", "conversation_id", "identity_key",
         "request_id", "messages": [{user_id, content}, ...]}   # 批量决策
        {"type": "flush_review"}                                # 等待 review 线程落库
        {"type": "llm_stats"}                                   # 查询本进程 LLM 调用量
        {"type": "shutdown"}                                    # 优雅退出
    响应：
        {"code": 0, "type": "<req type>", "data": {...}}
        {"code": -1, "type": "<req type>", "error": "..."}

LLM 通过环境变量注入（不写死在节点代码中）：
    AAA_LLM_MODE=real|fake        # 默认 fake（不调真实 API）
    AAA_API_URL / AAA_API_KEY / AAA_MODEL   # real 模式必填

隔离说明：
    - 每进程独立加载一次 memos 语义模型（~80MB），Agent ≤ 5。
    - 后台 review 线程在子进程内自行调 LLM（review.set_llm_call），
      与真实架构一致；进程退出前 flush_review 等待落库。
    - 后台重建线程（rebuild_index 等）在子进程内照常运行，
      native 崩溃风险由「进程隔离 + 串行请求」天然消除。
"""
import os
import sys
import json
import urllib.request

# 演化长跑防 OpenBLAS 内存分配失败（必须在 import numpy/memos 之前设置）
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")

NODE_DIR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "nodes", "node_python_aaa_cognition"))
if NODE_DIR not in sys.path:
    sys.path.insert(0, NODE_DIR)


# ── LLM（环境变量注入，与 run_pool_experiment 参数一致） ──────────
def _llm_real(prompt: str) -> str:
    body = {"model": os.environ.get("AAA_MODEL", "deepseek-v4-flash"),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7, "max_tokens": 2048}
    req = urllib.request.Request(
        os.environ.get("AAA_API_URL",
                       "https://api.deepseek.com/v1/chat/completions"),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ.get('AAA_API_KEY', '')}"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


_fake_counter = {"n": 0}


def _llm_fake(prompt: str) -> str:
    """假 LLM：交替返回 reply / silent（仅用于流程验收，不调 API）。"""
    _fake_counter["n"] += 1
    if _fake_counter["n"] % 2 == 1:
        return ("【自然回复】\n你好呀！看到你的消息啦\n【心情】\n开心\n"
                "【想法】\n想回应这条消息\n【情绪调整】\n0.05\n"
                "【事件摘要】\n用户发言，AI 回应 [重要性:3]\n"
                "【他人认知】\n这个用户很活跃")
    return ("【心情】\n平静\n【想法】\n这条消息听过了，不必回应\n"
            "【情绪调整】\n0.0\n【事件摘要】\n用户闲聊 [重要性:2]")


def _make_llm():
    """返回带调用计数的 LLM 函数（决策 + 后台 review 都经过它，计数全覆盖）。

    统计 API 调用量：real 模式为真实 API 请求次数，fake 模式为模拟调用次数。
    """
    _base = _llm_real if os.environ.get("AAA_LLM_MODE", "fake") == "real" \
        else _llm_fake
    stats = {"calls": 0}

    def _counted(prompt: str) -> str:
        stats["calls"] += 1
        return _base(prompt)

    _counted.stats = stats
    return _counted


# ── 服务主体 ────────────────────────────────────────────────────────
def main():
    # 保持 stdout 纯净（只输出协议 JSON），日志走 stderr
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    # v6.2 修复：节点代码 print（MemOS 图谱重建/缓存命中等，由 _on_parsed 后台
    # 线程触发）会污染 stdout 协议流 → 决策/llm_stats 响应被干扰 → agent_bridge
    # 解析失败 → 重启子进程 → 计数丢失（真实实验 API 调用量恒为 0 的根因）。
    # 全局把 print 重定向到 stderr；协议响应只经 sys.stdout.write，不受影响。
    import builtins
    _orig_print = builtins.print

    def _stderr_print(*args, **kwargs):
        kwargs.setdefault("file", sys.stderr)
        _orig_print(*args, **kwargs)

    builtins.print = _stderr_print

    import db
    import memos
    import review

    # AAA_SKIP_HEAVY=1（验收/fake 用）：跳过模型预加载与后台重建线程。
    # 必须在 import main 之前 patch——main 模块级会实例化 MyNode()，
    # 其 __init__ 内调用 memos.preload() 启动模型加载线程。
    # 真实实验不设此变量——子进程内照常运行（进程隔离保证安全）。
    if os.environ.get("AAA_SKIP_HEAVY") == "1":
        memos.preload = lambda: None
        memos.rebuild_index = lambda *a, **k: None
        memos.rebuild_knowledge_index = lambda *a, **k: None
        db._aggregate_mood = lambda *a, **k: None

    import main as aaa_main

    llm_fn = _make_llm()
    # 后台 review 线程内同步调 LLM（与对话并行）
    review.set_llm_call(llm_fn)

    # 从启动参数取 identity/db（实验桥接，覆盖 node_config 默认）
    identity = ""
    db_path = ""
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--identity" and i + 1 < len(args):
            identity = args[i + 1]
        elif a == "--db" and i + 1 < len(args):
            db_path = args[i + 1]
    if not identity:
        identity = "gui:default"
    if not db_path:
        from config import resolve, load_config
        db_path = resolve(load_config().get("db_path", "../shared/chatbot.db"))
    db_path = os.path.abspath(db_path)

    node = aaa_main.MyNode()
    db.ensure(db_path)  # 首次连接确保建表
    if memos._embeddings is None:
        memos.load_index(db_path)

    max_llm_rounds = 4
    print(f"[aaa_serve] identity={identity} db={db_path}", file=sys.stderr, flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            _respond("ping", {"code": -1, "type": "ping", "error": f"bad json: {e}"})
            continue

        req_type = req.get("type", "")
        if req_type == "shutdown":
            _respond(req_type, {"code": 0, "type": req_type, "data": {"status": "bye"}})
            break

        if req_type == "ping":
            _respond(req_type, {"code": 0, "type": req_type, "data": {"status": "ok"}})
            continue

        if req_type == "flush_review":
            _flush_review(node)
            _respond(req_type, {"code": 0, "type": req_type,
                                "data": {"status": "ok"}})
            continue

        if req_type == "llm_stats":
            _respond(req_type, {"code": 0, "type": req_type,
                                "data": {"calls": llm_fn.stats["calls"]}})
            continue

        if req_type == "pool_batch":
            try:
                decision = _handle_pool_batch(node, db_path, req, llm_fn,
                                              identity, max_llm_rounds)
                _respond(req_type, {"code": 0, "type": req_type,
                                    "data": decision})
            except Exception as e:
                _respond(req_type, {"code": -1, "type": req_type,
                                    "error": f"{type(e).__name__}: {e}"})
            continue

        _respond(req_type, {"code": -1, "type": req_type,
                            "error": f"unknown type: {req_type}"})

    # 退出前等待 review 线程落库（保证实验数据完整）
    _flush_review(node)


def _handle_pool_batch(node, db_path, req, llm_fn, identity, max_llm_rounds):
    """单批消息完整决策：_on_pool_batch → LLM → _on_parsed，直到 action。

    与 AgentBridge.process_batch（inline 模式）逻辑一致，保证两种模式行为等价。
    """
    messages = req.get("messages") or []
    if not messages:
        return {"action": "silent", "content": "", "user_id": "",
                "想法": "", "心情": "", "request_id": req.get("request_id", "")}
    conv_id = req.get("conversation_id") or "default"
    rid = req.get("request_id", "")
    out = node._on_pool_batch({
        "data_type": "pool_batch",
        "conversation_id": conv_id,
        "identity_key": req.get("identity_key") or identity,
        "request_id": rid,
        "messages": messages,
    }, db_path)
    last_user_id = messages[-1].get("user_id", "")
    decision = None
    for _ in range(max_llm_rounds):
        if not out or out.get("data_type") != "prompt":
            decision = out
            break
        content = llm_fn(out.get("content", ""))
        out = node._on_parsed({
            "data_type": "parsed", "source": "llm",
            "request_id": out.get("request_id", rid),
            "content": content or "",
        }, db_path, {}, user_id="", batch_mode=True)
    if decision is None:
        decision = {"action": "silent", "content": "", "user_id": "",
                    "想法": "", "心情": "", "request_id": rid}
    if not isinstance(decision, dict):
        decision = {"action": "silent", "content": "", "user_id": "",
                    "想法": "", "心情": "", "raw": decision}
    # v6.3 P0-2：user_id 归因由 _on_parsed 按【回应对象】决定，
    # 不再用批次末尾兜底（否则静默/回复都错误归因到最后发言者）。
    decision.setdefault("user_id", "")
    decision.setdefault("action", "silent")
    return decision


def _flush_review(node):
    """等待节点内所有后台 review 线程完成落库（daemon 线程不阻塞退出）。"""
    for t in getattr(node, "_review_threads", [])[:]:
        try:
            t.join(timeout=60)
        except Exception:
            pass
        node._review_threads = [x for x in node._review_threads if x is not t]


def _respond(req_type, payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
