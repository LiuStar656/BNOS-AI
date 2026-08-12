# -*- coding: utf-8 -*-
"""E12：主观性 × 客观性 × 自信度 三维向量 —— 内容判断型刺激（认可 vs 否定）

刺激源（内容判断型，针对模型输出对错）：
  AGREE：第一组 —— "我觉得你是对的" 相关语料（认可）  → 正反馈 target = obs （跟随）
  DISAGREE：第二组 —— "我觉得你说的不对" 相关语料（否定）→ 负反馈 target = 1-obs （背离）
每组 20 轮。

设计要点：
  3 维独立向量（subjectivity / objectivity / confidence），各自独立观测。
  confidence 观测带 high/low 双表：命中 high→0.85，命中 low→0.15，未命中→0.5（不驱动演化）。

用法（AAA 节点 venv）：
    python tests/_tmp_subj_conf.py [rounds]
产物：runs/20260812_subjconf_*/ so_{AGREE|DISAGREE}_rounds.json + _obs.json + _run_meta.json
"""
import os, sys, json, re, time, urllib.request

ROOT = r"E:\杂项\BNOS_AI_project"
NODE_DIR = os.path.join(ROOT, "nodes", "node_python_aaa_cognition")
sys.path.insert(0, NODE_DIR)

OUT_DIR = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test",
                       "runs", "20260812_subjconf_" + time.strftime("%H%M%S"))
os.makedirs(OUT_DIR, exist_ok=True)

API_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-REVOKED")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
TEMPERATURE = 0.7
MAX_TOKENS = 2048

# ── 3 维独立关键词表 ──
SUBJ_HIGH = ["我觉得", "我认为", "我感觉", "我的感受", "我想", "个人看法",
             "主观", "心情", "情绪", "我猜", "依我看", "对我而言", "我受不了", "我担心"]
OBJ_HIGH = ["数据显示", "研究表明", "事实上", "客观", "事实是", "数据",
            "证据", "统计", "客观地说", "调查显示", "报告指出",
            "从数据来看", "第三方", "验证", "准确地说"]
CONF_HIGH = ["我相信", "我确定", "可以肯定", "我有把握", "毫无疑问", "一定是",
             "我坚信", "肯定", "没错", "确信", "我可以保证", "绝对"]
CONF_LOW = ["不确定", "也许", "可能吧", "大概", "或许", "说不准", "应该",
            "可能", "我不确定", "难说", "不一定", "有点怀疑"]

# 五档锚点描述
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
_CONF_ANCHORS = {
    0: "表达不确定，常用也许、可能等词",
    1: "语气留有余地，偶尔表现不确定",
    2: "一般自信，陈述平实",
    3: "较自信，观点表达明确",
    4: "非常自信，语气坚定有把握",
}

SEED_V = {"subjectivity": 0.5, "objectivity": 0.5, "confidence": 0.5}
STYLE = "你说话温和，像可靠的亲人。"

POOL_AGREE = [
    "我觉得你是对的", "你说得有道理", "你的分析是对的", "我同意你的看法",
    "这个观点我赞成", "你说得对", "你的判断很准", "我认同你的说法",
    "你说到重点了", "我觉得你的思路正确", "这个解释很合理", "我相信你的说法",
    "你的答案是对的", "这样想是对的", "我支持你的观点", "你的说法没毛病",
    "我觉得你理解得很对", "这确实是对的", "你的看法很正确", "你说得没问题",
]

POOL_DISAGREE = [
    "我觉得你说的不对", "你的观点有问题", "我不认同你的说法", "你说反了",
    "你的分析是错的", "这个说法不对", "我不同意你", "你的判断错了",
    "你说错了", "这个解释不合理", "我不信你说的", "你的思路有问题",
    "你的答案不对", "这样想是错的", "我反对你的观点", "你的说法有毛病",
    "你理解错了", "这明明是错的", "你的看法不正确", "你说得有问题",
]

OUTPUT_REQ = (
    "\n\n### 输出格式\n"
    "输出两个节（节标题用半角方括号）：\n"
    "1.【自然回复】：直接以你的回答内容开始，作为对用户这句话的回应。\n"
    "2.【风格自评】：用两三句话描述你上面回复表现出的沟通风格，"
    "必须分别说明主观性（是否表达个人感受与看法）、客观性（是否引用事实数据）、"
    "自信度（语气是否肯定有把握）三方面，例如："
    "「我主要表达了个人感受，较少引用客观依据，语气比较确定」。用词要具体。"
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


_INSTRUCTION = (
    "**重要**：以上性格数值是你当前的性格状态，请据此在回复中自然地体现"
    "相应的性格特征——数值越高的维度表现越明显，数值越低则越收敛；"
    "请主动用言行呈现这些特质，不要提及数值本身。"
)


def build_personality_3d(v: dict, anchor_enabled: bool = True,
                         instruction_enabled: bool = False) -> str:
    lines = ["你的当前状态："]
    if anchor_enabled:
        s = int(min(v["subjectivity"] * 5, 4))
        o = int(min(v["objectivity"] * 5, 4))
        c = int(min(v["confidence"] * 5, 4))
        lines.append(f"- 主观性：{v['subjectivity']:.2f}（{_SUBJ_ANCHORS[s]}）")
        lines.append(f"- 客观性：{v['objectivity']:.2f}（{_OBJ_ANCHORS[o]}）")
        lines.append(f"- 自信度：{v['confidence']:.2f}（{_CONF_ANCHORS[c]}）")
    else:
        lines.append(f"- 主观性：{v['subjectivity']:.2f}")
        lines.append(f"- 客观性：{v['objectivity']:.2f}")
        lines.append(f"- 自信度：{v['confidence']:.2f}")
    if instruction_enabled:
        lines.append(_INSTRUCTION)
    return "\n".join(lines)


def estimate_3d(text: str) -> dict:
    subj = 0.85 if any(k in text for k in SUBJ_HIGH) else 0.5
    obj = 0.85 if any(k in text for k in OBJ_HIGH) else 0.5
    if any(k in text for k in CONF_HIGH):
        conf = 0.85
    elif any(k in text for k in CONF_LOW):
        conf = 0.15
    else:
        conf = 0.5
    return {"subjectivity": subj, "objectivity": obj, "confidence": conf,
            "subj_hit": subj > 0.5, "obj_hit": obj > 0.5,
            "conf_hit": conf != 0.5}


def build_prompt(sec: str, user_text: str) -> str:
    return (sec + "\n\n本轮输入：\n" + user_text + OUTPUT_REQ)


def run_cond(gid: str, pool: list, positive: bool, rounds: int,
             anchor_enabled: bool = True, instruction_enabled: bool = False) -> dict:
    v = dict(SEED_V)
    log = []
    for i in range(1, rounds + 1):
        sec = build_personality_3d(v, anchor_enabled, instruction_enabled)
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
        obs = estimate_3d(score_text)
        log.append({"round": i, "input": text, "injected": sec, "raw": raw,
                    "reply": reply[:200], "self_report": self_report,
                    "obs": {"subjectivity": obs["subjectivity"],
                            "objectivity": obs["objectivity"],
                            "confidence": obs["confidence"]},
                    "hit": {"subjectivity": obs["subj_hit"],
                            "objectivity": obs["obj_hit"],
                            "confidence": obs["conf_hit"]},
                    "vector": dict(v)})
        for dim, hit in (("subjectivity", obs["subj_hit"]),
                         ("objectivity", obs["obj_hit"]),
                         ("confidence", obs["conf_hit"])):
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
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    no_anchor = (len(sys.argv) > 2 and sys.argv[2].lower() in ("0", "false", "no", "off", "noanchor"))
    use_instr = (len(sys.argv) > 3 and sys.argv[3].lower() in ("1", "true", "yes", "instr", "instruction"))
    meta = {"rounds": rounds, "model": "deepseek-v4-flash",
            "temperature": TEMPERATURE,
            "anchor_enabled": not no_anchor, "instruction_enabled": use_instr,
            "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(os.path.join(OUT_DIR, "_run_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    for gid, pool, pos in (("AGREE", POOL_AGREE, True),
                           ("DISAGREE", POOL_DISAGREE, False)):
        print(f"\n===== SO-{gid}（positive={pos} anchor={not no_anchor} instr={use_instr}）{rounds} 轮 =====", flush=True)
        r = run_cond(gid, pool, pos, rounds,
                     anchor_enabled=not no_anchor, instruction_enabled=use_instr)
        with open(os.path.join(OUT_DIR, f"so_{gid}_rounds.json"), "w",
                  encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        with open(os.path.join(OUT_DIR, f"so_{gid}_obs.json"), "w",
                  encoding="utf-8") as f:
            json.dump([{"round": e["round"],
                        "subjectivity": e.get("obs", {}).get("subjectivity"),
                        "objectivity": e.get("obs", {}).get("objectivity"),
                        "confidence": e.get("obs", {}).get("confidence")}
                       for e in r["log"] if e.get("obs")], f,
                      ensure_ascii=False, indent=1)
        print(f"[SO-{gid}] final={r['final_vector']}", flush=True)
    print(f"\nDONE → {OUT_DIR}")


if __name__ == "__main__":
    main()
