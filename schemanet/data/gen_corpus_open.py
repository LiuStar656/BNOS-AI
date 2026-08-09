# -*- coding: utf-8 -*-
"""生成开源真实语料 corpus_open.json（C 路线第二阶段：真实语料规模验证）。

数据源：ChineseNlpCorpus（SophonPlus/ChineseNlpCorpus，GitHub raw 直链）
  ① 外卖评论 waimai_10k（1.2 万条，口语短句）
  ② 酒店评论 ChnSentiCorp_htl_all（7000+ 条）
  ③ 商品评论 online_shopping_10_cats（6 万+ 条）
  ④ 微博 weibo_senti_100k（10 万条）

流程：下载（缓存 data/raw/）→ 解析 CSV（label,review）→ 清洗（去 URL/@/#
话题/emoji/非常用字符，去空去重）→ jieba 分词 → 标点白名单过滤 → 长度过滤
[3,30] 词 → 每源均衡抽样 → 词表 top-K（KV=3000，强制含 <UNK>）→ OOV 替换
→ 输出分词后句子列表 corpus_open.json（训练/验收直接使用，一次处理多处复用）。

输出：corpus_open.json（tokenized 句列表）+ 统计报告（词表、覆盖率、UNK 占比、
句长分布、每源句数）。可复现：固定 seed。已下载的 CSV 缓存不重复下载。
"""
import csv
import io
import json
import re
from collections import Counter
from pathlib import Path

import requests

DATA = Path(__file__).parent
RAW = DATA / "raw"
RAW.mkdir(parents=True, exist_ok=True)

N_TARGET = 24000          # 目标总句数（标准档）
N_PER_SRC = N_TARGET // 4  # 每源均衡 6000
KV = 3000                 # 词表规模（标准档）
UNK = "<UNK>"
SEED = 42
MIN_LEN, MAX_LEN = 3, 30   # 句长过滤（词数）

# 数据源：(repo, 文件路径, 格式)
#   fmt="csv"：label,review 逗号分隔；fmt="txt"：label\t标题 tab 分隔
#   online/toutiao 为 zip 包（GitHub 仓库内直接提供，zip 内为上述格式文件）
SOURCES = {
    "waimai": ("SophonPlus/ChineseNlpCorpus", "datasets/waimai_10k/waimai_10k.csv", "csv"),
    "hotel": ("SophonPlus/ChineseNlpCorpus", "datasets/ChnSentiCorp_htl_all/ChnSentiCorp_htl_all.csv", "csv"),
    "online": ("SophonPlus/ChineseNlpCorpus", "datasets/online_shopping_10_cats/online_shopping_10_cats.zip", "zip_csv"),
    "toutiao": ("aceimnorstuvwxz/toutiao-text-classfication-dataset", "toutiao_cat_data.txt.zip", "zip_txt"),
}

# 下载镜像（按序尝试；jsdelivr CDN 国内可达，raw 直连不稳定作兜底）
BASE_URLS = [
    "https://cdn.jsdelivr.net/gh/{repo}@master/{path}",
    "https://raw.githubusercontent.com/{repo}/master/{path}",
    "https://mirror.ghproxy.com/https://raw.githubusercontent.com/{repo}/master/{path}",
]
N_TRY = 2   # 每镜像重试次数

# 保留的中文常用标点（作为独立 token，句号=句尾信号）
PUNCT_KEEP = set("，。！？；：、…—·")
# 去 URL / @提及 / #话题#
RE_URL = re.compile(r"https?://\S+")
RE_AT = re.compile(r"@\S+")
RE_TOPIC = re.compile(r"#\S*#")
# 去 emoji / 非常用字符（只留中文、英数、白名单标点、空白）
RE_DIRTY = re.compile(r"[^\u4e00-\u9fffA-Za-z0-9，。！？；：、…—·\s]")


def fetch(repo, path):
    """下载文件并缓存到 data/raw/。多镜像 + 重试。zip 包自动解压。返回数据文件本地路径。"""
    fname = path.rsplit("/", 1)[-1]
    local = RAW / fname
    if not local.exists():
        last_err = None
        for url_tpl in BASE_URLS:
            for attempt in range(1, N_TRY + 1):
                url = url_tpl.format(repo=repo, path=path)
                try:
                    print(f"[fetch] {fname}: 尝试({attempt}) {url.split('//')[1][:55]} ...", flush=True)
                    r = requests.get(url, timeout=90)
                    r.raise_for_status()
                    if not r.content:
                        raise RuntimeError("空响应")
                    local.write_bytes(r.content)
                    print(f"[fetch] {fname}: {len(r.content) / 1e6:.1f}MB 成功")
                    break
                except Exception as e:   # noqa: BLE001 —— 下载失败记录后换源/重试
                    last_err = e
                    print(f"[fetch] {fname}: 失败 {type(e).__name__}: {e}")
            if local.exists():
                break
        if not local.exists():
            raise RuntimeError(f"{fname} 全部镜像下载失败: {last_err}")
    else:
        print(f"[fetch] {fname}: 缓存命中 {local}")

    # zip 包解压到 data/raw/{name}_unzip/
    if path.endswith(".zip"):
        name = fname[:-4] if fname.endswith(".zip") else fname
        unzip_dir = RAW / f"{name}_unzip"
        if not unzip_dir.exists():
            import zipfile
            with zipfile.ZipFile(local) as z:
                z.extractall(unzip_dir)
        # 返回解压目录里的第一个数据文件（.csv/.txt）
        cands = sorted(p for p in unzip_dir.rglob("*") if p.suffix.lower() in (".csv", ".txt"))
        if not cands:
            raise RuntimeError(f"{fname} 解压后无数据文件")
        print(f"[fetch] {fname}: 解压 → {cands[0]}")
        return cands[0]
    return local


def load_texts(path, fmt):
    """按格式解析数据文件，返回 review/标题 文本列表。"""
    texts = []
    if fmt in ("csv", "zip_csv"):
        text = path.read_bytes().decode("utf-8-sig", errors="ignore")
        reader = csv.reader(io.StringIO(text))
        header = next(reader, None)
        if not header:
            return texts
        # 按 header 定位 review 列（waimai/hotel 两列、online 三列 cat,label,review）
        ri = header.index("review") if "review" in header else 1
        for row in reader:
            if len(row) <= ri:
                continue
            texts.append(row[ri])
    else:   # zip_txt：news_id_!_label_!_cat_!_标题_!_keywords_!_desc（_!_ 分隔，标题第 4 列）
        for line in path.read_bytes().decode("utf-8-sig", errors="ignore").splitlines():
            parts = line.split("_!_")
            if len(parts) >= 4 and parts[3].strip():
                texts.append(parts[3].strip())
    return texts


def clean(s):
    s = RE_URL.sub("", s)
    s = RE_AT.sub("", s)
    s = RE_TOPIC.sub("", s)
    s = RE_DIRTY.sub("", s)
    return s.strip()


def main():
    import jieba
    import numpy as np

    rng = np.random.default_rng(SEED)

    # ── 1. 下载 + 解析 + 清洗 ──
    per_src = {}
    for name, (repo, path, fmt) in SOURCES.items():
        raw = fetch(repo, path)
        reviews = [clean(s) for s in load_texts(raw, fmt)]
        uniq = list(dict.fromkeys(r for r in reviews if r))   # 去空 + 去重（保序）
        print(f"[{name}] 原始 {len(reviews)} → 去空去重后 {len(uniq)}")
        per_src[name] = uniq

    # ── 2. 分词 + 标点/长度过滤 → kept_all[name] ──
    kept_all = {}
    src_cnt = {}
    for name, uniq in per_src.items():
        kept = []
        for s in uniq:
            toks = [t for t in jieba.lcut(s)
                    if t and (t.strip() or t in PUNCT_KEEP)]   # 去空白 token
            toks = [t for t in toks if t[0].isalnum() or t in PUNCT_KEEP]
            if MIN_LEN <= len(toks) <= MAX_LEN:
                kept.append(toks)
        kept_all[name] = kept
        src_cnt[name] = len(kept)
        print(f"[{name}] 分词+长度过滤后 {len(kept)} 句")

    # ── 3. 每源均衡抽样（目标每源 N_PER_SRC）──
    sampled = []
    sampled_cnt = {}
    for name, kept in kept_all.items():
        n = min(N_PER_SRC, len(kept))
        idx = rng.choice(len(kept), n, replace=False)
        for i in sorted(idx):
            sampled.append(kept[i])
        sampled_cnt[name] = n
        print(f"[{name}] 抽样 {n} 句")

    print(f"合计抽样 {len(sampled)} 句")

    # ── 4. 词表 top-KV（强制含 <UNK>；UNK 已高频，排除后按频率补齐）──
    freq = Counter(t for toks in sampled for t in toks)
    vocab = [UNK] + [w for w, _ in freq.most_common(KV + 100) if w != UNK][:KV - 1]
    vocab_idx = {w: i for i, w in enumerate(vocab)}
    covered = sum(freq[w] for w in vocab)
    oov_tot = sum(c for w, c in freq.items() if w not in vocab_idx)
    print(f"词表 {len(vocab)}（含 {UNK}），token 覆盖率 {covered / sum(freq.values()):.4f}")

    # ── 5. OOV → <UNK> 替换 ──
    out = [[t if t in vocab_idx else UNK for t in toks] for toks in sampled]

    # ── 6. 统计 ──
    lens = [len(t) for t in out]
    unk_ratio = sum(t == UNK for toks in out for t in toks) / sum(lens)
    top20 = [f"{w}:{c}" for w, c in freq.most_common(20)]
    stats = {
        "n_sent": len(out), "vocab": len(vocab), "kv_target": KV,
        "token_cover": round(covered / sum(freq.values()), 4),
        "unk_ratio": round(unk_ratio, 4),
        "len_min": min(lens), "len_mean": round(sum(lens) / len(lens), 1),
        "len_max": max(lens),
        "per_src": src_cnt, "sampled_per_src": sampled_cnt,
        "top20": top20, "seed": SEED,
    }
    print("\n[corpus_open] 统计:", json.dumps(stats, ensure_ascii=False))
    print("  top-20:", " ".join(top20))

    # ── 7. 输出 ──
    out_path = DATA / "corpus_open.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    (DATA / "corpus_open_meta.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写出: {out_path}（{len(out)} 句）")


if __name__ == "__main__":
    main()
