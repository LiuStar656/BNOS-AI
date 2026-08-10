# -*- coding: utf-8 -*-
"""主动求证循环最小实验（2026-08-11）：

用户："让定式网络直接找 LLM 求证（打通网络自主能力），而不是 LLM
主动给网络说"——PRT 依据：遵循孩子选择/穿插新旧任务/强化努力/
自然强化。

流程（纯内存——不碰快照）：
  ① 网络"运行"于情境集（新刺激 = 制造提问时机）
  ② 疑问信号检测：状态→需求语义边（L3）缺失 = 推演卡壳 = 提问时机；
     已存在 = 已会（穿插新旧任务的"旧"——不问）
  ③ 网络主动提问（"X怎么办？"——已有句式）
  ④ LLM 求证（只答被问的——按需教学）
  ⑤ 答案 → 教学 + 验证登记（教师示范 = 权威正例）→ 验证 ≥2 固化
  ⑥ 自然强化检查：求证后该情境预测/走链是否变准（RPE 归零）
统计：提问质量（真缺口率）、吸收率、自然强化率、LLM 调用量
     （对比 live12 主动教学 60 次/轮）

用法：python _exp_ask.py
"""

import json
import time
from pathlib import Path

from schema_net import _learn_sentence
from snapshot import load_version, load_consolidated
from _exam_free import free_read, build_domain, build_teach_out
from _grow_qa_s3 import build_pool as qa_build_pool
from _grow_cat import build_cats
from _grow_v11 import _load_key, _llm_chat
from _grow_v16 import edge_between

DATA = Path(__file__).parent / "data" / "curriculum"

# 情境集（制造提问时机）：(触发词, 期望需求词, 提问句式)
SCENES = [
    ("狗", "喝", "狗渴了怎么办？"),
    ("猫", "喝", "猫渴了怎么办？"),
    ("他", "穿", "他冷了怎么办？"),
    ("小猫", "吃", "小猫饿了怎么办？"),
    ("疼", "帮", "疼了怎么办？"),          # 已会（疼→帮 旧边）——对照
    ("困", "睡", "困了怎么办？"),          # 已会（固化句）——对照
    ("生病", "看医生", "生病了怎么办？"),   # 旧知识（生病→看医生？）
    ("下雨", "带伞", "下雨了怎么办？"),     # 旧知识（下雨→带伞？）
]


def ask_teacher(ask):
    """网络主动提问 → LLM 求证（只答示范句——按需）。"""
    q = (f"你是妈妈，孩子问：「{ask}」\n"
         f"请只用一句话回答：正常儿童该怎么说（≤10 字，自然完整）")
    txt = None
    for _ in range(2):
        txt = _llm_chat([{"role": "user", "content": q}])
        if txt:
            break
    return txt


def seg_demo(demo, keys):
    d_toks = []
    rest = (demo or "").replace("。", "").replace("！", "")
    while rest:
        hit = next((w for w in sorted(keys, key=len, reverse=True)
                    if rest.startswith(w)), None)
        if not hit:
            break
        d_toks.append(hit)
        rest = rest[len(hit):]
    return d_toks


def main():
    from schema_net import consolidate_sentence
    t0 = time.time()
    print("═══ 主动求证循环最小实验（网络找 LLM 求证）═══\n")
    print("（纯内存——不保存快照，不碰 v34.0 治疗成果）\n")

    ng, vocab, pats, cursor = load_version("34.0")
    consolidated, validation = load_consolidated("34.0")
    ng.w_max = 64.0
    n2w = {j: w for w, ns in pats.items() for j in ns}
    keys = set(pats.keys())
    rows = json.loads((DATA / "stage3_rel_v3.json").read_text(encoding="utf-8"))
    sem = json.loads((DATA / "stage25_sememes.json").read_text(encoding="utf-8"))
    cats = build_cats(pats, sem["words"], 12, 3)
    q_pool = qa_build_pool(rows, cats)
    domain = build_domain(ng, pats, rows, q_pool)
    teach_out = build_teach_out(rows, q_pool)
    has_llm = bool(_load_key())
    cursor2 = cursor

    n_ask = n_gap = n_absorb = n_natural = 0
    n_calls = 0
    print(f"{'情境':<14}{'疑问信号':<10}{'行为':<8}{'求证答案':<16}{'固化'}")
    for kw, want, ask in SCENES:
        if kw not in keys:
            print(f"「{kw}」✗ 词表外（跳过）")
            continue
        # ① 疑问信号：L3 语义边（状态→需求）缺失 = 推演卡壳
        gap = edge_between(ng, pats, kw, want) <= 0
        if gap:
            n_gap += 1
        if not gap:
            # 已会（穿插新旧任务的"旧"）——不问
            print(f"「{kw}」已会     跳过（穿插维持）")
            continue
        n_ask += 1
        # ③ 网络主动提问 → LLM 求证
        ans = ask_teacher(ask) if has_llm else None
        n_calls += 1
        if not ans:
            print(f"「{kw}」提问失败（无 LLM）")
            continue
        d_toks = seg_demo(ans, keys)
        if not d_toks:
            print(f"「{kw}」求证「{ans[:12]}」→ 分词失败")
            continue
        # ⑤ 答案 → 教学 + 验证登记（教师示范 = 权威正例）→ 固化
        for _ in range(3):
            _learn_sentence(ng, d_toks, pats, slot=0)
        vkey = (kw, want, tuple(d_toks))
        v0, v1 = validation.get(vkey, (0, 0))
        validation[vkey] = (v0 + 3, v1)      # 示范 ×3 = 3 对
        slots, cursor2 = consolidate_sentence(ng, pats, cursor2, d_toks)
        consolidated.setdefault(kw, []).append(
            (d_toks, slots, "怎么办"))
        n_absorb += 1
        # ⑥ 自然强化检查：求证后该情境是否变准
        trace = []
        read = free_read(ng, pats, n2w, [kw], domain, teach_out=teach_out,
                         trace=trace, consolidated=consolidated,
                         validation=validation)
        toks = []
        for w in [x.split("(")[0] for x in read]:
            if w.startswith("[") or w in toks:
                break
            toks.append(w)
        walked = any("整句" in str(t.get("cands", [])) for t in trace)
        if toks and kw not in toks and not walked:
            toks.insert(0, kw)
        correct = any(any(e in w for e in [want, *d_toks]) for w in toks)
        n_natural += correct
        print(f"「{ask}」缺口     提问    「{ans[:12]}」"
              f"{'✅固化+走通' if correct else '⚠️固化未通'}"
              f"（{'/'.join(toks)[:20]}）")

    print(f"\n═══ 统计 ═══")
    print(f"  情境数：{len(SCENES)}（已会跳过 = 穿插维持——不问）")
    print(f"  提问数（真缺口）：{n_ask}/{n_gap}（疑问信号质量）")
    print(f"  吸收率（求证→固化）：{n_absorb}/{n_ask}")
    print(f"  自然强化率（求证后走通）：{n_natural}/{n_ask}"
          f"（预测变准 = RPE 归零）")
    print(f"  LLM 调用：{n_calls} 次（live12 主动教学对比：60 次/轮）")
    print(f"[完成]（{time.time()-t0:.0f}s）")


if __name__ == "__main__":
    main()
