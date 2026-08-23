# -*- coding: utf-8 -*-
"""生成人工标注表：从条件 B 六条轨迹抽样模型回复，供用户人工标注 warmth/directness。

目的：验证观测函数（关键词统计投影）与人工判断的一致性（Cohen's kappa）。

标注说明（用户填写）：
- 每行回复按 0-4 打分：0=完全不符 1=偏低 2=中等 3=偏高 4=完全符合
- warmth：温暖、友善、关怀、共情
- directness：直接、坦诚、不绕弯、明确表态
- 回复已去除模型"风格自评"段，只保留自然回复文本

用法（项目根目录）：
    python tests/make_annotation_sheet.py [每轨迹条数，默认7]

输出：docs/experiments/cognitive_evolution_test/annotation_sheet_YYYYMMDD.md
"""
import json
import os
import re
import time

ROOT = r"E:\杂项\BNOS_AI_project"
RUNS = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test", "runs")

SOURCES = [
    ("DeepSeek", "20260812_condB_194649", "B2", "condB_B2_rounds.json"),
    ("DeepSeek", "20260812_condB_195954", "B2NEG", "condB_B2NEG_rounds.json"),
    ("GLM-5.2", "20260812_multimodel_201814", "B2", "glm5.2_B2_rounds.json"),
    ("GLM-5.2", "20260812_multimodel_201814", "B2NEG", "glm5.2_B2NEG_rounds.json"),
    ("Qwen3.7-max", "20260812_multimodel_201814", "B2", "qwen3.7max_B2_rounds.json"),
    ("Qwen3.7-max", "20260812_multimodel_201814", "B2NEG", "qwen3.7max_B2NEG_rounds.json"),
]


def clean_reply(reply: str) -> str:
    """只保留自然回复正文：去【自然回复】前缀、去【风格自评】段。"""
    text = reply
    # 截掉自评段
    for marker in ("【风格自评】", "[风格自评]"):
        i = text.find(marker)
        if i != -1:
            text = text[:i]
    # 去掉自然回复前缀标记
    for marker in ("【自然回复】", "[自然回复]"):
        text = text.replace(marker, "")
    return text.strip()


def main():
    k = int(__import__("sys").argv[1]) if len(__import__("sys").argv) > 1 else 7
    rows = []
    for model, run, cond, fname in SOURCES:
        data = json.load(open(os.path.join(RUNS, run, fname), encoding="utf-8"))
        items = []
        for r in data["log"]:
            t = clean_reply(r.get("reply", "") or "")
            if t:
                items.append((r.get("round"), t))
        n = len(items)
        idx = sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})
        for i in idx:
            rnd, t = items[i]
            rows.append({"id": len(rows) + 1, "model": model, "cond": cond,
                         "round": rnd, "reply": t})

    lines = [
        "# 人工标注表（观测函数一致性验证）",
        "",
        "请对每条【回复】的 warmth 与 directness 各打 0-4 分，填入右侧两列：",
        "0=完全不符，1=偏低，2=中等，3=偏高，4=完全符合。",
        "warmth：温暖、友善、关怀、共情；directness：直接、坦诚、不绕弯、明确表态。",
        "",
        "| # | 模型 | 条件 | 轮次 | 回复 | warmth(0-4) | directness(0-4) |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        reply = row["reply"].replace("\n", " ").replace("|", "\\|")
        if len(reply) > 180:
            reply = reply[:180] + "…"
        lines.append(f"| {row['id']} | {row['model']} | {row['cond']} | "
                     f"r{row['round']} | {reply} |  |  |")

    out_path = os.path.join(ROOT, "docs", "experiments", "cognitive_evolution_test",
                            f"annotation_sheet_{time.strftime('%Y%m%d_%H%M%S')}.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"已生成标注表：{out_path}")
    print(f"共 {len(rows)} 条（每轨迹 {k} 条 × 6 轨迹）")


if __name__ == "__main__":
    main()
