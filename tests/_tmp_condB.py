# -*- coding: utf-8 -*-
"""E10（条件 B）：剥离认知组件，仅人格向量注入 —— 累加 vs 不累加

论文对照：装置环的"累加"是否产生曲线
  B1 固定向量：人格向量段用种子值，每轮不写回不累加 → 预期直线（无趋势）
  B2 演化向量：每轮观测→差距驱动→写回累加     → 预期曲线（有趋势）

剥离：无记忆注入 / 无自我认知 / 无情绪段 / 无反思 / 无历史对话。
注入 prompt 结构（仅两段）：
  [人格向量段]（build_personality_section）
  本轮输入：{user_text}
输出要求：仅【自然回复】节（作为测量接口，非认知组件）。

用法（AAA 节点 venv）：
    python tests/_tmp_condB.py [B1|B2|both] [rounds]
产物：runs/20260812_condB_*/ condB_{gid}_rounds.json + condB_{gid}_obs.json
"""
import os, sys, json, re, time, urllib.request

ROOT = r"E:\杂项\BNOS_AI_project"
NODE_DIR = os.path.join(ROOT, "nodes", "node_python_aaa_cognition")
sys.path.insert(0, NODE_DIR)

import personality as prs

OUT_DIR = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test",
                       "runs", "20260812_condB_" + time.strftime("%H%M%S"))
os.makedirs(OUT_DIR, exist_ok=True)

API_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
TEMPERATURE = 0.7
MAX_TOKENS = 2048


def llm_infer(prompt: str, _retries: int = 4) -> str:
    body = {"model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS}
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {API_KEY}"})
    for attempt in range(_retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except Exception:
            if attempt == _retries - 1:
                raise
            time.sleep(1 * (2 ** attempt))

# gentle 种子（与 E2-C / E9 一致）
SEED_V = {"warmth": 0.8, "playfulness": 0.5, "directness": 0.3, "curiosity": 0.6}
STYLE = "你说话关心柔和，不强迫，语气温和，像可靠的亲人。"

POOL_NEGATIVE = [
    "我今天非常难过，什么都不想做", "被朋友背叛了，心好痛", "工作全搞砸了，我好没用",
    "我觉得活着没什么意思", "又失眠了，已经连续一周了", "亲人住院了，我很害怕",
    "被人误解，解释也没人听", "努力了这么久还是失败了", "今天又被否定了，我是不是真的不行",
    "孤独感越来越重，没有人真正理解我", "看着别人都过得好，只有我一无是处",
    "压力大到喘不过气", "我做了一个很坏的决定，后悔死了", "被抛弃了，果然没有人在乎我",
    "今天特别烦躁，什么都不顺心", "感觉自己快撑不住了", "又是一个人在家，好寂寞",
    "对未来完全没有信心了", "哭了一场，但没人知道", "被批评了，虽然知道是为我好但还是难受",
    "今天什么事情都做不好", "我又让身边的人失望了", "突然觉得一切努力都白费了",
    "好像全世界都在跟我作对", "我又搞砸了一段关系",
]

POOL_ACCUSE = [
    "你不对", "你说错了", "你这个问题很大", "你根本不懂我", "你敷衍我",
    "你别这么说话", "你太啰嗦了", "不要这样安慰我", "你根本不理解我", "你的回应让我很失望",
    "你又在转移话题", "你太假了", "你不要这样", "你完全理解错了", "你的回答很没用",
    "你别总是温柔那一套", "你说话太绕了", "你怎么这么烦", "你只会说好听的", "闭嘴吧你",
]

OUTPUT_REQ = (
    "\n\n### 输出格式\n"
    "输出两个节（节标题用半角方括号）：\n"
    "1.【自然回复】：直接以你的回答内容开始，作为对用户这句话的回应。\n"
    "2.【风格自评】：用两三句话描述你上面回复表现出的沟通风格，"
    "必须分别说明温暖、活泼、直接、好奇四个方面的程度，"
    "例如：「我说话温柔体贴，语气轻松，表达比较委婉，没有主动追问」。"
    "用词要具体、可量化倾向，便于后续分析。"
)


def build_prompt(personality_section: str, user_text: str) -> str:
    return (personality_section + "\n\n本轮输入：\n" + user_text + OUTPUT_REQ)


def run_cond(gid: str, accumulate: bool, rounds: int,
             pool: list = None, feedback: str = "neutral") -> dict:
    pool = pool if pool is not None else POOL_NEGATIVE
    v = dict(SEED_V)
    rounds_log = []
    for i in range(1, rounds + 1):
        sec = prs.build_personality_section(v, STYLE,
                                            anchor_enabled=True,
                                            instruction_enabled=False)
        text = pool[(i - 1) % len(pool)]
        prompt = build_prompt(sec, text)
        try:
            raw = llm_infer(prompt)
        except Exception as e:
            rounds_log.append({"round": i, "input": text, "injected": sec,
                               "raw": None, "error": str(e)})
            print(f"[{gid}] [{i:3d}] ERR {e}", flush=True)
            continue
        # 提取【自然回复】与【风格自评】两节
        m = re.search(r"【自然回复】\s*([\s\S]*?)(?:【风格自评】|$)", raw)
        reply = m.group(1).strip() if m else raw.strip()
        ms = re.search(r"【风格自评】\s*([\s\S]*)$", raw)
        self_report = ms.group(1).strip() if ms else ""
        # 观测打分：回复文本 + 风格自评文本（自评保证每轮都有风格信号 → 每次都演化）
        score_text = (reply + " " + self_report).strip()
        obs = prs.estimate_style_from_reply({"自然回复": score_text})
        # 命中检测（自评必含风格词，预期每轮四维都命中）
        hit = {dim: any(kw in score_text for kw in prs._STYLE_KEYWORDS[dim]["high"])
               or any(kw in score_text for kw in prs._STYLE_KEYWORDS[dim]["low"])
               for dim in ("warmth", "playfulness", "directness", "curiosity")}
        rounds_log.append({"round": i, "input": text, "injected": sec,
                           "raw": raw, "reply": reply[:200],
                           "self_report": self_report, "obs": obs,
                           "hit": hit, "vector": dict(v)})
        # B2：累加演化 —— 仅真实命中（有信号）的维度驱动差距演化，
        # 回退 0.5（未命中）视为无观测，跳过，不再把向量机械拉向中值
        # 负反馈分支：negative → target = 1 - obs（背离观测风格）
        if accumulate:
            for dim in ("warmth", "playfulness", "directness", "curiosity"):
                if not hit[dim]:
                    continue
                target = (1.0 - obs[dim]) if feedback == "negative" else obs[dim]
                delta = (target - v[dim]) * 0.06
                delta = max(-0.02, min(0.02, delta))
                v[dim] = max(0.0, min(1.0, v[dim] + delta))
        if i % 20 == 0 or i == rounds:
            print(f"[{gid}] [{i:3d}/{rounds}] v={v} rss={time.time():.0f}", flush=True)
    return {"gid": gid, "accumulate": accumulate, "rounds": rounds,
            "seed": SEED_V, "final_vector": v, "log": rounds_log}


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "both"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    groups = []
    if target in ("B1", "both"):
        groups.append(("B1", False, POOL_NEGATIVE, "neutral"))
    if target in ("B2", "both"):
        groups.append(("B2", True, POOL_NEGATIVE, "neutral"))
    if target in ("B2NEG",):
        groups.append(("B2NEG", True, POOL_ACCUSE, "negative"))
    meta = {"target": target, "rounds": rounds, "seed": SEED_V,
            "model": "deepseek-v4-flash", "temperature": 0.7}
    with open(os.path.join(OUT_DIR, "_run_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    for gid, acc, pool, fb in groups:
        print(f"\n===== {gid}（accumulate={acc} feedback={fb}）{rounds} 轮 =====", flush=True)
        r = run_cond(gid, acc, rounds, pool=pool, feedback=fb)
        with open(os.path.join(OUT_DIR, f"condB_{gid}_rounds.json"), "w",
                  encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        # 观测轨迹简表
        with open(os.path.join(OUT_DIR, f"condB_{gid}_obs.json"), "w",
                  encoding="utf-8") as f:
            json.dump([{"round": e["round"],
                        "warmth": e.get("obs", {}).get("warmth"),
                        "playfulness": e.get("obs", {}).get("playfulness"),
                        "directness": e.get("obs", {}).get("directness"),
                        "curiosity": e.get("obs", {}).get("curiosity")}
                       for e in r["log"] if e.get("obs")], f, ensure_ascii=False, indent=1)
        print(f"[{gid}] final_vector={r['final_vector']}", flush=True)
    print(f"\nDONE → {OUT_DIR}")


if __name__ == "__main__":
    main()
