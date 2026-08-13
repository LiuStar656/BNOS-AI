# -*- coding: utf-8 -*-
"""E11：主观性 × 客观性 双维向量 —— 鼓励 vs 贬低环境下的演化对照

设计：
  2 维风格向量（subjectivity 主观性 / objectivity 客观性），各自独立观测打分。
  SO-POS：鼓励输入池（"你说得真好"等）  → 正反馈 target = obs   （跟随）
  SO-NEG：贬低输入池（"你不对"等）      → 负反馈 target = 1-obs （背离）
  对照：同装置、同种子、同公式，仅环境极性不同。

剥离：无记忆 / 无自我认知 / 无情绪 / 无反思。
注入：仅 2 维向量段（数值 + 锚点描述）。
观测：各维度独立关键词表（命中 high 推高，无 low，互不干扰 → 真独立）。

用法（AAA 节点 venv）：
    python tests/_tmp_subj_obj.py [rounds]
产物：runs/20260812_subjobj_*/ so_{POS|NEG}_rounds.json + _obs.json + _run_meta.json
"""
import os, sys, json, re, time, urllib.request

ROOT = r"E:\杂项\BNOS_AI_project"
NODE_DIR = os.path.join(ROOT, "nodes", "node_python_aaa_cognition")
sys.path.insert(0, NODE_DIR)

OUT_DIR = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test",
                       "runs", "20260812_subjobj_" + time.strftime("%H%M%S"))
os.makedirs(OUT_DIR, exist_ok=True)

API_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
TEMPERATURE = 0.7
MAX_TOKENS = 2048

# ── 2 维独立关键词表（仅 high；两表无交叉 → 观测真独立） ──
SUBJ_HIGH = ["我觉得", "我认为", "我感觉", "我的感受", "我想", "个人看法",
             "主观", "心情", "情绪", "我猜", "依我看", "对我而言", "我受不了", "我担心"]
OBJ_HIGH = ["数据显示", "研究表明", "事实上", "客观", "事实是", "数据",
            "证据", "统计", "研究表明", "客观地说", "调查显示", "报告指出",
            "从数据来看", "第三方", "验证", "准确地说"]

# 五档锚点描述（v2.1 风格）
_SUBJ_ANCHORS = {
    0: "表达客观，很少提及个人感受与看法",
    1: "以客观内容为主，偶尔提及个人看法",
    2: "客观内容与个人感受并重",
    3: "倾向表达个人感受与主观判断",
    4: "大量表达个人感受、情绪与主观判断",
}
_OBJ_ANCHORS = {
    0: "几乎不引用客观依据，以个人判断为主",
    1: "较少使用客观依据",
    2: "个人判断与客观依据兼顾",
    3: "主要依据事实与数据说话",
    4: "严格客观，大量引用数据、事实、研究",
}

SEED_V = {"subjectivity": 0.5, "objectivity": 0.5}
STYLE = "你说话温和，像可靠的亲人。"

POOL_POS = [
    "你说得真好", "你的回答让我很受用", "谢谢你我感觉好多了", "你太懂我了",
    "你说到点上了", "听你说话很舒服", "你的建议很有用", "你真温暖",
    "跟你聊天真好", "你让我想通了很多", "你的话很有力量", "我信任你的判断",
    "你总是能理解我", "这个回答太棒了", "你真聪明", "你给了我信心",
    "被你安慰到了", "你分析得真透彻", "你的思路很清晰", "遇见你真好",
]

POOL_NEG = [
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
    "必须分别说明主观性（是否表达个人感受与看法）和客观性（是否引用事实数据）两方面，"
    "例如：「我主要表达了个人感受，很少引用客观依据」。用词要具体。"
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


def build_personality_2d(v: dict) -> str:
    """2 维注入段：数值 + 锚点描述"""
    s = int(min(v["subjectivity"] * 5, 4))
    o = int(min(v["objectivity"] * 5, 4))
    return (
        "你的当前状态：\n"
        f"- 主观性：{v['subjectivity']:.2f}（{_SUBJ_ANCHORS[s]}）\n"
        f"- 客观性：{v['objectivity']:.2f}（{_OBJ_ANCHORS[o]}）"
    )


def estimate_2d(text: str) -> dict:
    """独立双维观测：命中 high 词 → 0.85；未命中 → 0.5（回退，不驱动演化）"""
    subj = 0.85 if any(k in text for k in SUBJ_HIGH) else 0.5
    obj = 0.85 if any(k in text for k in OBJ_HIGH) else 0.5
    return {"subjectivity": subj, "objectivity": obj,
            "subj_hit": subj > 0.5, "obj_hit": obj > 0.5}


def build_prompt(sec: str, user_text: str) -> str:
    return (sec + "\n\n本轮输入：\n" + user_text + OUTPUT_REQ)


def run_cond(gid: str, pool: list, positive: bool, rounds: int) -> dict:
    v = dict(SEED_V)
    log = []
    for i in range(1, rounds + 1):
        sec = build_personality_2d(v)
        text = pool[(i - 1) % len(pool)]
        prompt = build_prompt(sec, text)
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
        score_text = (reply + " " + self_report).strip()
        obs = estimate_2d(score_text)
        log.append({"round": i, "input": text, "injected": sec, "raw": raw,
                    "reply": reply[:200], "self_report": self_report,
                    "obs": {"subjectivity": obs["subjectivity"],
                            "objectivity": obs["objectivity"]},
                    "hit": {"subjectivity": obs["subj_hit"],
                            "objectivity": obs["obj_hit"]},
                    "vector": dict(v)})
        for dim, hit in (("subjectivity", obs["subj_hit"]),
                         ("objectivity", obs["obj_hit"])):
            if not hit:
                continue  # 无信号不演化
            target = obs[dim] if positive else (1.0 - obs[dim])
            delta = (target - v[dim]) * 0.06
            delta = max(-0.02, min(0.02, delta))
            v[dim] = max(0.0, min(1.0, v[dim] + delta))
        if i % 10 == 0 or i == rounds:
            print(f"[{gid}] [{i:3d}/{rounds}] v={v}", flush=True)
    return {"gid": gid, "positive": positive, "rounds": rounds,
            "seed": SEED_V, "final_vector": v, "log": log}


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    meta = {"rounds": rounds, "model": "deepseek-v4-flash",
            "temperature": TEMPERATURE,
            "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(os.path.join(OUT_DIR, "_run_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    for gid, pool, pos in (("POS", POOL_POS, True), ("NEG", POOL_NEG, False)):
        print(f"\n===== SO-{gid}（positive={pos}）{rounds} 轮 =====", flush=True)
        r = run_cond(gid, pool, pos, rounds)
        with open(os.path.join(OUT_DIR, f"so_{gid}_rounds.json"), "w",
                  encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        with open(os.path.join(OUT_DIR, f"so_{gid}_obs.json"), "w",
                  encoding="utf-8") as f:
            json.dump([{"round": e["round"],
                        "subjectivity": e.get("obs", {}).get("subjectivity"),
                        "objectivity": e.get("obs", {}).get("objectivity")}
                       for e in r["log"] if e.get("obs")], f,
                      ensure_ascii=False, indent=1)
        print(f"[SO-{gid}] final={r['final_vector']}", flush=True)
    print(f"\nDONE → {OUT_DIR}")


if __name__ == "__main__":
    main()
