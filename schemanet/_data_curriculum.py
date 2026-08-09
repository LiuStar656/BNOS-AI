# -*- coding: utf-8 -*-
"""定式网络 v2.0 Phase A —— 分级纯净数据抽取（数据专门化基建）。

从 corpus_open20w.json（20 万句 tokenized 混合语料）抽取 Stage 0-5 分级纯净数据，
严格对照 v2.0 方案 §五（数据专门化设计）——"训练什么就用什么数据"：

  Stage 0 词表   : 高频词 top-N（去 <UNK>/停用词/纯标点）
  Stage 1 词组   : 高频相邻词对 bigram（两词均非停用/UNK/标点，主谓/动宾等组合）
  Stage 2 短句   : ≤8 词、无 <UNK> 的整句（句内标点去除）
  Stage 3 复杂句 : 含关系标记（因为/所以/虽然/但是/如果…）的句子
  Stage 4 句对   : 同段相邻句对（从含句读标点的长句切分子句，相邻子句成对）
  Stage 5 推理   : 模板构造（条件/选择/类比模板，专门生成）

关键设计——跟读重复率：每阶段基础集唯一，训练序列 = 同一批内容反复出现
（repeat ≥ 10，输出 train_*.json），满足"读的越多印象越足"（三字经机制）。

验收（Phase A）：每级数据纯净性 = 词表检查（无 UNK/停用词）、句长过滤、
关系标记覆盖、无重复污染（基础集唯一）。--stats 输出全部过滤计数。

用法：
  python _data_curriculum.py --stats           # 只统计语料结构，不写文件
  python _data_curriculum.py                   # 抽取全部分级数据到 data/curriculum/
  python _data_curriculum.py --vocab 2000 --bigrams 12000 --short 30000 \
         --complex 15000 --pairs 20000 --synth 5000 --repeat 10
"""

import argparse
import json
from collections import Counter
from pathlib import Path

DATA = Path(__file__).parent / "data"
CORPUS = DATA / "corpus_clean.json"      # v2.0 干净原料库（覆盖率 98%、UNK 2%）
CORPUS_FALLBACK = DATA / "corpus_open20w.json"  # 旧污染语料（仅 --corpus 显式指定用）
OUT = DATA / "curriculum"

UNK = "<UNK>"

# 句读标点（子句切分用）
CLAUSE_PUNCT = "。？！；"
# 全量标点（过滤用）
PUNCT = set("，。？！：；、""''（）【】《》…—·,.!?:;()~～-—_/|\\")

# 停用词（只滤最虚的虚词；关系标记词 因为/所以/虽然/但是/如果/然后… 是
# Stage 3 的学习对象，绝不进停用词）
STOPWORDS = set(
    "的了是有很你不我他她它我们你们他们她们它们这那这些那些这样那样这个那个这里那里"
    "在到上中下前后左右从向把被让给对和与或及了着过吧吗呢啊呀哦嗯嘛呗哟哦呵哈哈"
    "就也才又再更都还只一直常正别没没有不是不要要能会可以应该得怎么什么为什么怎么着"
    "个位种次些点样儿东西东西方的事情况时候地方人么什跟叫使拿按趁随"
)

# Stage 3 关系标记（复杂句判定 + 验收覆盖检查）
RELATION_MARKS = ["因为", "所以", "虽然", "但是", "但是", "如果", "那么", "由于",
                  "因此", "而且", "不但", "不仅", "只要", "只有", "除非", "无论",
                  "不管", "即使", "既然", "于是", "然而", "否则", "然后", "先",
                  "再", "首先", "接着", "最后", "要是", "假如", "假设", "一旦",
                  "一边", "一方面", "反而", "却", "不过", "尽管"]

# Stage 5 推理模板（条件/选择/因果/转折…，轻量构造器）。
# token 列表形式：{0}/{1} 为变量位（整词替换，非字符级拼接）。
SYNTH_TEMPLATES = [
    ("条件", ["如果", "{0}", "那么", "{1}"]),
    ("条件", ["要是", "{0}", "就会", "{1}"]),
    ("选择", ["要么", "{0}", "要么", "{1}"]),
    ("因果", ["因为", "{0}", "所以", "{1}"]),
    ("转折", ["虽然", "{0}", "但是", "{1}"]),
    ("条件", ["只有", "{0}", "才能", "{1}"]),
    ("并列", ["{0}", "而且", "{1}"]),
    ("假设", ["假如", "{0}", "就", "{1}"]),
]


def load_corpus(path=None):
    p = Path(path) if path else (CORPUS if CORPUS.exists() else CORPUS_FALLBACK)
    print(f"原料库: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def is_stop(w):
    return w in STOPWORDS or w in PUNCT


def is_clean_word(w):
    """词表/词组可用词：非 UNK、非停用、非纯标点、非空。"""
    if not w or w == UNK or w in STOPWORDS or w in PUNCT:
        return False
    return True


def clause_split(toks):
    """按句读标点切分子句：[(sub_toks, 该子句前是否直接跟句读)]。

    corpus 中句读是独立 token（PUNCT_KEEP），"." 后即新子句。
    返回子句列表（纯内容 token，去标点），丢弃 <UNK> 子句由调用方决定。
    """
    clauses, cur = [], []
    for t in toks:
        if t in CLAUSE_PUNCT:
            if cur:
                clauses.append(cur)
                cur = []
        elif t in PUNCT:
            continue
        else:
            cur.append(t)
    if cur:
        clauses.append(cur)
    return clauses


# ════════════════════════════════════════════════════════════════
#  Stage 抽取
# ════════════════════════════════════════════════════════════════

def extract_stage0(sents, vocab_n):
    """Stage 0 词表：高频词 top-N（去 UNK/停用/标点）。"""
    freq = Counter(t for toks in sents for t in toks
                   if is_clean_word(t))
    vocab = [w for w, _ in freq.most_common(vocab_n)]
    return vocab


def extract_stage1(sents, bigram_n):
    """Stage 1 词组：高频相邻词对（两词均可用）。"""
    freq = Counter()
    for toks in sents:
        for a, b in zip(toks, toks[1:]):
            if is_clean_word(a) and is_clean_word(b):
                freq[(a, b)] += 1
    return [list(p) for p, _ in freq.most_common(bigram_n)]


def extract_stage2(sents, max_len, short_n):
    """Stage 2 短句：无 UNK、去句内标点、≤ max_len 词的整句（基础集唯一）。"""
    out, seen = [], set()
    for toks in sents:
        if UNK in toks:
            continue
        clean = [t for t in toks if t not in PUNCT]
        if 2 <= len(clean) <= max_len:
            key = tuple(clean)
            if key in seen:
                continue
            seen.add(key)
            out.append(clean)
        if short_n and len(out) >= short_n:
            break
    return out


def extract_stage3(sents, complex_n):
    """Stage 3 复杂句：含关系标记、无 UNK 的句子（基础集唯一）。"""
    out, seen = [], set()
    for toks in sents:
        if UNK in toks:
            continue
        joined = "".join(t for t in toks if t not in PUNCT)
        if any(m in joined for m in RELATION_MARKS):
            clean = [t for t in toks if t not in PUNCT]
            key = tuple(clean)
            if key in seen:
                continue
            seen.add(key)
            out.append(clean)
        if complex_n and len(out) >= complex_n:
            break
    return out


def extract_stage4(sents, pairs_n):
    """Stage 4 句对：同段相邻子句对（长句按句读切分，相邻成对）。

    语料无显式段落 → 含句读标点的长句即"微段落"，切分出的相邻子句
    即同段相邻句（句接句转移的真实素材）。两子句均无 UNK，基础集唯一。
    """
    out, seen = [], set()
    for toks in sents:
        clauses = clause_split(toks)
        if len(clauses) < 2:
            continue
        for a, b in zip(clauses, clauses[1:]):
            if UNK in a or UNK in b:
                continue
            if len(a) < 2 or len(b) < 2:
                continue
            key = (tuple(a), tuple(b))
            if key in seen:
                continue
            seen.add(key)
            out.append([a, b])
        if pairs_n and len(out) >= pairs_n:
            break
    return out


def extract_stage5(short_sents, synth_n, rng):
    """Stage 5 推理：模板整词替换构造（条件/选择/因果/转折…）。

    变量 {0}/{1} 从 Stage 2 短句的实词中随机抽取（词级替换，保持分词格式）。
    Phase A 为骨架构造器——模板固定词 + 随机实词，语义合理性在 Phase E
    升级为真正的条件/类比推理语料。
    """
    pool = [w for toks in short_sents for w in toks if is_clean_word(w)]
    if len(pool) < 2:
        return []
    out, n = [], len(pool)
    tpl_idx = 0
    while len(out) < synth_n:
        tpl_name, tpl = SYNTH_TEMPLATES[tpl_idx % len(SYNTH_TEMPLATES)]
        tpl_idx += 1
        a = pool[rng.integers(0, n)]
        b = pool[rng.integers(0, n)]
        if a == b:
            continue
        toks = [w if w != "{0}" else a for w in tpl]
        toks = [w if w != "{1}" else b for w in toks]
        out.append({"tpl": tpl_name, "sentence": toks})
    return out


# ════════════════════════════════════════════════════════════════
#  统计 / 验收
# ════════════════════════════════════════════════════════════════

def stats_report(sents):
    lens = [len(t) for t in sents]
    n_unk_sent = sum(UNK in t for t in sents)
    freq = Counter(t for toks in sents for t in toks)
    n_tok = sum(lens)
    rel_covered = sum(
        1 for t in sents
        if any(m in "".join(x for x in t if x not in PUNCT) for m in RELATION_MARKS)
    )
    return {
        "n_sent": len(sents),
        "len_min": min(lens), "len_mean": round(sum(lens) / max(1, len(sents)), 1),
        "len_max": max(lens),
        "sent_with_unk": n_unk_sent,
        "sent_with_unk_ratio": round(n_unk_sent / max(1, len(sents)), 4),
        "token_total": n_tok,
        "vocab": len(freq),
        "token_cover": round(sum(freq[w] for w, _ in freq.most_common(3000)) / max(1, n_tok), 4),
        "rel_mark_sent_ratio": round(rel_covered / max(1, len(sents)), 4),
        "top20": [f"{w}:{c}" for w, c in freq.most_common(20)],
    }


def purity_check(stage, items, kind):
    """验收：基础集唯一、无 UNK/停用/标点污染。返回 (ok, issues)。"""
    issues = []
    # 唯一性
    if kind in ("vocab", "bigrams", "short", "complex"):
        seen = set()
        for it in items:
            key = tuple(it) if isinstance(it, list) else it
            if key in seen:
                issues.append("duplicate")
                break
            seen.add(key)
    # 污染检查
    def check_tokens(seq):
        return [t for t in seq if t == UNK or t in STOPWORDS or t in PUNCT]
    if kind == "vocab":
        bad = check_tokens(items)
        if bad:
            issues.append(f"bad_tokens={bad[:5]}")
    elif kind == "bigrams":
        for p in items:
            if not (is_clean_word(p[0]) and is_clean_word(p[1])):
                issues.append(f"bad_bigram={p}")
                break
    else:
        for seq in items:
            if UNK in seq:
                issues.append("has_unk")
                break
    return not issues, issues


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    print(f"  写 {path}（{path.stat().st_size / 1e6:.2f}MB）")


def build_train(uniq, repeat, rng, shuffle=True):
    """跟读重复：唯一集 × repeat 次 → 训练序列（默认打乱次序）。"""
    seq = uniq * repeat
    if shuffle:
        idx = rng.permutation(len(seq))
        seq = [seq[i] for i in idx]
    return seq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true", help="只统计语料结构，不写文件")
    ap.add_argument("--corpus", type=str, default=None, help="显式指定原料库路径")
    ap.add_argument("--vocab", type=int, default=2000, help="Stage 0 词表规模")
    ap.add_argument("--bigrams", type=int, default=12000, help="Stage 1 词组规模")
    ap.add_argument("--short", type=int, default=30000, help="Stage 2 短句规模")
    ap.add_argument("--complex", type=int, default=15000, help="Stage 3 复杂句规模")
    ap.add_argument("--pairs", type=int, default=20000, help="Stage 4 句对规模")
    ap.add_argument("--synth", type=int, default=5000, help="Stage 5 推理句规模")
    ap.add_argument("--repeat", type=int, default=10, help="跟读重复率（≥10）")
    ap.add_argument("--max_len", type=int, default=8, help="Stage 2 短句最大词数")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = __import__("numpy").random.default_rng(args.seed)
    sents = load_corpus(args.corpus)
    print(f"语料: {len(sents)} 句")
    base = stats_report(sents)
    print("[语料基准] " + json.dumps(base, ensure_ascii=False))

    if args.stats:
        return

    print("\n=== Stage 0 词表 ===")
    vocab = extract_stage0(sents, args.vocab)
    ok, issues = purity_check("stage0", vocab, "vocab")
    print(f"  抽取 {len(vocab)} 词；纯净={ok} {issues}")

    print("\n=== Stage 1 词组 ===")
    bigrams = extract_stage1(sents, args.bigrams)
    ok, issues = purity_check("stage1", bigrams, "bigrams")
    print(f"  抽取 {len(bigrams)} 对；纯净={ok} {issues}")
    print("  样例:", bigrams[:10])

    print("\n=== Stage 2 短句（≤%d 词、无 UNK）===" % args.max_len)
    short = extract_stage2(sents, args.max_len, args.short)
    ok, issues = purity_check("stage2", short, "short")
    print(f"  抽取 {len(short)} 句；纯净={ok} {issues}")
    if short:
        print("  句长分布:", dict(Counter(len(s) for s in short)))
        print("  样例:", short[:5])

    print("\n=== Stage 3 复杂句（关系标记）===")
    complex_s = extract_stage3(sents, args.complex)
    ok, issues = purity_check("stage3", complex_s, "complex")
    print(f"  抽取 {len(complex_s)} 句；纯净={ok} {issues}")
    if complex_s:
        joined = ["".join(s) for s in complex_s]
        marks = Counter(m for j in joined for m in RELATION_MARKS if m in j)
        print("  关系标记覆盖:", dict(marks.most_common(12)))
        print("  样例:", complex_s[:5])

    print("\n=== Stage 4 句对（同段相邻子句）===")
    pairs = extract_stage4(sents, args.pairs)
    ok, issues = purity_check("stage4", pairs, "pairs")
    print(f"  抽取 {len(pairs)} 对；纯净={ok} {issues}")
    if pairs:
        print("  样例:", pairs[:5])

    print("\n=== Stage 5 推理（模板构造）===")
    synth = extract_stage5(short, args.synth, rng)
    print(f"  构造 {len(synth)} 句（关系标记句）")
    if synth:
        tpl_dist = Counter(x["tpl"] for x in synth)
        print("  模板分布:", dict(tpl_dist))

    # ── 写出：基础集（唯一） + 跟读训练序列（重复 repeat 次） ──
    print("\n=== 写出 data/curriculum/ ===")
    save_json(OUT / "stage0_vocab.json", vocab)
    save_json(OUT / "stage1_bigrams.json", bigrams)
    save_json(OUT / "stage2_sents.json", short)
    save_json(OUT / "stage3_sents.json", complex_s)
    save_json(OUT / "stage4_pairs.json", pairs)
    save_json(OUT / "stage5_sents.json", [x["sentence"] for x in synth])
    save_json(OUT / "stage5_meta.json",
              {"templates": [x["tpl"] for x in synth]})

    save_json(OUT / "train_stage0.json", build_train(vocab, args.repeat, rng))
    save_json(OUT / "train_stage1.json", build_train(bigrams, args.repeat, rng))
    save_json(OUT / "train_stage2.json", build_train(short, args.repeat, rng))
    save_json(OUT / "train_stage3.json", build_train(complex_s, args.repeat, rng))
    save_json(OUT / "train_stage4.json", build_train(pairs, args.repeat, rng))
    save_json(OUT / "train_stage5.json", build_train([x["sentence"] for x in synth],
                                                     args.repeat, rng))

    meta = {
        "desc": "v2.0 分级纯净数据（数据专门化基建 Phase A）",
        "source": CORPUS.name,
        "repeat": args.repeat,
        "n": {"stage0": len(vocab), "stage1": len(bigrams), "stage2": len(short),
              "stage3": len(complex_s), "stage4": len(pairs), "stage5": len(synth)},
        "seed": args.seed,
    }
    save_json(OUT / "meta.json", meta)
    print("\nPhase A 完成。验收要点：各 Stage 纯净性见上方打印；重复率 = %d。" % args.repeat)


if __name__ == "__main__":
    main()
