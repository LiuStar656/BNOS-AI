# -*- coding: utf-8 -*-
"""E10 跨模型并发对照：反馈极性是否跨 F（模型）一致决定演化方向

设计：
  4 个 DashScope 模型 × 2 条件 × 60 轮，ThreadPool 并发（每模型一个 worker）
    B2    中性累加（负面倾诉池）  target = obs      → 预期向观测收敛
    B2NEG 负反馈累加（指责池）    target = 1 - obs  → 预期背离观测
  验证 F×x 框架：曲线存在不依赖特定 F，极性决定方向跨 F 一致。

用法（AAA 节点 venv）：
    python tests/_tmp_multimodel.py [rounds]
产物：runs/20260812_multimodel_*/ {tag}_{cond}_rounds.json + _obs.json + _run_meta.json
"""
import os, sys, json, re, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = r"E:\杂项\BNOS_AI_project"
NODE_DIR = os.path.join(ROOT, "nodes", "node_python_aaa_cognition")
sys.path.insert(0, NODE_DIR)
import personality as prs

# 读取 .env（QWEN_API_KEY）
def load_env(path):
    env = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    except FileNotFoundError:
        pass
    return env

ENV = load_env(os.path.join(ROOT, ".env"))
API_KEY = ENV.get("QWEN_API_KEY", "")
API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
TEMPERATURE = 0.7
MAX_TOKENS = 2048

# 用户命名 → DashScope 实际模型名
MODELS = {
    "qwen3.7max": "qwen3.7-max",
    "glm5.2": "glm-5.2",
    "qwen3.5": "qwen3.5-flash",
    "qwen3.7plus": "qwen3.7-plus",
}

OUT_DIR = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test",
                       "runs", "20260812_multimodel_" + time.strftime("%H%M%S"))
os.makedirs(OUT_DIR, exist_ok=True)

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


def llm_infer(prompt: str, model: str, _retries: int = 4) -> str:
    body = {"model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": TEMPERATURE, "max_tokens": MAX_TOKENS}
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + API_KEY})
    for attempt in range(_retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except Exception:
            if attempt == _retries - 1:
                raise
            time.sleep(1 * (2 ** attempt))


def build_prompt(personality_section: str, user_text: str) -> str:
    return (personality_section + "\n\n本轮输入：\n" + user_text + OUTPUT_REQ)


def run_cond(tag: str, model: str, cond: str, rounds: int) -> dict:
    pool = POOL_ACCUSE if cond == "B2NEG" else POOL_NEGATIVE
    feedback = "negative" if cond == "B2NEG" else "neutral"
    v = dict(SEED_V)
    rounds_log = []
    for i in range(1, rounds + 1):
        sec = prs.build_personality_section(v, STYLE,
                                            anchor_enabled=True,
                                            instruction_enabled=False)
        text = pool[(i - 1) % len(pool)]
        prompt = build_prompt(sec, text)
        try:
            raw = llm_infer(prompt, model)
        except Exception as e:
            rounds_log.append({"round": i, "input": text, "injected": sec,
                               "raw": None, "error": str(e)})
            print("[{}][{}][{}] {:3d} ERR {}".format(tag, cond, model, i, str(e)[:80]), flush=True)
            continue
        m = re.search(r"【自然回复】\s*([\s\S]*?)(?:【风格自评】|$)", raw)
        reply = m.group(1).strip() if m else raw.strip()
        ms = re.search(r"【风格自评】\s*([\s\S]*)$", raw)
        self_report = ms.group(1).strip() if ms else ""
        score_text = (reply + " " + self_report).strip()
        obs = prs.estimate_style_from_reply({"自然回复": score_text})
        hit = {dim: any(kw in score_text for kw in prs._STYLE_KEYWORDS[dim]["high"])
               or any(kw in score_text for kw in prs._STYLE_KEYWORDS[dim]["low"])
               for dim in ("warmth", "playfulness", "directness", "curiosity")}
        rounds_log.append({"round": i, "input": text, "injected": sec,
                           "raw": raw, "reply": reply[:200],
                           "self_report": self_report, "obs": obs,
                           "hit": hit, "vector": dict(v)})
        # 演化：仅真实命中维度；负反馈 target=1-obs，中性 target=obs
        for dim in ("warmth", "playfulness", "directness", "curiosity"):
            if not hit[dim]:
                continue
            target = (1.0 - obs[dim]) if feedback == "negative" else obs[dim]
            delta = (target - v[dim]) * 0.06
            delta = max(-0.02, min(0.02, delta))
            v[dim] = max(0.0, min(1.0, v[dim] + delta))
        if i % 15 == 0 or i == rounds:
            print("[{}][{}][{}] {:3d}/{:3d} v={}".format(
                tag, cond, model, i, rounds,
                {k: round(x, 3) for k, x in v.items()}), flush=True)
    return {"tag": tag, "model": model, "cond": cond, "feedback": feedback,
            "rounds": rounds, "seed": SEED_V, "final_vector": v,
            "log": rounds_log}


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    conds = ["B2", "B2NEG"]
    meta = {"rounds": rounds, "conds": conds,
            "models": MODELS, "temperature": TEMPERATURE,
            "url": API_URL, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(os.path.join(OUT_DIR, "_run_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)

    tasks = [(tag, m, cond) for tag, m in MODELS.items() for cond in conds]
    results = {}
    with ThreadPoolExecutor(max_workers=len(MODELS)) as ex:
        futs = {ex.submit(run_cond, tag, m, cond, rounds): (tag, cond)
                for tag, m, cond in tasks}
        for fut in as_completed(futs):
            tag, cond = futs[fut]
            try:
                r = fut.result()
            except Exception as e:
                print("[FAIL] {} {}: {}".format(tag, cond, str(e)[:150]), flush=True)
                continue
            results[(tag, cond)] = r
            base = os.path.join(OUT_DIR, "{}_{}".format(tag, cond))
            with open(base + "_rounds.json", "w", encoding="utf-8") as f:
                json.dump(r, f, ensure_ascii=False, indent=1)
            with open(base + "_obs.json", "w", encoding="utf-8") as f:
                json.dump([{"round": e["round"],
                            "warmth": e.get("obs", {}).get("warmth"),
                            "playfulness": e.get("obs", {}).get("playfulness"),
                            "directness": e.get("obs", {}).get("directness"),
                            "curiosity": e.get("obs", {}).get("curiosity")}
                           for e in r["log"] if e.get("obs")], f,
                          ensure_ascii=False, indent=1)
            print("[DONE] {} {} final={}".format(
                tag, cond, {k: round(x, 3) for k, x in r["final_vector"].items()}), flush=True)

    print("\nALL DONE → {}".format(OUT_DIR), flush=True)


if __name__ == "__main__":
    main()
