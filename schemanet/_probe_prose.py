# -*- coding: utf-8 -*-
"""Stage 3 v17 散文/记叙文语料探测：鲁迅公版作品 → 分句 → 配对关系句筛选。

背景（2026-08-10 用户）：
  - "要不要加一些自然语言对话文本或者那种记叙文散文这种文本来训练？"
  - 用户决策：我找开源语料（推荐）+ 构造对话自然化
  - 来源：Project Gutenberg 公版中文（鲁迅《朝花夕拾》《呐喊》《彷徨》《野草》
    《南腔北调集》），Public Domain，著作权过期可自由使用

管线（与 toutiao 精筛同构，铁律 1 数据专门化——只取句级配对关系句，不喂全文）：
  原始 txt → 去 Gutenberg 页眉页脚/脚注 → opencc 繁转简 → 标点分句
  → 配对关系句（因为…所以 / 虽然…但是 / 先…然后）→ 长度 5-22 词
  → 词表外词 ≤4 → 去重

输出：runs/_speak_logs/{ts}_probe_prose/result.json + 样本

用法：python _probe_prose.py
"""

import json
import re
import time
from pathlib import Path

PROSE_DIR = Path(__file__).parent / "data" / "curriculum" / "raw" / "prose"
RUNS_DIR = Path(__file__).parent / "runs"

BOOKS = ["zhaohuaxishi_luxun.txt", "nahan_luxun.txt", "panghuang_luxun.txt",
         "yecao_luxun.txt", "nanqiangbeidiao_luxun.txt"]
REL_PAIRS = [("因为", "所以"), ("虽然", "但是"), ("先", "然后")]

TITLE = {
    "zhaohuaxishi_luxun.txt": "朝花夕拾（散文集）",
    "nahan_luxun.txt": "呐喊（叙事小说集）",
    "panghuang_luxun.txt": "彷徨（叙事小说集）",
    "yecao_luxun.txt": "野草（散文诗）",
    "nanqiangbeidiao_luxun.txt": "南腔北调集（杂文）",
}


def clean_pg(text):
    """去 Gutenberg 页眉页脚与脚注标记。"""
    m = re.search(r"\*\*\*\s*START OF[^\n]*\n", text)
    if m:
        text = text[m.end():]
    m = re.search(r"\*\*\*\s*END OF[^\n]*", text)
    if m:
        text = text[:m.start()]
    text = re.sub(r"\[_?[Nn]ote:[^\]]*\]", "", text)      # 脚注
    text = re.sub(r"[_*#]{1,3}\s?", "", text)              # 校订/强调标记
    text = re.sub(r"\s+", "", text)                        # 去所有空白（含换行）
    return text


def split_sents(text):
    """标点分句（。！？；切分）。"""
    return [s for s in re.split(r"[。！？；]+", text) if len(s) >= 4]


def main():
    from opencc import OpenCC
    from snapshot import load_version
    cc = OpenCC("t2s")          # 繁转简
    ng, _, pats, _ = load_version("15.0")
    keys = set(pats.keys())
    print(f"[词表] v15.0 共 {len(keys)} 词（简体）\n")

    t0 = time.time()
    all_out = []
    per_book = {}
    for fn in BOOKS:
        p = PROSE_DIR / fn
        raw = p.read_text(encoding="utf-8", errors="ignore")
        body = cc.convert(clean_pg(raw))
        sents = split_sents(body)
        # 配对关系句筛选
        pair_rows = []
        for s in sents:
            for a, b in REL_PAIRS:
                if a in s and b in s:
                    pair_rows.append((s, f"{a}…{b}"))
                    break
        # 去重 + 长度 + 词表过滤
        seen, rows = set(), []
        for s, tag in pair_rows:
            toks = list(jieba_cut(s))
            if not (5 <= len(toks) <= 22):
                continue
            if any(ch.isascii() and ch.isalnum() for w in toks for ch in w):
                continue
            miss = [w for w in toks if w not in keys]
            if len(miss) > 4:
                continue
            key = "".join(toks)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"book": TITLE[fn], "pair": tag, "tokens": toks,
                         "sent": "".join(toks), "miss": miss,
                         "miss_n": len(miss)})
        per_book[fn] = {"total_chars": len(body), "sents": len(sents),
                        "pair_rows": len(pair_rows), "kept": len(rows)}
        all_out += rows
        print(f"[{TITLE[fn]}] 正文 {len(body)} 字 | 分句 {len(sents)}"
              f" | 配对候选 {len(pair_rows)} | 通过词表/长度 {len(rows)}")
        for r in rows[:6]:
            print(f"    ({len(r['tokens'])}词 缺{len(r['miss'])})"
                  f" {' '.join(r['tokens'])}")

    # 来源分布 + 样本
    from collections import Counter
    dist = Counter(r["pair"] for r in all_out)
    print(f"\n[汇总] 散文/记叙文精筛共 {len(all_out)} 条"
          f"（配对分布 {dict(dist)}）")
    print(f"  词表内条数：{sum(1 for r in all_out if r['miss_n'] == 0)}/"
          f"{len(all_out)}")

    # 落档
    out_dir = RUNS_DIR / "_speak_logs" / f"{time.strftime('%Y%m%d_%H%M%S')}_probe_prose"
    out_dir.mkdir(parents=True, exist_ok=True)
    result = {"tag": "v17 散文/记叙文语料探测（鲁迅公版，繁转简）",
              "base": "15.0", "per_book": per_book,
              "total_kept": len(all_out), "pair_dist": dict(dist),
              "rows": all_out, "sec": round(time.time() - t0, 1)}
    (out_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False,
                                                    indent=1), encoding="utf-8")
    print(f"\n[留档] {out_dir / 'result.json'}（{time.time() - t0:.0f}s）")


def jieba_cut(s):
    import jieba
    return list(jieba.cut(s))


if __name__ == "__main__":
    main()
