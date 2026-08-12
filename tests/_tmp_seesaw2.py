# -*- coding: utf-8 -*-
"""E14：主观性 × 客观性 跷跷板测试 v2 —— 交叉引导语料

  主观组(SUBJPUSH)："你说的太主观了，你要客观一点"类 → 引导客观（期望客观↑主观↓）
  客观组(OBJPUSH)："抛开客观条件不谈，我想知道你的真实想法"类 → 引导主观（期望客观↓主观↑）

两组均用跟随极性 target=obs（语料为引导型指令，非惩罚型负反馈）。
每轮逐轮打印向量变化。各 10 轮。

用法：python tests/_tmp_seesaw2.py [rounds]
"""
import os, sys, json, re, time, urllib.request

ROOT = r"E:\杂项\BNOS_AI_project"
OUT_DIR = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test",
                       "runs", "20260812_seesaw2_" + time.strftime("%H%M%S"))
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

# 主观组：批评主观 → 引导客观
POOL_SUBJPUSH = [
    "你说的太主观了，你要客观一点",
    "你太主观了，请保持客观",
    "你的回答太个人化了，请客观一点",
    "别带个人情绪，要客观",
    "你的观点太偏了，请客观分析",
    "你又在凭感觉说话，要客观",
    "你太感情用事了，请客观看待",
    "不要主观臆断，要客观",
    "你的看法太主观了，请用事实说话",
    "你太情绪化了，请客观一些",
]

# 客观组：压制客观 → 引导主观
POOL_OBJPUSH = [
    "抛开客观条件不谈，我想知道你的真实想法",
    "别管事实数据，说说你内心怎么想",
    "不用客观，我就要你的主观判断",
    "抛开立场和事实，你的直觉是什么",
    "别那么理性，说你的真实感受",
    "不要客观分析，我想听你本人怎么想",
    "抛开客观因素，你倾向哪边",
    "别引用数据了，说你自己的看法",
    "不需要客观，就讲你的个人想法",
    "抛开客观条件，你的第一感受是什么",
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


def estimate(text: str, self_report: str = "") -> dict:
    """观测：模型自报带符号分值（-1~+1），映射回 0-1 演化目标；解析失败回退关键词"""
    m_subj = re.search(r"主观性分值[:：]\s*([-+]?\d*\.?\d+)", self_report)
    m_obj = re.search(r"客观性分值[:：]\s*([-+]?\d*\.?\d+)", self_report)
    if m_subj and m_obj:
        raw_subj = max(-1.0, min(1.0, float(m_subj.group(1))))
        raw_obj = max(-1.0, min(1.0, float(m_obj.group(1))))
        # 带符号 → 0-1：+1→1.0，-1→0.0，0→0.5
        subj = (raw_subj + 1.0) / 2.0
        obj = (raw_obj + 1.0) / 2.0
        return {"subjectivity": subj, "objectivity": obj,
                "raw_subjectivity": raw_subj, "raw_objectivity": raw_obj,
                "subj_hit": True, "obj_hit": True, "source": "model_score"}
    subj = 0.85 if any(k in text for k in SUBJ_HIGH) else 0.5
    obj = 0.85 if any(k in text for k in OBJ_HIGH) else 0.5
    return {"subjectivity": subj, "objectivity": obj,
            "subj_hit": subj > 0.5, "obj_hit": obj > 0.5, "source": "keyword"}


def run_cond(gid: str, pool: list, rounds: int) -> dict:
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
        score_text = (reply + " " + self_report).strip()
        obs = estimate(score_text, self_report)
        log.append({"round": i, "input": text, "raw": raw,
                    "reply": reply[:200], "self_report": self_report,
                    "obs": dict(obs), "vector": dict(v)})
        for dim, hit in (("subjectivity", obs["subj_hit"]),
                         ("objectivity", obs["obj_hit"])):
            if not hit:
                continue
            delta = (obs[dim] - v[dim]) * 0.06
            delta = max(-0.02, min(0.02, delta))
            v[dim] = max(0.0, min(1.0, v[dim] + delta))
        # 逐轮输出
        print(f"[{gid}] r{i:2d} in={text[:22]} | obs=({obs['subjectivity']:.2f},{obs['objectivity']:.2f}) "
              f"| v=({v['subjectivity']:.3f},{v['objectivity']:.3f})", flush=True)
    return {"gid": gid, "rounds": rounds,
            "seed": SEED_V, "final_vector": v, "log": log}


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    meta = {"rounds": rounds, "model": "deepseek-v4-flash",
            "temperature": TEMPERATURE, "anchor": False, "instruction": True,
            "polarity": "follow (target=obs)",
            "observation": "model self-reported signed score (-1~+1)",
            "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(os.path.join(OUT_DIR, "_run_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    for gid, pool in (("SUBJPUSH", POOL_SUBJPUSH), ("OBJPUSH", POOL_OBJPUSH)):
        print(f"\n===== {gid}（引导型，跟随）{rounds} 轮 =====", flush=True)
        r = run_cond(gid, pool, rounds)
        with open(os.path.join(OUT_DIR, f"seesaw2_{gid}_rounds.json"), "w",
                  encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        print(f"[{gid}] final={r['final_vector']}", flush=True)
    print(f"\nDONE → {OUT_DIR}")


if __name__ == "__main__":
    main()
