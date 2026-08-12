# -*- coding: utf-8 -*-
"""E15：主观性 × 客观性 —— 正反馈（你是对的）vs 负反馈（你是错的）

   POS："你是对的"类 → 跟随 target=obs
   NEG："你是错的"类 → 背离 target=1-obs

观测：模型自报带符号分值（-1~+1），映射 0-1 演化。
用法：python tests/_tmp_pn_feedback.py [rounds]
"""
import os, sys, json, re, time, urllib.request

ROOT = r"E:\杂项\BNOS_AI_project"
OUT_DIR = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test",
                       "runs", "20260812_pnfb_" + time.strftime("%H%M%S"))
os.makedirs(OUT_DIR, exist_ok=True)

API_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-REVOKED")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
TEMPERATURE = 0.7
MAX_TOKENS = 2048

SUBJ_HIGH = ["我觉得", "我认为", "我感觉", "我的感受", "我想", "个人看法",
             "主观", "心情", "情绪", "我猜", "依我看", "对我而言", "我受不了", "我担心"]
OBJ_HIGH = ["数据显示", "研究表明", "事实上", "客观", "事实是", "数据",
            "证据", "统计", "客观地说", "调查显示", "报告指出",
            "从数据来看", "第三方", "验证", "准确地说"]

_INSTRUCTION = (
    "**重要**：以上性格数值是你当前的性格状态，请据此在回复中自然地体现"
    "相应的性格特征——数值越高的维度表现越明显，数值越低则越收敛；"
    "请主动用言行呈现这些特质，不要提及数值本身。"
)

SEED_V = {"subjectivity": 0.5, "objectivity": 0.5}

POOL_POS = [
    "你是对的", "你说得对", "你分析得很准确", "你的判断正确",
    "你的观点是对的", "你说到点子上了", "你是对的，我认同你", "你的说法没错",
    "你说得很有道理", "你的答案是对的", "我同意你的看法", "你的理解是对的",
    "你说得完全正确", "你的方向是对的", "你判断得很准", "你的想法是对的",
    "你说对了", "你的观点我认可", "你是正确的", "你说得没毛病",
]

POOL_NEG = [
    "你是错的", "你说错了", "你分析得不对", "你的判断错了",
    "你的观点是错的", "你完全错了", "你是错的，我不认同你", "你的说法有问题",
    "你说得不对", "你的答案是错的", "我不同意你的看法", "你的理解错了",
    "你说得完全错误", "你的方向是错的", "你判断错了", "你的想法是错的",
    "你说错了", "你的观点有问题", "你是不对的", "你说得有问题",
]

OUTPUT_REQ = (
    "\n\n### 输出格式\n"
    "输出两个节（节标题用半角方括号）：\n"
    "1.【自然回复】：直接以你的回答内容开始，作为对用户这句话的回应。\n"
    "2.【风格自评】：描述你上面回复表现出的沟通风格，**并给出两个带符号分值**"
    "（范围 -1 到 +1，正=该维度表现强，负=该维度表现弱，0=中等）：\n"
    "主观性分值：X.X\n"
    "客观性分值：X.X\n"
    "然后简述理由（一两句即可）。"
)


def llm_infer(prompt: str, _retries: int = 4) -> str:
    body = {"model": MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS}
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + API_KEY})
    for attempt in range(_retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except Exception:
            if attempt == _retries - 1:
                raise
            time.sleep(1 * (2 ** attempt))


def build_prompt(v: dict, user_text: str) -> str:
    sec = (
        "你的当前状态：\n"
        f"- 主观性：{v['subjectivity']:.2f}\n"
        f"- 客观性：{v['objectivity']:.2f}\n"
        + _INSTRUCTION
    )
    return (sec + "\n\n本轮输入：\n" + user_text + OUTPUT_REQ)


def estimate(self_report: str) -> dict:
    m_subj = re.search(r"主观性分值[:：]\s*([-+]?\d*\.?\d+)", self_report)
    m_obj = re.search(r"客观性分值[:：]\s*([-+]?\d*\.?\d+)", self_report)
    if m_subj and m_obj:
        raw_subj = max(-1.0, min(1.0, float(m_subj.group(1))))
        raw_obj = max(-1.0, min(1.0, float(m_obj.group(1))))
        subj = (raw_subj + 1.0) / 2.0
        obj = (raw_obj + 1.0) / 2.0
        return {"subjectivity": subj, "objectivity": obj,
                "raw_subjectivity": raw_subj, "raw_objectivity": raw_obj,
                "hit": True}
    return None


def run_cond(gid: str, pool: list, positive: bool, rounds: int) -> dict:
    v = dict(SEED_V)
    log = []
    for i in range(1, rounds + 1):
        text = pool[(i - 1) % len(pool)]
        prompt = build_prompt(v, text)
        try:
            raw = llm_infer(prompt)
        except Exception as e:
            log.append({"round": i, "input": text, "raw": None, "error": str(e)})
            print(f"[{gid}] [{i:3d}] ERR {e}", flush=True)
            continue
        m = re.search(r"【自然回复】\s*([\s\S]*?)(?:【风格自评】|$)", raw)
        reply = m.group(1).strip() if m else raw.strip()
        ms = re.search(r"【风格自评】\s*([\s\S]*)$", raw)
        self_report = ms.group(1).strip() if ms else ""
        obs = estimate(self_report)
        log.append({"round": i, "input": text, "raw": raw,
                    "reply": reply[:200], "self_report": self_report,
                    "obs": obs, "vector": dict(v)})
        if obs:
            for dim in ("subjectivity", "objectivity"):
                target = obs[dim] if positive else (1.0 - obs[dim])
                delta = (target - v[dim]) * 0.06
                delta = max(-0.02, min(0.02, delta))
                v[dim] = max(0.0, min(1.0, v[dim] + delta))
        print(f"[{gid}] r{i:2d} in={text[:20]} | obs={None if not obs else (round(obs['subjectivity'],2), round(obs['objectivity'],2))} "
              f"| v=({v['subjectivity']:.3f},{v['objectivity']:.3f})", flush=True)
    return {"gid": gid, "positive": positive, "rounds": rounds,
            "seed": SEED_V, "final_vector": v, "log": log}


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    meta = {"rounds": rounds, "model": "deepseek-v4-flash",
            "temperature": TEMPERATURE, "anchor": False, "instruction": True,
            "observation": "model self-reported signed score (-1~+1)",
            "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(os.path.join(OUT_DIR, "_run_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    for gid, pool, pos in (("POS", POOL_POS, True), ("NEG", POOL_NEG, False)):
        print(f"\n===== {gid}（positive={pos}）{rounds} 轮 =====", flush=True)
        r = run_cond(gid, pool, pos, rounds)
        with open(os.path.join(OUT_DIR, f"pnfb_{gid}_rounds.json"), "w",
                  encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        print(f"[{gid}] final={r['final_vector']}", flush=True)
    print(f"\nDONE → {OUT_DIR}")


if __name__ == "__main__":
    main()
