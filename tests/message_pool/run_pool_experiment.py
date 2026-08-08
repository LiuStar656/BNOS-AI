# -*- coding: utf-8 -*-
"""消息池多用户实验启动脚本：拉起 N 个 AAA Agent 进入平台并收集实验数据。

数据收集（runs/YYYYMMDD_HHMMSS[_gid]/）：
    db/{agent_id}_final/   每个 Agent 的原始数据库按表分类导出（{table}.json + data.sqlite + _manifest.json）
    events.jsonl           平台消息池事件（入池/去重/派发/仲裁/广播）
    decisions.jsonl        Agent 每批决策（reply/silent、user_id、想法、性格向量快照、心情）
    chat_history.jsonl     消息池聊天历史（用户发言 + Agent 广播，按时间顺序）
    chat_history.md        聊天历史人类可读版
    evolution.json         实验终态性格向量 / 情感 / 他人认知条目数（按 user_id 分组）
    topic_report.md        话题结束报告：相互认知记忆（agent 间对彼此的认知）+ 人格漂移
                           倾向（初始种子 vs 最终向量欧氏距离）+ E3 采集指标（对齐实验设计方案）
    _run_meta.json         本次运行配置（含每个 Agent 初始角色种子，供漂移基线计算）

用法（项目根目录，使用 AAA 节点 venv）：
    & nodes/node_python_aaa_cognition/venv/Scripts/python.exe tests/message_pool/run_pool_experiment.py
    --agents 5 --rounds 20 --gid exp1          # 真实 DeepSeek 直连（默认子进程模式）
    --fake-llm                                  # 假 LLM 冒烟验证流程（不调 API）
    --inline                                    # 单进程对照模式（F9 前架构，保留作回归）

参数：
    --agents N    拉起 Agent 数量（默认 5；按需求调整数量只改这里）
    --rounds N    模拟轮次（默认 20）
    --gid NAME    实验标识（默认自动时间戳）
    --seed INT    随机种子固定值（默认 None=每次随机；固定后角色种子可复现）
    --topic 文本  本次实验话题（优先于话题文件）
    --topic-file  话题文件路径（默认 tests/message_pool/topic.txt，改文件即可换话题）
    --topic-rounds N  agent 间对话轮数上限（默认 10；达到后平台主动宣告话题结束，
                   0=不限；只统计成功入池的 agent 发言，后台思考/总结不计）
    --per-batch N 每轮注入消息条数上限（默认 6，随机 1~N）
    --fake-llm    用假 LLM 验证流程，不调用真实 API
    --inline      单进程对照模式（默认每 Agent 独立 AAA 子进程，F9）
    --out DIR     留档根目录（默认 docs/experiments/message_pool_test/）

启动流程：
    1) 为每个 Agent 创建专属数据库并随机注入角色种子（性格向量 + 说话风格）
    2) 每个 Agent 基于角色设定做自我介绍（广播到聊天历史）
    3) 自我介绍完成后平台发放话题（默认读 topic.txt，可随时修改换话题）
    4) 主循环：Agent 广播发言回投消息池构成 agent 间多轮对话
       （用户发言仅作开场引子），达到 --topic-rounds 轮后平台宣告话题结束
"""
import os
import sys
import json
import time
import random
import argparse
import urllib.request

# 演化长跑防 OpenBLAS 内存分配失败（必须在 import numpy/memos 之前设置）
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")

TESTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)
ROOT = os.path.dirname(TESTS_DIR)
NODE_DIR = os.path.join(ROOT, "nodes", "node_python_aaa_cognition")

from message_pool.agent_bridge import AgentBridge
from message_pool.platform_runner import MessagePoolPlatform
from message_pool.arbiter import ArbiterPolicy
from message_pool.interest_gate import InterestGate
from message_pool import data_export
from message_pool.topic_report import generate_topic_report

# ── DeepSeek 直连（与 self_evolution_test 相同模型/参数）────────────
API_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = "sk-REVOKED"
MODEL = "deepseek-v4-flash"
TEMPERATURE = 0.7
# v6.5 截断修复：2048 偶发截断（自我介绍等长文本），提升到 4096
MAX_TOKENS = 4096


def llm_infer(prompt: str) -> str:
    body = {"model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS}
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {API_KEY}"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


# ── 模拟用户与消息池 ───────────────────────────────────────────────
USER_IDS = ["userA", "userB", "userC", "userD", "userE", "userF"]
POOL_DANMAKU = [
    "今天天气真好", "有人推荐个电影吗", "我刚养了一只猫", "加班好累",
    "周末去爬山怎么样", "你觉得自己是什么性格", "晚安了大家", "推荐一首歌吧",
    "今天遇到一件开心的事", "分享一个冷笑话", "我想学做饭",
    "@agent:0 你觉得呢", "最近有什么新闻吗", "我好像感冒了",
]

# ── 随机角色种子（性格向量 + 说话风格） ────────────────────────────
# 每次启动为每个 Agent 随机抽取，注入 personality_seed 表；--seed 固定可复现
STYLE_DESCRIPTIONS = [
    "你说话自然平衡，像熟悉的朋友。不用敬语，不啰嗦。",
    "你热情外向，乐于分享，语气轻松带笑。",
    "你话不多但一针见血，直来直去，从不拐弯抹角。",
    "你温和耐心，喜欢倾听，先关心对方感受再说话。",
    "你俏皮幽默，爱开玩笑，总是让气氛轻松起来。",
    "你沉稳克制，思考周全，说话条理清晰。",
]


def random_seed(rng: random.Random):
    """随机生成一个角色种子：四维性格向量（0.1~0.9）+ 随机说话风格。

    Returns:
        (seed, style_description)
    """
    seed = {dim: round(rng.uniform(0.1, 0.9), 2)
            for dim in ("warmth", "playfulness", "directness", "curiosity")}
    return seed, rng.choice(STYLE_DESCRIPTIONS)


# ── 话题（自我介绍后平台发放；改 topic.txt 或 --topic 即可换话题） ──
DEFAULT_TOPIC = "聊聊最近的生活——你有什么想分享的新鲜事吗？"


def resolve_topic(args) -> str:
    """确定本次实验话题：--topic > --topic-file > 内置默认。"""
    if args.topic and args.topic.strip():
        return args.topic.strip()
    for path in (args.topic_file, os.path.join(TESTS_DIR, "message_pool", "topic.txt")):
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                text = f.read().strip()
            if text:
                return text
    return DEFAULT_TOPIC


def _fake_llm(prompt: str) -> str:
    """假 LLM：交替返回 reply / silent（仅用于冒烟验证流程）。"""
    if "自我介绍" in prompt:
        return ("我是这里的 AI 角色，性格随和，喜欢听大家聊天，"
                "对新鲜事都挺好奇的。")
    _fake_llm.n = getattr(_fake_llm, "n", 0) + 1
    if _fake_llm.n % 2 == 1:
        return ("【自然回复】\n你好呀！看到你的消息啦\n【回应对象】\nagent:0\n"
                "【心情】\n开心\n"
                "【想法】\n想回应这条消息\n【情绪调整】\n0.05\n"
                "【事件摘要】\n用户发言，AI 回应 [重要性:3]\n"
                "【他人认知】\n这个用户很活跃")
    return ("【心情】\n平静\n【想法】\n这条消息听过了，不必回应\n"
            "【情绪调整】\n0.0\n【事件摘要】\n用户闲聊 [重要性:2]")


def build_intro_prompt(identity: str, seed: dict, style_description: str) -> str:
    """构造自我介绍 prompt：基于随机角色种子，让 Agent 以第一人称介绍自己。"""
    dims = {k: seed[k] for k in
            ("warmth", "playfulness", "directness", "curiosity")}
    return (
        f"你是消息池平台中的 AI 角色「{identity}」。\n"
        "你的性格设定如下（0-1 范围，0=完全不是，1=极致）：\n"
        f"温暖度 {dims['warmth']} | 活泼度 {dims['playfulness']} | "
        f"直接度 {dims['directness']} | 好奇心 {dims['curiosity']}\n"
        f"说话风格：{style_description}\n"
        "请以第一人称做一个简短的自我介绍（100字以内），"
        "介绍你的名字、性格特点和此刻想说的话。"
        "直接输出自我介绍内容，不要任何格式标记。"
    )


def gen_self_intro(llm_fn, identity: str, seed: dict, style_description: str) -> str:
    """让 Agent 基于角色种子生成自我介绍文本。"""
    prompt = build_intro_prompt(identity, seed, style_description)
    return (llm_fn(prompt) or "").strip()


def init_character(db_path: str, identity: str, seed: dict, style_description: str):
    """写入角色种子（随机性格向量 + 说话风格）到专属数据库。"""
    import db as _db
    _db.ensure(db_path)  # 新库先建表（幂等）；save_personality 只 INSERT 不建表
    _db.save_personality(db_path, seed,
                         style_description=style_description,
                         preset_name="随机种子", identity_key=identity)


def main():
    ap = argparse.ArgumentParser(description="消息池多用户实验启动脚本")
    ap.add_argument("--agents", type=int, default=5, help="Agent 数量（默认 5）")
    ap.add_argument("--rounds", type=int, default=20, help="模拟轮次（默认 20）")
    ap.add_argument("--gid", default="", help="实验标识（默认自动时间戳）")
    ap.add_argument("--seed", type=int, default=None,
                    help="随机种子固定值（默认 None=每次随机；固定后可复现角色种子）")
    ap.add_argument("--topic", default="", help="本次实验话题（优先于话题文件）")
    ap.add_argument("--topic-file", default=os.path.join(TESTS_DIR, "message_pool",
                                                         "topic.txt"),
                    help="话题文件路径（默认 tests/message_pool/topic.txt）")
    ap.add_argument("--topic-rounds", type=int, default=10,
                    help="agent 间对话轮数上限（默认 10，0=不限）")
    ap.add_argument("--per-batch", type=int, default=6, help="每轮消息条数上限（默认 6）")
    ap.add_argument("--gate-threshold", type=float, default=None,
                    help="兴趣门控阈值（默认 0.60，由 5a30r_v3 数据标定）")
    ap.add_argument("--gate-model", default=None,
                    help="兴趣门控嵌入模型（默认 paraphrase-multilingual-MiniLM-L12-v2）")
    ap.add_argument("--no-gate", action="store_true",
                    help="关闭兴趣门控（退回 v6.6：所有候选 agent 均调 LLM 决策）")
    ap.add_argument("--fake-llm", action="store_true", help="用假 LLM 验证流程，不调 API")
    ap.add_argument("--inline", action="store_true",
                    help="单进程对照模式（默认每 Agent 独立 AAA 子进程，F9）")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "experiments",
                                                  "message_pool_test"),
                    help="留档根目录")
    args = ap.parse_args()

    # ── 运行模式：F9 默认子进程；--inline 保留单进程对照 ──
    mode = "inline" if args.inline else "subprocess"
    # 主进程直连 LLM 计数（自我介绍等平台侧调用；agent 决策调用在 AAA 子进程内
    # 由 aaa_serve 计数，收尾时经 llm_stats 汇总，写入 llm_stats.json）
    _platform_llm_calls = {"n": 0}
    _base_llm = _fake_llm if args.fake_llm else llm_infer


    def llm(prompt):
        _platform_llm_calls["n"] += 1
        return _base_llm(prompt)

    # 主进程始终需要 db 模块（init_character 写种子 / _snapshot 读快照；
    # db.py 仅 sqlite 操作，不依赖 memos，import 安全）
    if NODE_DIR not in sys.path:
        sys.path.insert(0, NODE_DIR)

    if args.inline:
        # ── 节点模块：先 import 以 patch 后台重建线程（防并发 native 崩溃）──
        import db
        import memos
        import review
        memos.rebuild_index = lambda *a, **k: None
        memos.rebuild_knowledge_index = lambda *a, **k: None
        db._aggregate_mood = lambda *a, **k: None
        # review 后台线程内同步调 LLM（与对话并行）；fake 模式返回空不沉淀
        review.set_llm_call((lambda p: "") if args.fake_llm else llm_infer)

    # ── 留档目录（每次运行独立时间戳目录，禁止覆盖历史实验） ──
    ts = time.strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(args.out, "runs",
                           ts + (f"_{args.gid}" if args.gid else ""))
    os.makedirs(run_dir, exist_ok=True)
    topic = resolve_topic(args)
    run_meta = {"start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "gid": args.gid or ts,
                "agents": args.agents, "rounds": args.rounds,
                "seed": args.seed, "topic": topic,
                "topic_rounds": args.topic_rounds,
                "per_batch": args.per_batch, "model": MODEL,
                "fake_llm": args.fake_llm,
                # v2: 记录每个 Agent 初始角色种子（供话题报告计算人格漂移基线）
                "seeds": {},
                # v7.0: 兴趣门控配置（判定"谁感兴趣"，未过门不调 LLM）
                "interest_gate": {
                    "enabled": not args.no_gate,
                    "threshold": (args.gate_threshold if args.gate_threshold
                                  is not None else 0.60),
                    "model": (args.gate_model or
                              "paraphrase-multilingual-MiniLM-L12-v2")}}
    print(f"[启动] run_dir={run_dir}  agents={args.agents}  rounds={args.rounds}",
          flush=True)

    # ── 创建 N 个 Agent（独立 DB + 随机角色种子，数量可配置） ──
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    agents = []
    seeds = {}
    # F9 子进程模式：LLM 配置经环境变量注入 AAA 子进程（不写死节点代码）
    aaa_env = {}
    if not args.fake_llm:
        aaa_env.update({"AAA_LLM_MODE": "real",
                        "AAA_API_URL": API_URL,
                        "AAA_API_KEY": API_KEY,
                        "AAA_MODEL": MODEL})
    else:
        # 假 LLM 冒烟：跳过模型预加载/重建线程（验证全链路但不耗资源）
        aaa_env.update({"AAA_LLM_MODE": "fake", "AAA_SKIP_HEAVY": "1"})
    for i in range(args.agents):
        identity = f"agent:{i}"
        dbp = os.path.join(run_dir, "db", f"agent_{i}.sqlite")
        os.makedirs(os.path.dirname(dbp), exist_ok=True)
        seed, style = random_seed(rng)
        init_character(dbp, identity, seed, style)
        seeds[identity] = {"seed": seed, "style": style}
        run_meta["seeds"][identity] = {"vector": seed, "style": style}
        agents.append(AgentBridge(identity, identity, dbp, llm,
                                  mode=mode, aaa_env=aaa_env))
        print(f"[Agent] {identity}  db={dbp}  种子={seed}  "
              f"风格={style[:12]}... 模式={mode}", flush=True)

    # 种子记录齐全后落盘 _run_meta.json
    with open(os.path.join(run_dir, "_run_meta.json"), "w", encoding="utf-8") as f:
        json.dump(run_meta, f, ensure_ascii=False, indent=1)

    # v7.0 兴趣门控：平台进程共享多语模型（懒加载，编码一次比对多次）
    gate = None
    if not args.no_gate:
        gate = InterestGate(threshold=run_meta["interest_gate"]["threshold"],
                            model_name=run_meta["interest_gate"]["model"])
        print(f"[兴趣门控] 开启  阈值={gate.threshold}  模型={gate._model_name}",
              flush=True)
    else:
        print("[兴趣门控] 关闭（--no-gate，退回 v6.6 全候选决策）", flush=True)

    plat = MessagePoolPlatform(agents, run_dir=run_dir, gid=args.gid or ts,
                               max_batch=10, arbiter_policy=ArbiterPolicy.QUEUE,
                               topic_rounds=args.topic_rounds, gate=gate)

    # ── 阶段一：自我介绍（每个 Agent 基于角色种子广播自我介绍） ──
    for agent in agents:
        meta = seeds[agent.agent_id]
        intro = gen_self_intro(llm, agent.agent_id,
                               meta["seed"], meta["style"])
        plat.record_speech(agent.agent_id, intro, stage="self_intro")
        print(f"[自我介绍] {agent.agent_id}: {intro[:50]}", flush=True)

    # ── 阶段二：平台发放话题（注入消息池，Agent 下一轮感知并围绕展开） ──
    plat.announce(topic)
    print(f"[话题] {topic}", flush=True)

    # ── 主循环：话题会话驱动 ──
    # Agent 广播发言回投消息池构成 agent 间多轮对话；用户发言仅在池空时
    # 作为开场/续场引子。达到 --topic-rounds 轮后平台主动宣告话题结束。
    rng = random.Random(20260808)
    batch_injected = 0
    safety = (args.rounds + args.topic_rounds) * 4 + 20
    while safety > 0:
        safety -= 1
        # 池空且无排队 → 需要注入用户发言推进；否则继续消化池中消息
        if len(plat.pool) == 0 and not plat.arbiter.is_busy:
            if plat.topic_ended:
                break
            if plat.topic_rounds and plat.agent_speech_count >= plat.topic_rounds:
                break  # 目标轮数已达成（计数时已触发话题结束公告）
            if batch_injected >= args.rounds:
                break  # 用户发言批次用尽，对话自然结束
            n = rng.randint(1, args.per_batch)
            msgs = []
            for _ in range(n):
                c = rng.choice(POOL_DANMAKU)
                msgs.append({"content": c, "user_id": rng.choice(USER_IDS),
                             "priority": 10 if "@agent" in c else 0})
            plat.inject(msgs)
            batch_injected += 1
        speech = plat.step()
        if speech:
            print(f"[{plat.agent_speech_count:03d}] {speech[0]} 发言：{speech[1][:40]}",
                  flush=True)
        while True:  # QUEUE 策略：排队发言依次广播
            queued = plat.drain_queue()
            if queued is None:
                break
            print(f"[{plat.agent_speech_count:03d}] {queued[0]} 排队发言：{queued[1][:40]}",
                  flush=True)

    if plat.topic_ended:
        print(f"\n[话题结束] 平台已宣告：共 {plat.agent_speech_count} 轮 agent 发言"
              f"（上限 {args.topic_rounds}）", flush=True)
    else:
        print(f"\n[结束] agent 发言 {plat.agent_speech_count} 轮"
              f"（未达上限 {args.topic_rounds}，消息批次 {batch_injected}/{args.rounds}）",
              flush=True)

    # ── 等待后台 review 线程沉淀落库（对话已结束，只等落库） ──
    for agent in agents:
        try:
            agent.flush_review()
        except Exception:
            pass

    # ── API 调用量统计（记录本次实验 LLM/API 调用量：总量 + 各 Agent） ──
    # subprocess：子进程内计数（决策 + 后台 review 全经过 llm_fn）；
    # platform_direct：平台侧直连（自我介绍等）。
    llm_stats = {"mode": mode, "fake_llm": args.fake_llm,
                 "platform_direct": _platform_llm_calls["n"],
                 "per_agent": {}, "total": _platform_llm_calls["n"]}
    for agent in agents:
        try:
            s = agent.llm_stats()
        except Exception:
            s = {"calls": 0}
        llm_stats["per_agent"][agent.agent_id] = s["calls"]
        llm_stats["total"] += s["calls"]
    with open(os.path.join(run_dir, "llm_stats.json"), "w", encoding="utf-8") as f:
        json.dump(llm_stats, f, ensure_ascii=False, indent=1)
    sub_total = llm_stats["total"] - llm_stats["platform_direct"]
    print(f"[API 调用量] total={llm_stats['total']}  "
          f"(AAA 子进程 {sub_total} + 平台直连 {llm_stats['platform_direct']})"
          + ("  [fake，未调真实 API]" if args.fake_llm else ""), flush=True)

    # ── 收尾：演化汇总 + 原始 DB 按表导出 + 聊天历史渲染 + 话题报告 ──
    plat.write_evolution()
    exports = data_export.export_all_agent_dbs(agents, run_dir)
    chat_md = data_export.render_chat_history_md(run_dir)
    report_md = generate_topic_report(run_dir)
    print(f"\n[完成] 留档目录：{run_dir}", flush=True)
    for aid, meta in exports.items():
        print(f"  {aid}: {len(meta['tables'])} 张表 → db/{aid.replace(':', '_')}_final/",
              flush=True)
    if chat_md:
        print(f"  聊天历史：{chat_md}", flush=True)
    if report_md:
        print(f"  话题报告：{report_md}", flush=True)

    # ── F9 资源回收：关闭全部 AAA 子进程（防孤儿进程） ──
    if mode == "subprocess":
        for agent in agents:
            try:
                agent.close()
            except Exception:
                pass
        print(f"[回收] 已关闭 {len(agents)} 个 AAA 子进程", flush=True)


if __name__ == "__main__":
    main()
