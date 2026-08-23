# 验证锚点档位-数值错位 & 双开 vs 纯锚点差异是否显著
# 数据源：formatAB probe_samples.jsonl (style 为观测值) + formatAB_results.json
import json
import math
import os

ROOT = r"e:\杂项\BNOS_AI_project\docs\experiments\cognitive_evolution_test\runs\20260815_232810_formatAB"
samples_path = os.path.join(ROOT, "probe_samples.jsonl")

rows = {}
with open(samples_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        d = json.loads(line)
        key = (d["fmt"], d["level"])
        rows.setdefault(key, []).append(d["style"]["directness"])

def mean_ci(vals):
    n = len(vals)
    m = sum(vals) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in vals) / (n - 1))
    se = sd / math.sqrt(n)
    return m, sd, m - 1.96 * se, m + 1.96 * se

print("=== 观测 directness（style 字段，目标 low=0.1 / high=0.9） ===")
for fmt in ["数值", "指令", "锚点", "双开"]:
    for lv in ["low", "high"]:
        vals = rows.get((fmt, lv), [])
        if vals:
            m, sd, lo, hi = mean_ci(vals)
            print(f"{fmt}-{lv}: n={len(vals)} mean={m:.3f} SD={sd:.3f} CI=[{lo:.3f},{hi:.3f}] 目标={'0.1' if lv=='low' else '0.9'} 偏差={m - (0.1 if lv=='low' else 0.9):+.3f}")

# 双开 vs 纯锚点 两组差异（Welch t 检验）
def welch(a, b):
    na, nb = len(a), len(b)
    ma, mb = sum(a)/na, sum(b)/nb
    va = sum((x-ma)**2 for x in a)/(na-1)
    vb = sum((x-mb)**2 for x in b)/(nb-1)
    t = (ma-mb)/math.sqrt(va/na+vb/nb)
    df = (va/na+vb/nb)**2 / ((va/na)**2/(na-1)+(vb/nb)**2/(nb-1))
    return t, df

print("\n=== 双开 vs 纯锚点（low 端 / high 端）===")
for lv in ["low", "high"]:
    a = rows.get(("锚点", lv), [])
    b = rows.get(("双开", lv), [])
    t, df = welch(a, b)
    print(f"{lv}: 锚点 mean={sum(a)/len(a):.3f} vs 双开 mean={sum(b)/len(b):.3f}, t={t:.3f}, df={df:.1f} (|t|<2 即不显著)")

# 锚点 high 注入档5 描述, 观测相对目标 0.9 的错位
a = rows.get(("锚点", "high"), [])
m, sd, lo, hi = mean_ci(a)
print(f"\n锚点-high 档位错位: 注入 0.9 → 观测 {m:.3f} (CI [{lo:.3f},{hi:.3f}]), 偏差 {m-0.9:+.3f} = {(m-0.9)/sd:.2f} SD")
