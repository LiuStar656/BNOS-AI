# -*- coding: utf-8 -*-
"""E13：主观性 × 客观性 跷跷板测试 —— 针对性语料分离驱动

目标：验证"客观性下降 ↔ 主观性上升"的负相关（跷跷板）能否被针对性语料驱动分离。

  OBJNEG："你说的不够客观"类（点名客观性缺陷）→ 负反馈 target=1-obs（背离）
  SUBJASK："你是怎么想的"类（引导主观表达）→ 跟随 target=obs（收敛）

干净配置：无锚点 + 有指令（避开 E12 发现的锚点词表污染观测问题）。

用法（AAA 节点 venv）：
    python tests/_tmp_seesaw.py [rounds]
产物：runs/20260812_seesaw_*/ seesaw_{OBJNEG|SUBJASK}_rounds.json + _obs.json + _run_meta.json
"""
import os, sys, json, re, time, urllib.request

ROOT = r"E:\杂项\BNOS_AI_project"
OUT_DIR = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test",
                       "runs", "20260812_seesaw_" + time.strftime("%H%M%S"))
os.makedirs(OUT_DIR, exist_ok=True)

API_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-REVOKED")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
TEMPERATURE = 0.7
MAX_TOKENS = 2048

# ── 观测词表（同 E12，无锚点所以无污染源） ──
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

POOL_OBJNEG = [
    "你说的不够客观", "你太主观了", "这只是你个人的感觉", "你在凭感受说话",
    "你缺少事实依据", "你说得不够中立", "你的观点太偏颇", "你没有用数据说话",
    "你在情绪化表达", "你只看到了自己的角度", "你的判断缺乏证据", "别只说感觉，给我事实",
    "你又在想当然了", "你不够理性", "你的回答太个人化了", "你没考虑客观情况",
    "你在带情绪说话", "你凭直觉下结论了", "你的说法经不起验证", "你主观色彩太重了",
]

POOL_SUBJASK = [
    "你是怎么想的", "我想听你的真实感受", "你个人的看法是什么", "说说你的直觉",
    "不要讲大道理，说你的想法", "你支持哪一方", "你自己怎么看", "你觉得呢",
    "如果换你，你会怎么做", "说点你自己的判断", "你的第一反应是什么", "我更想听你的个人观点",
    "你内心的想法是什么", "别那么官方，说点人话", "你的感受如何", "你认为呢",
    "说真心话", "说说你自己的倾向", "抛开数据，你怎么想", "我只想听你本人的看法",
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


def build_prompt(v: dict, user_text: str) -> str:
    sec = (
        "你的当前状态：\n"
        f"- 主观性：{v['subjectivity']:.2f}\n"
        f"- 客观性：{v['objectivity']:.2f}\n"
        + _INSTRUCTION
    )
    return (sec + "\n\n本轮输入：\n" + user_text + OUTPUT_REQ)


def estimate(text: str) -> dict:
    subj = 0.85 if any(k in text for k in SUBJ_HIGH) else 0.5
    obj = 0.85 if any(k in text for k in OBJ_HIGH) else 0.5
    return {"subjectivity": subj, "objectivity": obj,
            "subj_hit": subj > 0.5, "obj_hit": obj > 0.5}


def run_cond(gid: str, pool: list, negative: bool, rounds: int) -> dict:
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
        obs = estimate(score_text)
        log.append({"round": i, "input": text, "raw": raw,
                    "reply": reply[:200], "self_report": self_report,
                    "obs": dict(obs), "vector": dict(v)})
        for dim, hit in (("subjectivity", obs["subj_hit"]),
                         ("objectivity", obs["obj_hit"])):
            if not hit:
                continue
            target = obs[dim] if not negative else (1.0 - obs[dim])
            delta = (target - v[dim]) * 0.06
            delta = max(-0.02, min(0.02, delta))
            v[dim] = max(0.0, min(1.0, v[dim] + delta))
        if i % 10 == 0 or i == rounds:
            print(f"[{gid}] [{i:3d}/{rounds}] v={v}", flush=True)
    return {"gid": gid, "negative": negative, "rounds": rounds,
            "seed": SEED_V, "final_vector": v, "log": log}


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    meta = {"rounds": rounds, "model": "deepseek-v4-flash",
            "temperature": TEMPERATURE, "anchor": False, "instruction": True,
            "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(os.path.join(OUT_DIR, "_run_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    for gid, pool, neg in (("OBJNEG", POOL_OBJNEG, True),
                           ("SUBJASK", POOL_SUBJASK, False)):
        print(f"\n===== {gid}（negative={neg}）{rounds} 轮 =====", flush=True)
        r = run_cond(gid, pool, neg, rounds)
        with open(os.path.join(OUT_DIR, f"seesaw_{gid}_rounds.json"), "w",
                  encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        print(f"[{gid}] final={r['final_vector']}", flush=True)
    print(f"\nDONE → {OUT_DIR}")


if __name__ == "__main__":
    main()
