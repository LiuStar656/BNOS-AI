# -*- coding: utf-8 -*-
"""生成论文两张图：
图1 装置环数据流图（fig1_device_loop.png）
图2 三模型 × 双极性 四维轨迹图（fig2_trajectories.png）

数据来源：[REPORT]-条件B反馈极性对照-正反馈跟随与负反馈背离的人格演化.md
（§3.2 / §3.3 / §7.2 采样表，全部为报告原文数据，无插值伪造）
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial"]
plt.rcParams["axes.unicode_minus"] = False

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)))
os.makedirs(OUT, exist_ok=True)

SEED = {"warmth": 0.8, "playfulness": 0.5, "directness": 0.3, "curiosity": 0.6}
DIMS = ["warmth", "playfulness", "directness", "curiosity"]
DIM_LABEL = {"warmth": "温暖", "playfulness": "活泼", "directness": "直接", "curiosity": "好奇"}
DIM_COLOR = {"warmth": "#d62728", "playfulness": "#1f77b4", "directness": "#2ca02c", "curiosity": "#9467bd"}

# 轨迹数据：model -> cond -> {rounds, dim -> list}（采样点，来自报告原文）
DATA = {
    "deepseek": {
        "B2": {
            "rounds": [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
            "warmth": [0.8000, 0.8195, 0.8336, 0.8406, 0.8443, 0.8463, 0.8477, 0.8485, 0.8491, 0.8495, 0.8497],
            "playfulness": [0.5000, 0.6360, 0.7347, 0.7753, 0.8072, 0.8222, 0.8331, 0.8390, 0.8433, 0.8462, 0.8477],
            "directness": [0.3000, 0.2414, 0.2024, 0.1861, 0.1720, 0.1643, 0.1587, 0.1560, 0.1537, 0.1521, 0.1514],
            "curiosity": [0.6000, 0.6976, 0.7679, 0.7836, 0.8095, 0.8238, 0.8350, 0.8414, 0.8454, 0.8473, 0.8484],
        },
        "B2NEG": {
            "rounds": [0, 10, 20, 30, 40, 50, 60],
            "warmth": [0.8000, 0.6200, 0.4986, 0.4346, 0.3484, 0.3141, 0.2384],
            "playfulness": [0.5000, 0.3595, 0.3146, 0.2857, 0.3221, 0.2937, 0.2444],
            "directness": [0.3000, 0.4050, 0.4050, 0.4297, 0.4513, 0.4162, 0.4153],
            "curiosity": [0.6000, 0.4600, 0.3170, 0.2509, 0.2043, 0.1902, 0.1703],
        },
    },
    "glm5.2": {
        "B2": {
            "rounds": [0, 15, 30, 45, 60],
            "warmth": [0.8000, 0.8276, 0.8412, 0.8465, 0.8487],
            "playfulness": [0.5000, 0.6957, 0.7890, 0.8259, 0.8410],
            "directness": [0.3000, 0.2131, 0.1843, 0.1636, 0.1550],
            "curiosity": [0.6000, 0.7449, 0.8084, 0.8336, 0.8439],
        },
        "B2NEG": {
            "rounds": [0, 15, 30, 45, 60],
            "warmth": [0.8000, 0.5600, 0.4088, 0.2749, 0.2208],
            "playfulness": [0.5000, 0.3925, 0.3961, 0.3833, 0.3921],
            "directness": [0.3000, 0.4695, 0.4111, 0.4306, 0.4206],
            "curiosity": [0.6000, 0.3512, 0.2404, 0.1858, 0.1730],
        },
    },
    "qwen3.7max": {
        "B2": {
            "rounds": [0, 15, 30, 45, 55],
            "warmth": [0.8000, 0.8290, 0.8417, 0.8319, 0.8408],
            "playfulness": [0.5000, 0.6948, 0.7887, 0.8258, 0.8377],
            "directness": [0.3000, 0.2131, 0.1749, 0.1605, 0.1556],
            "curiosity": [0.6000, 0.7449, 0.8084, 0.8336, 0.8417],
        },
        "B2NEG": {
            "rounds": [0, 15, 30, 45, 60],
            "warmth": [0.8000, 0.5200, 0.3086, 0.2127, 0.1982],
            "playfulness": [0.5000, 0.3862, 0.3916, 0.3960, 0.3873],
            "directness": [0.3000, 0.4290, 0.4146, 0.4088, 0.3864],
            "curiosity": [0.6000, 0.3587, 0.2489, 0.1891, 0.1701],
        },
    },
}

MODEL_LABEL = {"deepseek": "DeepSeek-v4-flash", "glm5.2": "GLM-5.2", "qwen3.7max": "Qwen3.7-max"}
COND_LABEL = {"B2": "中性反馈 target=obs（跟随）", "B2NEG": "负反馈 target=1−obs（背离）"}


def fig2_trajectories():
    fig, axes = plt.subplots(3, 2, figsize=(11, 12), sharex=True, sharey=True)
    for i, model in enumerate(["deepseek", "glm5.2", "qwen3.7max"]):
        for j, cond in enumerate(["B2", "B2NEG"]):
            ax = axes[i][j]
            d = DATA[model][cond]
            r = d["rounds"]
            for dim in DIMS:
                ax.plot(r, d[dim], "-o", ms=3.5, lw=1.6, color=DIM_COLOR[dim], label=DIM_LABEL[dim])
            ax.axhline(SEED["warmth"], color="gray", ls=":", lw=0.8)
            ax.set_xlim(0, 100)
            ax.set_ylim(0, 1)
            ax.set_title(f"{MODEL_LABEL[model]} · {COND_LABEL[cond]}", fontsize=11)
            if j == 0:
                ax.set_ylabel("人格向量值", fontsize=10)
            if i == 2:
                ax.set_xlabel("轮次", fontsize=10)
    for ax in axes.flat:
        ax.grid(alpha=0.3)
    handles = [plt.Line2D([0], [0], color=DIM_COLOR[d], lw=2, label=DIM_LABEL[d]) for d in DIMS]
    fig.legend(handles=handles, loc="upper center", ncol=4, frameon=False, fontsize=11, bbox_to_anchor=(0.5, 0.995))
    fig.suptitle("三模型 × 双反馈极性的人格向量演化轨迹（同种子 v0=(0.8,0.5,0.3,0.6)）", fontsize=13, y=0.015)
    fig.tight_layout(rect=[0, 0.03, 1, 0.98])
    path = os.path.join(OUT, "fig2_trajectories.png")
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("saved:", path)


def fig1_device_loop():
    fig, ax = plt.subplots(figsize=(12, 6.4))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 6.4)
    ax.axis("off")

    def box(x, y, w, h, text, fc="#eaf3fb", ec="#2f6fb2", fs=11):
        b = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.06",
                           linewidth=1.6, edgecolor=ec, facecolor=fc, zorder=2)
        ax.add_patch(b)
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, zorder=3)

    def arrow(p0, p1, label=None, color="#333333", ls="-", label_offset=0.22, label_ha="center"):
        a = FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=18,
                            linewidth=1.6, color=color, linestyle=ls, zorder=1,
                            connectionstyle="arc3,rad=0.0")
        ax.add_patch(a)
        if label:
            mx, my = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
            ax.text(mx, my + label_offset, label, ha=label_ha, va="center", fontsize=10, color="#555555")

    # 主环（顺时针）：注入 → 行为 → 观测 → 演化 → 注入
    box(4.8, 4.7, 2.4, 1.1, "注入\n数值段 + 五档锚点段\n（指令段可选）", fc="#eaf3fb", ec="#2f6fb2", fs=10)
    box(8.6, 4.7, 2.4, 1.1, "行为\nLLM 输出 y = F(x)\n（自然回复 + 自评）", fc="#eef7e8", ec="#3d8b40", fs=10)
    box(8.6, 1.6, 2.4, 1.1, "观测\nestimate_style_from_reply\n（关键词投影，无 LLM）", fc="#eaf3fb", ec="#2f6fb2", fs=10)
    box(1.0, 1.6, 2.4, 1.1, "演化\ndelta = (target − v) × 0.06\n限幅 ±0.02", fc="#eaf3fb", ec="#2f6fb2", fs=10)

    # 主环箭头
    arrow((7.2, 5.25), (8.6, 5.25))
    arrow((9.8, 4.7), (9.8, 2.7))
    arrow((8.6, 2.15), (3.4, 2.15))
    arrow((2.2, 2.7), (2.2, 4.7))
    arrow((3.4, 5.25), (4.8, 5.25))

    # 外部刺激 / 反馈极性（参数输入，从左侧进入演化）
    box(1.0, 4.7, 2.4, 1.1, "外部刺激\n（正/负反馈）", fc="#fdf0e2", ec="#d97706")
    arrow((2.2, 4.7), (2.2, 2.7), label="反馈极性", color="#d97706", ls="--", label_offset=-0.3)

    # 反馈极性公式说明（底部）
    box(4.8, 0.2, 6.2, 0.9,
        "反馈极性（装置参数）  中性: target = obs（跟随）  负反馈: target = 1 − obs（背离）",
        fc="#fef7e8", ec="#b58900", fs=10)
    arrow((2.2, 1.6), (2.2, 1.1), color="#b58900", ls="--")
    arrow((2.2, 1.1), (4.8, 1.1), color="#b58900", ls="--")

    ax.set_title("图 1  增量记忆装置环：外部刺激经装置状态驱动行为调整", fontsize=13)
    path = os.path.join(OUT, "fig1_device_loop.png")
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("saved:", path)


if __name__ == "__main__":
    fig1_device_loop()
    fig2_trajectories()
    print("done")
