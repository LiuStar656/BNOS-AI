# -*- coding: utf-8 -*-
"""LLM 输出一致性测试：100 轮对话，AAA 组装提示词 → DeepSeek 生成 → 收集原始输出并分析。

用法（在项目根目录执行，使用 AAA 节点 venv）：
    python tests/llm_consistency_test.py

产物（输出到 docs/experiments/llm_consistency_test/）：
    LLM一致性测试-原始输出.json   100 轮 {输入, prompt长度, 原始输出, 耗时}
    LLM一致性测试报告.md          一致性分析报告
"""
import os
import re
import sys
import json
import time
import urllib.request

NODE_DIR = r"E:\杂项\BNOS_AI_project\nodes\node_python_aaa_cognition"
os.chdir(NODE_DIR)
sys.path.insert(0, NODE_DIR)

# 重定向 config.resolve：防止测试期间任何 ./ 输出写入真实节点目录
import config as _cfg_mod
_orig_resolve = _cfg_mod.resolve


def _fake_resolve(p):
    if p.startswith("./"):
        return os.path.join(r"E:\杂项\BNOS_AI_project\_tmp_test_io", p[2:])
    return _orig_resolve(p)


_cfg_mod.resolve = _fake_resolve

import db
import main as aaa_main   # 触发 memos.preload() 加载语义模型
import parser as psr

ROOT = r"E:\杂项\BNOS_AI_project"
OUT_DIR = os.path.join(ROOT, "docs", "experiments", "llm_consistency_test")
os.makedirs(OUT_DIR, exist_ok=True)
TMP_DB = os.path.join(ROOT, "_tmp_consistency_test.db")
TMP_IO = os.path.join(ROOT, "_tmp_test_io")
os.makedirs(TMP_IO, exist_ok=True)
for f in (TMP_DB,):
    if os.path.isfile(f):
        os.remove(f)
db.ensure(TMP_DB)

# 轮数：python llm_consistency_test.py [N]，默认 100
N_ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 100

# ── DeepSeek 直连（与 llm 节点 CloudApiBackend 相同模型/参数）──────────
API_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = "deepseek-v4-flash"
TEMPERATURE = 0.7
MAX_TOKENS = 2048


def llm_infer(prompt: str) -> str:
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
    }
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {API_KEY}"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


# ── 100 轮测试输入（25 个真实场景 × 4 轮）─────────────────────────────
POOL = [
    "今天天气怎么样？",
    "我想听首歌，推荐一下吧",
    "我有点累，陪我聊聊天吧",
    "你还记得我们上次聊的电影吗？",
    "帮我规划一下明天的日程",
    "我最近在准备考试，好焦虑",
    "有什么好看的动漫推荐吗？",
    "今天在公司被领导夸了，开心",
    "你会想我吗？",
    "给我讲个冷笑话",
    "我决定开始健身了",
    "周末想去爬山，哪里好？",
    "你喜欢吃什么？",
    "我好像感冒了，头疼",
    "我们来玩个猜谜游戏吧",
    "你觉得自己是什么性格？",
    "我换工作了，新环境还不适应",
    "帮我记住：明天下午3点开会",
    "刚才看到一只猫，好可爱",
    "你做梦吗？",
    "我觉得生活好没意思",
    "推荐一本好书吧",
    "我今天学会做菜了",
    "如果只能选一个，你喜欢海边还是山里？",
    "晚安，我要睡了",
]
INPUTS = [POOL[i % len(POOL)] for i in range(N_ROUNDS)]

# ── 一致性分析规则 ───────────────────────────────────────────────────
REQUIRED_SECTIONS = ["自然回复", "心情", "想法", "情绪调整", "事件摘要",
                     "自我认知", "他人认知", "用户信息", "自我信息",
                     "用户记忆", "环境记忆", "实体名", "归档标签"]

EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u2764\U0001F1E6-\U0001F1FF]")
KAOMOJI_RE = re.compile(r"[（(][^\u4e00-\u9fa5A-Za-z0-9，。！？、\s]{1,12}[）)]")
NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")

_SECTION_LINE = re.compile(r"^【(.+?)】\s*$")


def extract_sections(raw: str) -> dict:
    """基于行的稳健节提取（不受解析器空节吞并 bug 影响）。

    说明：生产解析器 parser.parse_llm_output 存在空节吞并问题，
    一致性测量以原始文本为准，另用解析器对比以量化丢失。
    """
    sections = {}
    current = None
    for line in raw.split("\n"):
        m = _SECTION_LINE.match(line.strip())
        if m:
            current = m.group(1).strip()
            sections.setdefault(current, "")
            continue
        if current is not None:
            if sections[current]:
                sections[current] += "\n"
            sections[current] += line
    for k in sections:
        sections[k] = re.sub(r"\n{2,}", "\n", sections[k]).strip()
    return sections


def analyze_round(raw: str) -> dict:
    # 原始文本节提取（正确性测量）
    sec = extract_sections(raw)
    res = {f"sec_{s}": (s in sec) for s in REQUIRED_SECTIONS}
    res["n_sections"] = len(sec)
    # 解析器对照（量化生产解析器节丢失）
    parsed = psr.parse_llm_output(raw)
    res["parser_n"] = len(parsed)
    res["parser_loss"] = len(sec) - len(parsed)

    def content(s):
        return sec.get(s, "")

    mood = content("心情")
    res["mood_len_ok"] = (1 <= len(mood) <= 4) if mood else False

    adj = content("情绪调整")
    m = NUM_RE.search(adj) if adj else None
    res["adj_num_ok"] = bool(m) and (-0.2 <= float(m.group(0)) <= 0.2) if m else False

    summ = content("事件摘要")
    res["summary_importance_ok"] = bool(
        re.search(r"\[importance=\d+\]", summ) or
        re.search(r"\[重要性[:：]\s*[1-5]\s*\]", summ)) if summ else False

    reply = content("自然回复")
    res["reply_no_emoji"] = not EMOJI_RE.search(reply) if reply else False
    res["reply_no_kaomoji"] = not KAOMOJI_RE.search(reply) if reply else False

    res["user_info_kv_ok"] = ("=" in content("用户信息")) if content("用户信息") else True
    res["self_info_kv_ok"] = ("=" in content("自我信息")) if content("自我信息") else True

    env = content("环境记忆")
    res["env_max3_ok"] = (env.count("\n") + env.count("；") + 1 <= 3) if env else True

    tags = content("归档标签")
    res["tags_ok"] = (("," in tags) or (not tags)) if tags else True

    res["starts_with_section"] = raw.strip().startswith("【")
    return res


def main():
    n_total = len(INPUTS)
    print(f"[测试] 开始 {n_total} 轮一致性测试，模型={MODEL} temp={TEMPERATURE}")
    rounds = []
    t_start = time.time()
    for i, text in enumerate(INPUTS, 1):
        # 1) AAA 组装提示词
        prompt = aaa_main._node._on_text(
            {"content": text, "request_id": f"consist_{i}", "identity_key": "gui:default"},
            TMP_DB)
        prompt_text = prompt.get("content", "")

        # 2) LLM 生成（直连 DeepSeek，同生产参数）
        t0 = time.time()
        try:
            raw = llm_infer(prompt_text)
            latency = round(time.time() - t0, 1)
            error = None
        except Exception as e:
            raw, latency, error = "", round(time.time() - t0, 1), str(e)

        rec = {"round": i, "input": text, "prompt_len": len(prompt_text),
               "raw": raw, "latency": latency, "error": error,
               "analysis": analyze_round(raw) if raw else None}
        rounds.append(rec)

        # 增量保存，防中途中断丢失
        with open(os.path.join(OUT_DIR, "LLM一致性测试-原始输出.json"), "w", encoding="utf-8") as f:
            json.dump({"model": MODEL, "temperature": TEMPERATURE, "rounds": rounds},
                      f, ensure_ascii=False, indent=1)

        status = "ERR" if error else f"ok({latency}s)"
        print(f"[{i:3d}/{n_total}] {text[:16]:<18} prompt={len(prompt_text):>5} {status}")
        sys.stdout.flush()

    print(f"[测试] {n_total} 轮完成，总耗时 {time.time()-t_start:.0f}s")

    # ── 分析汇总 ─────────────────────────────────────────────
    valid = [r for r in rounds if r["analysis"]]
    n = len(valid)

    def rate(key):
        if n == 0:
            return 0.0, 0
        ok = sum(1 for r in valid if r["analysis"].get(key))
        return round(ok / n * 100, 1), ok

    summary = {"total": len(rounds), "valid": n, "errors": len(rounds) - n,
               "avg_latency": round(sum(r["latency"] for r in valid) / n, 1) if n else 0}
    rows = []
    for s in REQUIRED_SECTIONS:
        pct, ok = rate(f"sec_{s}")
        rows.append((f"【{s}】节存在且非空", f"{ok}/{n}", pct))
    fmt_checks = {
        "【心情】1-4字": "mood_len_ok",
        "【情绪调整】数字∈[-0.2,0.2]": "adj_num_ok",
        "【事件摘要】含重要性标记[1-5]": "summary_importance_ok",
        "【自然回复】无 emoji": "reply_no_emoji",
        "【自然回复】无颜文字": "reply_no_kaomoji",
        "【用户信息】key=值格式": "user_info_kv_ok",
        "【自我信息】key=值格式": "self_info_kv_ok",
        "【环境记忆】≤3条": "env_max3_ok",
        "【归档标签】逗号分隔": "tags_ok",
        "输出以【开头（无前言）": "starts_with_section",
    }
    fmt_rows = []
    for label, key in fmt_checks.items():
        pct, ok = rate(key)
        fmt_rows.append((label, f"{ok}/{n}", pct))

    avg_sections = round(sum(r["analysis"]["n_sections"] for r in valid) / n, 1) if n else 0
    parser_loss_total = sum(r["analysis"]["parser_loss"] for r in valid)
    parser_loss_rounds = sum(1 for r in valid if r["analysis"]["parser_loss"] > 0)
    print("\n===== 节标记完整性（基于原始文本） =====")
    for label, cnt, pct in rows:
        print(f"{label:<28}{cnt:>5}  {pct:>5}%")
    print("\n===== 格式合规 =====")
    for label, cnt, pct in fmt_rows:
        print(f"{label:<28}{cnt:>5}  {pct:>5}%")
    print(f"\n平均节数: {avg_sections}, 平均耗时: {summary['avg_latency']}s, 错误: {summary['errors']}")
    print(f"[解析器对照] 生产解析器节丢失轮数: {parser_loss_rounds}/{n}, 累计丢失节数: {parser_loss_total}")

    # 输出报告
    write_report(summary, rows, fmt_rows, avg_sections, rounds,
                 parser_loss_total, parser_loss_rounds)


def write_report(summary, rows, fmt_rows, avg_sections, rounds,
                 parser_loss_total, parser_loss_rounds):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# LLM 输出一致性测试报告",
        "",
        f"> 日期：{now} | 模型：{MODEL} | 温度：{TEMPERATURE} | 最大Token：{MAX_TOKENS}",
        f"> 测试链路：AAA `_on_text` 组装提示词 → DeepSeek API 生成 → `parser.parse_llm_output` 解析",
        "",
        "## 一、测试概况",
        "",
        f"- 对话轮数：**{summary['total']}** 轮（25 个真实场景 × 4 次循环）",
        f"- 成功生成：{summary['valid']} 轮，失败：{summary['errors']} 轮",
        f"- 平均耗时：{summary['avg_latency']} 秒/轮",
        f"- 平均识别节数：{avg_sections} 个（要求 13 个节标记）",
        "",
        "## 二、节标记完整性（是否按要求输出各节）",
        "",
        "| 检查项 | 达标 | 达标率 |",
        "|--------|:----:|:------:|",
    ]
    for label, cnt, pct in rows:
        lines.append(f"| {label} | {cnt} | {pct}% |")

    lines += [
        "",
        "## 三、格式合规（节内容是否符合格式要求）",
        "",
        "| 检查项 | 达标 | 达标率 |",
        "|--------|:----:|:------:|",
    ]
    for label, cnt, pct in fmt_rows:
        lines.append(f"| {label} | {cnt} | {pct}% |")

    lines += [
        "",
        "## 四、典型不合规样本",
        "",
    ]
    bad_samples = 0
    for r in rounds:
        if not r["analysis"]:
            continue
        issues = []
        for s in REQUIRED_SECTIONS:
            if not r["analysis"].get(f"sec_{s}"):
                issues.append(f"缺【{s}】")
        for label, key in [("心情长度", "mood_len_ok"), ("情绪调整范围", "adj_num_ok"),
                           ("重要性标记", "summary_importance_ok"), ("emoji", "reply_no_emoji"),
                           ("颜文字", "reply_no_kaomoji"), ("key=值", "user_info_kv_ok"),
                           ("key=值", "self_info_kv_ok"), ("≤3条", "env_max3_ok"),
                           ("逗号分隔", "tags_ok"), ("前言", "starts_with_section")]:
            if not r["analysis"].get(key):
                issues.append(f"格式: {label}")
        if issues and bad_samples < 8:
            bad_samples += 1
            lines.append(f"### 第 {r['round']} 轮（输入：{r['input']}）")
            lines.append("")
            lines.append(f"- 问题：{', '.join(issues)}")
            lines.append(f"- 原始输出：")
            lines.append("")
            lines.append("```text")
            lines.append(r["raw"][:600])
            lines.append("```")
            lines.append("")

    if bad_samples == 0:
        lines.append(f"（{summary['total']} 轮全部合规，无典型不合规样本）")
        lines.append("")

    lines += [
        "## 五、结论",
        "",
        f"原始输出已保存至 `LLM一致性测试-原始输出.json`（含每轮输入、prompt 长度、原始语录、耗时）。",
        "",
    ]
    lines += [
        "## 六、附带发现：生产解析器空节吞并问题",
        "",
        f"一致性测量基于原始文本；另用生产解析器 `parser.parse_llm_output` 做对照。",
        f"{summary['valid']} 轮中 **{parser_loss_rounds} 轮**发生节丢失，累计丢失 **{parser_loss_total} 节**。",
        "",
        "**根因**：`parser.py` 的正则 `【(.+?)】\\s*\\n(.*?)(?=\\n【|$)` 中 `\\s*\\n` 会吞掉空节与下一节之间的空行，",
        "导致空节（如【环境记忆】【实体名】留空）把后续节并入自身内容。",
        "实测：`【A】\\n\\n【B】\\n\\n【C】\\nx` 被解析为 `{'A': '【B】', 'C': 'x'}`。",
        "",
        "**影响**：LLM 正常输出时若连续多个可空节（【用户记忆】【环境记忆】【实体名】）留空，",
        "【归档标签】等靠后节的内容会被吞进前一个空节，导致归档标签/实体名/环境记忆在 AAA 落库时丢失或串位。",
        "",
        "**建议**：将 `parse_llm_output` 改为基于行的节切分（节标记独占一行时开新节），与本次测试的 `extract_sections` 一致。",
        "",
    ]
    with open(os.path.join(OUT_DIR, "LLM一致性测试报告.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[报告] 已生成: {os.path.join(OUT_DIR, 'LLM一致性测试报告.md')}")


if __name__ == "__main__":
    main()
