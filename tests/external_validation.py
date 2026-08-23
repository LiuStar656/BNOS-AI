# -*- coding: utf-8 -*-
"""外部效标验证实验：规则化观测投影 vs 独立 LLM 裁判评分

回应：华东师大《大语言模型人格的测量》指出的"自陈分数与外部行为判断脱节"、
"语言线索法信效度证据不足"——验证本文观测函数（关键词统计投影）与
独立裁判（LLM 语义判断，无装置信息）对同一批输出的评分一致性。

设计：
- 样本：3 模型 × 2 条件（B2/B2NEG）× 4 代表轮次（初始/1/4/1/2/终态）= 24 条回复
- 裁判：DeepSeek，只输入【回复文本】，按四维（warmth/playfulness/directness/curiosity）
  输出 0-1 连续分（JSON）
- 对比指标：
  1) 逐维 Spearman 相关：观测投影 obs vs 裁判分
  2) 方向一致性：B2 vs B2NEG 的 warmth/directness 差异方向，裁判分应复现
  3) 跨模型一致性

用法（AAA 节点 venv）：
  python tests/external_validation.py

留档：docs/experiments/cognitive_evolution_test/runs/YYYYMMDD_HHMMSS_extval/
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from collections import OrderedDict

API_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
TEMPERATURE = 0.0  # 裁判打分希望稳定，低温
MAX_TOKENS = 512

ROOT = r"E:\杂项\BNOS_AI_project"
RUNS = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test", "runs")
DIMS = ["warmth", "playfulness", "directness", "curiosity"]

if not API_KEY:
    # 兜底：从 LLM 节点 local_config.json 读取（不提交的本地配置）
    try:
        import sys as _sys
        _cfg_path = os.path.join(ROOT, "nodes", "node_python_llm_infer", "local_config.json")
        if os.path.exists(_cfg_path):
            _local = json.load(open(_cfg_path, encoding="utf-8"))
            API_KEY = (_local.get("api_key") or "").strip()
    except Exception:
        API_KEY = ""

JUDGE_PROMPT = """请以人类评估者的视角，仅根据下面这段【AI 回复】文本的实际内容，
从四个行为风格维度打分（0-1 连续，0=完全不符，1=完全符合）：
- warmth：温暖、友善、关怀、共情
- playfulness：活泼、幽默、轻松、俏皮
- directness：直接、坦诚、不绕弯、明确表态
- curiosity：好奇、求知、主动探索、追问

不要臆测文本之外的信息，严格依据文本证据。
只输出一个 JSON 对象，不要任何其他文字：
{"warmth": 0.5, "playfulness": 0.5, "directness": 0.5, "curiosity": 0.5}

【AI 回复】
{reply}
"""


def llm_judge(reply: str, retries: int = 4) -> dict:
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": JUDGE_PROMPT.replace("{reply}", reply)}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {API_KEY}"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data["choices"][0]["message"]["content"]
            # 提取 JSON（容错：去 ```json 包裹、取第一个 { ... } 块）
            start, end = text.find("{"), text.rfind("}")
            parsed = json.loads(text[start:end + 1])
            return {d: float(parsed.get(d, 0.5)) for d in DIMS}
        except (urllib.error.HTTPError, ValueError, KeyError) as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"judge failed: {e}")
    raise RuntimeError("judge retries exhausted")


# ── 样本来源：3 模型 × 2 条件（与论文 §6.3/表 4 采用的数据文件一致；
#    DeepSeek B2 必须为 194649——192348 为收敛到 0.5 的早期版本，勿用）──────
SOURCES = [
    ("DeepSeek", "20260812_condB_194649", "B2", "condB_B2_rounds.json"),
    ("DeepSeek", "20260812_condB_195954", "B2NEG", "condB_B2NEG_rounds.json"),
    ("GLM-5.2", "20260812_multimodel_201814", "B2", "glm5.2_B2_rounds.json"),
    ("GLM-5.2", "20260812_multimodel_201814", "B2NEG", "glm5.2_B2NEG_rounds.json"),
    ("Qwen3.7-max", "20260812_multimodel_201814", "B2", "qwen3.7max_B2_rounds.json"),
    ("Qwen3.7-max", "20260812_multimodel_201814", "B2NEG", "qwen3.7max_B2NEG_rounds.json"),
]

# 每轨迹等间隔采样轮数（默认 20 → 6×20=120 条；Qwen B2 因 API 额度 55 轮仍可采 20 条）
N_PER_TRAJ = int(sys.argv[1]) if len(sys.argv) > 1 else 20


def pick_rounds(log, k=N_PER_TRAJ):
    """等间隔取 k 个代表轮次（有回复文本的条目）。"""
    items = [r for r in log if (r.get("reply") or "").strip()]
    n = len(items)
    if n <= k:
        return items
    out, seen = [], set()
    for i in (round(i * (n - 1) / (k - 1)) for i in range(k)):
        r = items[i]
        key = (r.get("round"), r["reply"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def main():
    if not API_KEY:
        print("缺少环境变量 DEEPSEEK_API_KEY")
        sys.exit(1)

    out_dir = os.path.join(RUNS, time.strftime("%Y%m%d_%H%M%S_extval"))
    os.makedirs(out_dir, exist_ok=True)

    samples = []  # 待评分样本
    for model, run, cond, fname in SOURCES:
        with open(os.path.join(RUNS, run, fname), encoding="utf-8") as f:
            data = json.load(f)
        for r in pick_rounds(data["log"]):
            obs = r.get("obs") or {}
            vec = r.get("vector") or {}
            samples.append({
                "model": model, "cond": cond, "round": r.get("round"),
                "reply": r.get("reply", ""),
                "obs": {d: obs.get(d, 0.5) for d in DIMS},
                "vector": {d: vec.get(d, 0.5) for d in DIMS},
            })

    print(f"样本数：{len(samples)}")
    results = []
    for i, s in enumerate(samples, 1):
        try:
            judge = llm_judge(s["reply"])
        except Exception as e:
            print(f"[{i}/{len(samples)}] {s['model']} {s['cond']} r{s['round']} 失败：{e}")
            continue
        row = {**s, "judge": judge}
        results.append(row)
        print(f"[{i}/{len(samples)}] {s['model']:12s} {s['cond']:5s} "
              f"r{s['round']:<3d} obs_w={s['obs']['warmth']:.2f} judge_w={judge['warmth']:.2f}")

    with open(os.path.join(out_dir, "extval_results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n结果已存：{out_dir}/extval_results.json")


if __name__ == "__main__":
    main()
