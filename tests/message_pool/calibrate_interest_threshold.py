# -*- coding: utf-8 -*-
"""兴趣门控阈值标定：用历史实验真实 reply 数据算「兴趣相似度」分布。

方法（对齐 [PLAN]-兴趣门控回复机制.md §三）：
    1. 读 decisions.jsonl，取 action=reply 且回应对象为单个 agent/user 的决策；
    2. 锚点 = 该 agent 自己的上一条广播发言（decisions.jsonl 中上一轮同 agent
       reply 的 content；无则跳过）；
    3. 目标消息 = batch_context 中 user_id == 回应对象 的那条（content 已截断
       60 字，嵌入长度足够）；
    4. sim = cos(encode(锚点), encode(目标消息))——这正是门控的兴趣值语义：
       「候选消息与我自己最近发言的相似度」；
    5. 基线 = 从 chat_history.jsonl 随机抽两两无关消息对（不同 agent 发言，
       且不是真实回复关系）的相似度分布；
    6. 输出：真实接话分布 + 基线分布 + 各阈值下的过门率曲线 + 建议阈值。

用法（项目根目录，AAA 节点 venv）：
    & nodes/node_python_aaa_cognition/venv/Scripts/python.exe \
        tests/message_pool/calibrate_interest_threshold.py \
        docs/experiments/message_pool_test/runs/20260808_115334_exp_5a30r_v3 \
        --model paraphrase-multilingual-MiniLM-L12-v2
"""
import argparse
import json
import os
import random

import numpy as np


def load_reply_pairs(decisions_path: str) -> tuple[list[tuple[str, str]], int]:
    """提取真实 reply 的（锚点, 目标消息）对。

    Returns:
        (pairs, total_reply): pairs 为可计算的 (anchor, target) 文本对，
        total_reply 为全部 reply 决策数（含无法计算的对）。
    """
    pairs: list[tuple[str, str]] = []
    total_reply = 0
    last_reply: dict[str, str] = {}  # agent_id -> 上一条广播发言
    with open(decisions_path, encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            d = json.loads(raw)
            if d.get("action") != "reply":
                continue
            total_reply += 1
            aid = d.get("agent", "")
            content = (d.get("content") or "").strip()
            target = (d.get("回应对象") or "").strip()
            # 锚点 = 自己上一条广播发言（上一轮同 agent 的 reply 内容）
            anchor = last_reply.get(aid, "")
            # 目标消息 = batch_context 中 user_id == 回应对象 的那条
            target_text = ""
            for m in d.get("batch_context") or []:
                if (m.get("user_id") or "").strip() == target:
                    target_text = (m.get("content") or "").strip()
                    break
            if anchor and target_text and target not in ("群聊", "多条", "所有人"):
                pairs.append((anchor, target_text))
            if content:
                last_reply[aid] = content
    return pairs, total_reply


def load_all_speeches(chat_path: str) -> list[str]:
    """读取聊天历史中全部 agent 广播发言（基线采样用）。"""
    texts = []
    with open(chat_path, encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            d = json.loads(raw)
            if d.get("role") == "agent":
                t = (d.get("content") or "").strip()
                if t:
                    texts.append(t)
    return texts


def main():
    ap = argparse.ArgumentParser(description="兴趣门控阈值标定")
    ap.add_argument("run_dir", help="实验留档目录（须含 decisions.jsonl / chat_history.jsonl）")
    ap.add_argument("--model", default="paraphrase-multilingual-MiniLM-L12-v2",
                    help="嵌入模型名（默认多语模型，本地无缓存时走 HF 镜像）")
    ap.add_argument("--seed", type=int, default=42, help="基线随机采样种子")
    ap.add_argument("--baseline-pairs", type=int, default=500,
                    help="基线随机消息对数量")
    args = ap.parse_args()

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(args.model)
    print(f"[模型] {args.model} 加载完成", flush=True)

    decisions_path = os.path.join(args.run_dir, "decisions.jsonl")
    chat_path = os.path.join(args.run_dir, "chat_history.jsonl")
    pairs, total_reply = load_reply_pairs(decisions_path)
    print(f"[数据] reply 决策 {total_reply} 条，可计算兴趣对 {len(pairs)} 条", flush=True)

    anchors = [p[0] for p in pairs]
    targets = [p[1] for p in pairs]
    if not anchors:
        print("[结果] 无可用数据")
        return
    a_v = model.encode(anchors, normalize_embeddings=True)
    t_v = model.encode(targets, normalize_embeddings=True)
    real = (a_v * t_v).sum(axis=1)

    # ── 基线：随机无关消息对 ──
    speeches = load_all_speeches(chat_path)
    rng = random.Random(args.seed)
    baselines: list[float] = []
    n = len(speeches)
    if n >= 4:
        candidates = speeches
        # 随机抽取不重复消息对（避免真实回复对混入基线）
        idx_pairs = set()
        guard = 0
        while len(idx_pairs) < args.baseline_pairs and guard < args.baseline_pairs * 20:
            guard += 1
            i, j = rng.randrange(n), rng.randrange(n)
            if i == j or abs(i - j) <= 2:  # 相邻消息可能是真实接话 → 排除
                continue
            idx_pairs.add((min(i, j), max(i, j)))
        if idx_pairs:
            base_src = [candidates[i] for i, j in sorted(idx_pairs)]
            base_tgt = [candidates[j] for i, j in sorted(idx_pairs)]
            b_v = model.encode(base_src, normalize_embeddings=True)
            b2_v = model.encode(base_tgt, normalize_embeddings=True)
            baselines = (b_v * b2_v).sum(axis=1).tolist()

    # ── 汇总 ──
    def _pct(arr, q):
        return float(np.percentile(arr, q))

    print("\n== 真实接话（锚点 vs 回应对象）相似度分布 ==")
    for q in (0, 5, 10, 25, 50, 75, 90, 95, 100):
        print(f"  p{q:>3} = {_pct(real, q):.3f}")
    print(f"  均值 = {real.mean():.3f}")
    if baselines:
        print("\n== 基线（随机无关消息对）相似度分布 ==")
        for q in (0, 5, 10, 25, 50, 75, 90, 95, 100):
            print(f"  p{q:>3} = {_pct(baselines, q):.3f}")
        print(f"  均值 = {np.mean(baselines):.3f}")

    print("\n== 阈值候选 → 过门率（真实接话保留比例） ==")
    for th in (0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7):
        rate = float((real >= th).mean())
        bl = float((np.array(baselines) >= th).mean()) if baselines else 0.0
        print(f"  阈值 {th:.2f} → 真实接话保留 {rate*100:.1f}%  基线误放 {bl*100:.1f}%")

    # 建议：真实接话 p25 与基线 p90 的中点（平衡灵敏度与纯度）
    if baselines:
        lo = _pct(real, 25)
        hi = _pct(baselines, 90)
        print(f"\n[建议] 真实接话 p25={lo:.3f} / 基线 p90={hi:.3f} → "
              f"阈值取中点 {((lo+hi)/2):.3f}（下限 0.40）")
    else:
        print(f"\n[建议] 无基线数据 → 取真实接话 p25={_pct(real, 25):.3f}（下限 0.40）")


if __name__ == "__main__":
    main()
