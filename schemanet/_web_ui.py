# -*- coding: utf-8 -*-
"""定式网络 Web 前端（2026-08-11）：拼音教学台——浏览器里教守一说话。

交互（老师=用户，守一=网络）：
  · 输入框（空格分隔音节，如 "jiao ba ba" / "b a"）：
      [教学] 逐音素注入教学一次（说+零食——时序=结构）→ 自动问它看反应
      [问它] 整串一次注入检索（注意收窄 wta=4——当前论元胜出）
  · 奖惩按钮（倍率可手动输入）：
      [奖励 +2.0×倍率] / [惩罚 −2.0×倍率]（惩罚 factor=3.0 更狠）
      兑现最近教学建立的资格迹配对（延迟归因）
  · 对话显示屏：聊天式滚动（你 / 守一 / 系统）

零依赖：Python 标准库 http.server + 单页 HTML。
加载最新 v54.6 快照（拼音音位级——已教学 jiao baba/jiao mama 各 30 次）。

用法：python _web_ui.py [--port 8000]
"""

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

from schema_net import build_pulse
from snapshot import load_snapshot
from _exp_pinyin import (PHONEMES, SHENGMU, YUNMU, WORD_PH, JIAO,
                         teach_once, recall, edge_weight, count_edges,
                         AMP_VERB, AMP_ARG, REWARD)

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"

# ────────────────────────────────────────────────────────────
#  网络会话（全局单例 + 锁）
# ────────────────────────────────────────────────────────────

ng = None
pats = None
n2w = None
lock = threading.Lock()
say_log = []            # 最近一次教学的关键边日志
RUN = None              # 加载的快照路径（退出保存的 data_fp）
VOCAB = []
CURSOR = 0


def load_latest():
    """加载最新可用快照：54.12 重建词表基座链（version ≥ (54,12) 且
    parent ∈ {53.0 基座, 54.12 重建基座}）——排除旧词表前端存档
    （v55.0-55.2 parent=54.6——重建前残留）与中间实验快照（54.8-54.11）。
    版本比较用 (major, minor) 元组——float 比较会把 54.9 误判 > 54.12。"""
    from snapshot import snapshot_index
    global ng, pats, n2w, RUN, VOCAB, CURSOR

    def vkey(v):
        mj, mn = v.split(".")
        return (int(mj), int(mn))

    rows = [r for r in snapshot_index()
            if vkey(r["version"]) >= (54, 12)
            and r.get("parent_version") in ("53.0", "54.12")]
    if not rows:
        raise SystemExit("未找到重建基座链快照——先跑 python _exp_rebuild_vocab.py")
    RUN = RUNS / max(rows, key=lambda r: vkey(r["version"]))["dir"]
    ng, vocab, pats, cursor = load_snapshot(RUN)
    VOCAB, CURSOR = vocab, int(cursor)
    n2w = {int(x): w for w, ns in pats.items() for x in ns}
    return RUN.name


def parse_syllables(text):
    """拼音串 → 音素序列。按空格分词，每 token 一个音节：
    最长声母匹配 + 剩余韵母（zh/ch/sh 优先）→ [声母, 韵母]；
    纯韵母 token → [韵母]。返回 (音素列表, 未解析 token 列表)。"""
    out, bad = [], []
    for tok in text.strip().split():
        hit = None
        for sm in sorted(SHENGMU, key=len, reverse=True):
            if tok.startswith(sm) and tok[len(sm):] in YUNMU:
                hit = [sm, tok[len(sm):]]
                break
        if hit:
            out += hit
        elif tok in YUNMU:
            out.append(tok)
        else:
            bad.append(tok)
    return out, bad


def seg_words(text):
    """汉字贪心分词：每位置尝试最长词（词表最长 4 字），否则单字。
    "叫爸爸" → [叫, 爸爸]；"你好" → [你好]；"小猫吃鱼" → [小猫?, 吃, 鱼]。
    返回 (词列表, 未收录项列表)。"""
    out, bad = [], []
    i = 0
    while i < len(text):
        hit = None
        for L in range(min(4, len(text) - i), 0, -1):
            w = text[i:i + L]
            if w in pats:
                hit = w
                break
        if hit:
            out.append(hit)
            i += len(hit)
        else:
            bad.append(text[i])
            i += 1
    return out, bad


def parse_text(text):
    """输入解析：拼音音节优先（jiao ba ba）；失败则回退汉字（贪心分词
    ——"叫爸爸" → [叫, 爸爸]——词表词优先、单字兜底）。
    返回 (kind, items, bad)——kind ∈ {"phon", "word"}；
    均失败返回 (None, None, None)。"""
    phs, bad = parse_syllables(text)
    if phs:
        return "phon", phs, []
    if all("\u4e00" <= ch <= "\u9fff" or ch == " " for ch in text):
        words, bad = seg_words(text.replace(" ", ""))
        if words:
            return "word", words, bad
    return None, None, None


def teach(text):
    """教学一次：只说（不学——da=0）——听后奖惩才是学习开关。
    拼音（逐音素注入）或汉字（贪心分词 → 词模式注入）都支持。"""
    global say_log
    kind, items, bad = parse_text(text)
    if items is None:
        return {"error": "无法解析：拼音音节（jiao ba ba）或词表汉字（叫爸爸）"}, None, None
    say_log = []
    with lock:
        ng.v = np.zeros((ng.n, ng.slots))
        ng.spikes = np.zeros(ng.n)
        ng.pre_trace = np.zeros(ng.n)
        ng.da = 0.0                        # 清零残留 DA——只说不动学习
        ng._elig_pairs.clear()             # 清旧资格迹——本轮教学重新打标
        if kind == "phon":
            verb_len = 2 if items[0] == "j" and len(items) > 2 else 0
            for i, ph in enumerate(items):
                ng.spikes = np.zeros(ng.n)
                amp = AMP_ARG if i >= verb_len else AMP_VERB
                ng.step(build_pulse(ng.n, pats[ph], amp), slot=0)
                ng.spikes = np.zeros(ng.n)
                ng.step(np.zeros(ng.n), slot=0)
        else:                              # word：词模式注入（每词一拍+空拍）
            for w in items:
                ng.spikes = np.zeros(ng.n)
                ng.step(build_pulse(ng.n, pats[w], 1.0), slot=0)
                ng.spikes = np.zeros(ng.n)
                ng.step(np.zeros(ng.n), slot=0)
        # 句内序列配对（引擎的空拍打断逻辑对"逐音素教学"失效——这里在
        # 教学协议末尾统一打标——**先问它再看反应，ask_chain 的注入拍会
        # 清配对（新行为窗口）——打标必须在最后**）：相邻项 → 资格迹
        # ——奖惩兑现对象（Izhikevich Δw = DA × e——延迟归因——老师说→听后奖惩）
        resp = ask_chain(items, kind=kind, wta_k=4)   # 说后先看它现在怎么反应
        for i in range(len(items) - 1):
            for a in pats[items[i]]:
                for b in pats[items[i + 1]]:
                    if int(a) != int(b):
                        ng._elig_pairs[(int(a), int(b))] = 1.0
        pairs = [(items[i], items[i + 1]) for i in range(len(items) - 1)]
        say_log = [(p, q, edge_weight(ng, pats, p, q)) for p, q in pairs]
    return resp, say_log, bad


def ask(text, wta_k=4):
    kind, items, bad = parse_text(text)
    if items is None:
        return {"error": "无法解析：拼音音节（jiao ba ba）或词表汉字（叫爸爸）"}, None
    with lock:
        resp = ask_chain(items, kind=kind, wta_k=wta_k)
    return resp, bad


def ask_chain(items, kind="phon", wta_k=4):
    """整串一次注入检索（注意收窄——当前论元胜出）→ 发放链。
    显示按音素表顺序排序（jiaomama 读出顺序一致），空拍无发放显示 —。
    kind="word" 时显示词名（词模式神经元在 n2w——通用）。"""
    ph_order = {p: i for i, p in enumerate(PHONEMES)}

    def fmt(idxs):
        ws = {n2w.get(int(x)) for x in idxs}
        ws = {w for w in ws if w}
        if not ws:
            return "—"
        if kind == "phon":
            return "".join(sorted(ws, key=lambda x: ph_order.get(x, 99)))
        return "".join(sorted(ws))

    gate, wta_old = ng.learn_gate, ng.wta_k
    ng.learn_gate = False
    ng.wta_k = wta_k
    ng.v = np.zeros((ng.n, ng.slots))
    ng.spikes = np.zeros(ng.n)
    ng.pre_trace = np.zeros(ng.n)
    idxs = [x for ph in items for x in pats[ph]]
    ng.step(build_pulse(ng.n, idxs, AMP_ARG), slot=0)
    chain = [fmt(np.where(ng.spikes > 0)[0])]
    for _ in range(10):
        ng.step(np.zeros(ng.n), slot=0)
        now = fmt(np.where(ng.spikes > 0)[0])
        chain.append(now)
        if now == "—":
            break
    ng.learn_gate = gate
    ng.wta_k = wta_old
    return chain


def reward(rate):
    """奖惩（学习开关——DA 门控）：release_da(±2.0×倍率)——兑现
    最近教学累积的资格迹配对（延迟归因——老师说→听后奖惩）。
    返回 da、兑现配对数、剩余配对数。"""
    da = REWARD * float(rate)
    with lock:
        before = len(ng._elig_pairs)
        ng.release_da(da)
        after = len(ng._elig_pairs)
        n_edge = count_edges(ng)
    return da, before, after, n_edge


def sleep(keep_ratio=0.2, shrink=0.5):
    """睡眠巩固（用户协议 2026-08-11）：保留突触权重前 20%，其余按比例
    减少，重置神经元兴奋度。生物对应：睡眠中的突触稳态（synaptic
    scaling——强边保持、弱边收缩——用进废退巩固）+ 唤醒后兴奋度归零。
    顺带清理 0 权重虚边（历史 da=0 写入的残留键）。"""
    with lock:
        # 收集所有正权重边
        ws = [(w, i, j) for i in range(ng.n)
              for j, w in ng.W_out[i][0].items() if w > 0]
        n_total = len(ws)
        if not ws:
            return {"edges": 0, "th": 0.0, "kept": 0, "shrunk": 0,
                    "cleaned": 0, "da": 0.0}
        th = float(np.percentile([w for w, _, _ in ws],
                                 100 * (1 - keep_ratio)))
        kept = shrunk = cleaned = 0
        for i in range(ng.n):
            row = ng.W_out[i][0]
            for j in list(row.keys()):
                w = row[j]
                if w <= 0.0:
                    del row[j]                 # 清理 0 权重虚边
                    cleaned += 1
                elif w >= th:
                    kept += 1                  # 前 20%——保留
                else:
                    row[j] = w * shrink        # 其余——按比例减少
                    shrunk += 1
        # 重置神经元兴奋度（膜电位/发放/疲劳/痕迹/资格迹/调质）
        ng.v[:] = 0.0
        ng.spikes[:] = 0.0
        ng.fat[:] = 0.0
        ng.pre_trace[:] = 0.0
        ng._elig_pairs.clear()
        ng._prev_inp = set()
        ng._ctx_inp = set()
        ng._ctx_idle = 0
        ng.da = 0.0
        return {"edges": n_total, "th": round(th, 3), "kept": kept,
                "shrunk": shrunk, "cleaned": cleaned, "da": 0.0}


def clear_net():
    """全清空（除神经元外）：所有突触边、膜电位/发放/疲劳/痕迹、
    资格迹/上下文、轨道、驱动/信号、唤醒计数、调质——全部归零。
    保留：神经元分配（音素模式 pats/cursor/vocab 不动）——
    回到"零边起点"，但新词无需重新分配。"""
    with lock:
        n_edge_cleared = 0
        for i in range(ng.n):
            row = ng.W_out[i][0]
            if row:
                n_edge_cleared += len(row)
                row.clear()
        ng.v[:] = 0.0
        ng.spikes[:] = 0.0
        ng.fat[:] = 0.0
        ng.pre_trace[:] = 0.0
        ng._elig_pairs.clear()
        ng._prev_inp = set()
        ng._ctx_inp = set()
        ng._ctx_idle = 0
        ng.track_map = {}
        ng._track_slots = set()
        ng._track_readout = {}
        ng._track_readout_nwords = {}
        if hasattr(ng, "_track_slots_list"):
            ng._track_slots_list = np.array([], dtype=np.int64)
        ng._drive_any[:] = 0.0
        if hasattr(ng, "_sig_spikes"):
            ng._sig_spikes[:] = 0.0
        if hasattr(ng, "slot_freq"):
            ng.slot_freq[:] = 0
        if hasattr(ng, "elig"):
            ng.elig[:] = 0.0
        if hasattr(ng, "_punish_cands"):
            ng._punish_cands = set()
        ng.da = 0.0
        ng.da_expected = 0.0
        ng.last_rpe = 0.0
    return {"cleared": n_edge_cleared, "n": ng.n,
            "phonemes": len([p for p in PHONEMES if p in pats])}


def save_net(tag="web_ui 交互教学快照"):
    """退出保存：内存权重 → 快照（继承 v54.6 基座——新版本）。
    注意：state() 自带锁——不能在本函数持锁时调用（非重入锁死锁）。"""
    from snapshot import save_snapshot
    st = state()                     # state 内部加锁
    with lock:
        out = save_snapshot(ng, parent="54.12", vocab=VOCAB, pats=pats,
                            cursor=CURSOR, metrics={"web_ui": st},
                            tag=tag, data_fp=str(RUN))
    return out


def state():
    with lock:
        n_edge = count_edges(ng)
        da = float(ng.da)
    return {"edges": n_edge, "da": da,
            "phonemes": len([p for p in PHONEMES if p in pats])}


# ────────────────────────────────────────────────────────────
#  HTTP 服务
# ────────────────────────────────────────────────────────────

PAGE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>定式网络 · 守一（拼音教学台）</title>
<style>
  :root { --bg:#0f1115; --panel:#171a21; --line:#262b36; --tx:#e8eaf0;
          --dim:#8a93a6; --acc:#4f8cff; --ok:#3ecf8e; --bad:#ff6b6b; }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--bg); color:var(--tx);
         font:14px/1.6 "Microsoft YaHei", system-ui, sans-serif;
         height:100vh; display:flex; flex-direction:column; }
  header { padding:12px 20px; border-bottom:1px solid var(--line);
           display:flex; align-items:baseline; gap:14px; }
  header h1 { font-size:17px; font-weight:600; }
  header .sub { color:var(--dim); font-size:12px; }
  #state { margin-left:auto; color:var(--dim); font-size:12px; }
  #state b { color:var(--acc); }
  #screen { flex:1; overflow-y:auto; padding:18px 20px;
            display:flex; flex-direction:column; gap:10px; }
  .msg { max-width:76%; padding:9px 13px; border-radius:12px;
         white-space:pre-wrap; word-break:break-all; font-size:14px; }
  .msg.you { align-self:flex-start; background:#1e2430; border:1px solid var(--line); }
  .msg.you .who { color:var(--dim); font-size:11px; margin-bottom:2px; }
  .msg.sy { align-self:flex-end; background:#17324f; border:1px solid #22446b; }
  .msg.sy .who { color:#7fb0ff; font-size:11px; margin-bottom:2px; }
  .msg.sys { align-self:center; color:var(--dim); font-size:12px;
             background:#1a1d24; border:1px dashed var(--line);
             padding:4px 14px; border-radius:8px; }
  .msg .edge { color:#9db8e8; font-size:12px; }
  .msg .warn { color:var(--bad); font-size:12px; }
  #dock { border-top:1px solid var(--line); padding:12px 20px;
          display:flex; flex-direction:column; gap:8px; }
  .row { display:flex; gap:8px; align-items:center; }
  #inp { flex:1; background:#12151c; border:1px solid var(--line);
         color:var(--tx); border-radius:8px; padding:9px 12px; font-size:14px; }
  #inp:focus { outline:none; border-color:var(--acc); }
  button { border:none; border-radius:8px; padding:9px 16px; cursor:pointer;
           font-size:13px; color:#fff; }
  #btnTeach { background:var(--acc); }
  #btnAsk { background:#33415c; }
  #rate { width:64px; background:#12151c; border:1px solid var(--line);
          color:var(--tx); border-radius:8px; padding:8px 8px; text-align:center; }
  #btnReward { background:var(--ok); }
  #btnPunish { background:var(--bad); }
  .lab { color:var(--dim); font-size:12px; }
  .spacer { flex:1; }
</style>
</head>
<body>
<header>
  <h1>定式网络 · 守一</h1>
  <span class="sub">拼音教学台（重建词表基座 v54.12：常用字 3500 + 常用词 10000 + 音素 48）——输入 jiao ba ba 教它说话</span>
  <span id="state">边 <b id="sEdges">?</b> ｜ da <b id="sDa">?</b> ｜ 音素 <b id="sPh">?</b></span>
</header>

<div id="screen"></div>

<div id="dock">
  <div class="row">
    <input id="inp" placeholder='输入拼音音节（空格分隔）："jiao ba ba" / 单音素 "b a" / 词表汉字："你好"'
           autocomplete="off">
    <button id="btnTeach">教学</button>
    <button id="btnAsk">问它</button>
  </div>
  <div class="row">
    <span class="lab">奖惩倍率</span>
    <input id="rate" value="1.0" inputmode="decimal">
    <button id="btnReward">奖励 +2.0×倍率</button>
    <button id="btnPunish">惩罚 −2.0×倍率</button>
    <span class="spacer"></span>
    <span class="lab">教学=只说（听后奖惩才是学习开关）；问它=整串注入（注意收窄）</span>
  </div>
  <div class="row">
    <button id="btnSleep" style="background:#9b6bff">睡眠（保留前 20% 边 · 其余 ×0.5 · 重置兴奋度）</button>
    <button id="btnClear" style="background:#8a4a4a">清空（除神经元外全清）</button>
    <span class="spacer"></span>
    <button id="btnSave" style="background:#33415c">保存</button>
    <button id="btnExit" style="background:#555">退出并保存</button>
  </div>
</div>

<script>
const screen = document.getElementById('screen');
const inp = document.getElementById('inp');

function add(html, cls) {
  const d = document.createElement('div');
  d.className = 'msg ' + cls;
  d.innerHTML = html;
  screen.appendChild(d);
  screen.scrollTop = screen.scrollHeight;
  return d;
}
function you(html) { add(html, 'you'); }
function sy(html) { add(html, 'sy'); }
function sys(html) { add(html, 'sys'); }

async function post(url, body) {
  try {
    const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'},
                                body: JSON.stringify(body || {})});
    return r.json();
  } catch (e) {
    sys('<span class="warn">⚠ 连接失败：' + e + '（服务器未运行？按 F5 重试）</span>');
    throw e;
  }
}
window.addEventListener('error', ev =>
  sys('<span class="warn">⚠ 页面错误：' + ev.message + '</span>'));
window.addEventListener('unhandledrejection', ev =>
  sys('<span class="warn">⚠ 请求异常：' +
      ((ev.reason && ev.reason.message) || ev.reason) + '</span>'));
function refreshState() {
  fetch('/api/state').then(r=>r.json()).then(s => {
    document.getElementById('sEdges').textContent = s.edges;
    document.getElementById('sDa').textContent = s.da.toFixed(2);
    document.getElementById('sPh').textContent = s.phonemes;
  });
}
function fmtChain(chain) {
  return chain.map((c, i) => (i===0 ? '听' : '想') + i + ':' + c).join('  ');
}

async function doTeach() {
  const text = inp.value.trim();
  if (!text) return;
  you('<div class="who">老师</div>' + text);
  const r = await post('/api/teach', {text});
  if (r.error) { sys('<span class="warn">⚠ ' + r.error + '</span>'); return; }
  if (r.bad && r.bad.length) sys('<span class="warn">⚠ 未解析：' + r.bad.join(' ') + '</span>');
  let edge = '';
  if (r.edges && r.edges.length) {
    edge = '<div class="edge">强化边：' +
      r.edges.map(e => e[0]+'→'+e[1]+' = '+e[2][0].toFixed(2)).join('　') + '</div>';
  }
  sy('<div class="who">守一</div>' + r.resp.join('') + edge);
  refreshState();
}

async function doAsk() {
  const text = inp.value.trim();
  if (!text) return;
  you('<div class="who">老师（问它）</div>' + text);
  const r = await post('/api/ask', {text});
  if (r.error) { sys('<span class="warn">⚠ ' + r.error + '</span>'); return; }
  sy('<div class="who">守一</div>' + r.resp.join(''));
}

async function doReward(rate) {
  const r = await post('/api/reward', {rate: parseFloat(rate) || 1});
  const sign = r.da > 0 ? '+' : '';
  const verb = r.da > 0 ? '奖励' : '惩罚';
  let txt = verb + ' ' + sign + r.da.toFixed(2) + ' 发放';
  if (r.pairs > 0) txt += '（兑现 ' + r.pairs + ' 对资格迹配对——学习生效）';
  else txt += '（无待兑现配对——先按「教学」说一句）';
  sys(txt);
  refreshState();
}

async function doSleep() {
  const r = await post('/api/sleep');
  sys('睡眠：保留 ' + r.kept + ' 条强边（权重≥' + r.th + '），缩小 ' + r.shrunk +
      ' 条弱边（×0.5），清理 ' + r.cleaned + ' 条零边，神经元兴奋度已重置');
  refreshState();
}

async function doClear() {
  if (!confirm('清空除神经元外的全部内容？（边/资格迹/兴奋度/轨道/唤醒计数——神经元分配保留）')) return;
  const r = await post('/api/clear');
  sys('已清空 ' + r.cleared + ' 条边——零边起点（' + r.phonemes + ' 音素神经元保留）');
  refreshState();
}

async function doSave() {
  const r = await post('/api/save');
  sys(r.msg);
}

async function doExit() {
  const r = await post('/api/exit');
  sys(r.msg);
  sys('服务器即将退出——可关闭此页面');
}

document.getElementById('btnTeach').onclick = doTeach;
document.getElementById('btnAsk').onclick = doAsk;
inp.addEventListener('keydown', e => { if (e.key === 'Enter') doTeach(); });
document.getElementById('btnReward').onclick = () =>
  doReward(document.getElementById('rate').value);
document.getElementById('btnPunish').onclick = () =>
  doReward('-' + document.getElementById('rate').value);
document.getElementById('btnSleep').onclick = doSleep;
document.getElementById('btnClear').onclick = doClear;
document.getElementById('btnSave').onclick = doSave;
document.getElementById('btnExit').onclick = doExit;

sys('守一已苏醒（重建词表基座 v54.12）——教它说话：输入拼音音节按「教学」（只说）→ 听后按「奖励」或「惩罚」');
refreshState();
setInterval(refreshState, 3000);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            data = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")   # 防旧版缓存
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/api/state":
            self._send(state())
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        if self.path == "/api/teach":
            resp, edges, bad = teach(body.get("text", ""))
            if isinstance(resp, dict) and "error" in resp:
                self._send({"error": resp["error"]})      # 顶层错误——前端可判
            else:
                self._send({"resp": resp, "edges": edges, "bad": bad})
        elif self.path == "/api/ask":
            resp, bad = ask(body.get("text", ""))
            if isinstance(resp, dict) and "error" in resp:
                self._send({"error": resp["error"]})
            else:
                self._send({"resp": resp, "bad": bad})
        elif self.path == "/api/reward":
            try:
                rate = float(body.get("rate", 1.0))
            except Exception:
                rate = 1.0
            da, before, after, n_edge = reward(rate)
            self._send({"da": da, "pairs": before, "effected": after,
                        "edges": n_edge})
        elif self.path == "/api/sleep":
            self._send(sleep())
        elif self.path == "/api/clear":
            self._send(clear_net())
        elif self.path == "/api/save":
            out = save_net()
            self._send({"msg": f"已保存快照 {out.name}（退出或继续教学）",
                        "path": str(out)})
        elif self.path == "/api/exit":
            try:
                out = save_net("web_ui 退出保存")
                msg = f"已保存快照 {out.name}——守一入睡，服务器退出"
            except Exception as e:
                msg = f"保存失败：{e}"
            self._send({"msg": msg})
            # 响应发完后退出服务器（延迟——让响应送达浏览器）
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send({"error": "not found"}, 404)


def main():
    port = 8000
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    snap = load_latest()
    print(f"[守一] 加载快照 {snap} | n={ng.n} 边={count_edges(ng)}")
    print(f"[守一] 前端 http://127.0.0.1:{port}  （Ctrl+C 退出）")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
