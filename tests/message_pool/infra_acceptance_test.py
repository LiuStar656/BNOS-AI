# -*- coding: utf-8 -*-
"""消息池基础设施验收测试（不跑 LLM 实验，Fake LLM 覆盖批量链路）。

单元部分（不依赖 AAA 节点）：
    U1 事件总线：订阅/发布/异常隔离
    U2 消息池：入队 / 同人同文去重 / 单用户配额 / 优先级排序 / max_items
    U3 路由：@ 单个点名 / 多个点名 / 无点名
    U4 仲裁器：QUEUE（单一发言权 + 补位）/ DROP / INTERRUPT
    U5 采集器：events.jsonl / decisions.jsonl / evolution.json
    U6 话题报告：相互认知矩阵（n-agent 全覆盖：3 Agent 矩阵/双向判定/内容摘录）
       + 人格漂移（初始种子 vs 最终向量欧氏距离）+ E3 采集指标表
    U12 v6.6：P0-1 批次顺序事实源（seq 关联）/ P0-2 空 user_id 过滤 /
       P1-4 截断检测 / P1-5 末位偏置量化指标 / P1-6 演化阈值 30→10 /
       数据采集七项（memory_hits、silent_cognition、trajectory、
       cognition_timeline、@提及归因、位置对照、情绪关联）

集成部分（Fake LLM，不调真实 API）：
    I1 Agent 桥接：_on_pool_batch → prompt → Fake LLM → _on_parsed(batch_mode=True)
       → {action: reply|silent}；DB user_id 归属正确；静默轮也写事件摘要
    I2 平台 step：多 Agent 批处理、单步至多一条广播、决策落盘；
       避让机制：上一位广播发言者下批被跳过（防自言自语，@ 点名豁免）
    I3 话题轮数：agent 发言回投消息池，达到 topic_rounds 后平台宣告话题结束
    I4 避让公平性：无点名多轮后两 Agent 都有发言、无同一 Agent 连续广播

用法（项目根目录，使用 AAA 节点 venv）：
    & nodes/node_python_aaa_cognition/venv/Scripts/python.exe tests/message_pool/infra_acceptance_test.py
"""
import os
import sys
import json
import sqlite3
import shutil

# ── AAA 节点路径与配置重定向（与 self_evolution_test 相同模式） ──
NODE_DIR = r"E:\杂项\BNOS_AI_project\nodes\node_python_aaa_cognition"
os.chdir(NODE_DIR)
sys.path.insert(0, NODE_DIR)

import config as _cfg_mod
_orig_resolve = _cfg_mod.resolve
TMP_IO = r"E:\杂项\BNOS_AI_project\_tmp_pool_platform"
if os.path.exists(TMP_IO):
    shutil.rmtree(TMP_IO, ignore_errors=True)
os.makedirs(TMP_IO, exist_ok=True)


def _fake_resolve(p):
    if p.startswith("./"):
        return os.path.join(TMP_IO, p[2:])
    return _orig_resolve(p)


_cfg_mod.resolve = _fake_resolve

# 平台包（tests/message_pool/）
sys.path.insert(0, r"E:\杂项\BNOS_AI_project\tests")
from message_pool.event_bus import EventBus
from message_pool.message_pool import MessagePool
from message_pool.router import pick_speaker, find_mentions
from message_pool.arbiter import SpeechOutputArbiter, ArbiterPolicy
from message_pool.collector import ExperimentCollector

# ── 单元测试 ─────────────────────────────────────────────────
PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


print("== U1 事件总线 ==")
bus = EventBus()
got = []
bus.subscribe("ping", lambda **p: got.append(p))
bus.publish("ping", a=1)
bus.publish("other", a=2)
check("订阅事件收到", len(got) == 1 and got[0]["a"] == 1, repr(got))
bus.subscribe("ping", lambda **p: (_ for _ in ()).throw(RuntimeError("boom")))
bus.publish("ping", a=3)  # 异常订阅者不影响其他
check("订阅者异常隔离", len(got) == 2, repr(got))

print("== U2 消息池 ==")
pool = MessagePool(bus=None, dedup_window_s=60, per_user_quota=2)
m1 = pool.enqueue_input("大家好", user_id="userA", ts=1.0)
m2 = pool.enqueue_input("大家好", user_id="userA", ts=2.0)   # 窗口内重复 → None
m3 = pool.enqueue_input("大家好", user_id="userB", ts=3.0)   # 不同用户不重复
check("同人同文去重", m1 is not None and m2 is None and m3 is not None)
check("入队 2 条", len(pool) == 2)
pool.enqueue_input("高优先级", user_id="userC", priority=10, ts=4.0)
pool.enqueue_input("A1", user_id="userA", ts=5.0)
pool.enqueue_input("A2", user_id="userA", ts=6.0)
pool.enqueue_input("A3", user_id="userA", ts=7.0)   # 超配额
batch = pool.pop_all_inputs(max_items=10)
texts = [m.text for m in batch]
check("优先级消息先出", texts[0] == "高优先级", str(texts))
check("单用户配额 2 条", texts.count("A1") == 1 and "A3" not in texts, str(texts))
check("超配额消息留在队列", len(pool) == 2, str(len(pool)))
# 同优先级按时间正序：大家好(A,ts1) < 大家好(B,ts3) < A1(ts5)
ts_seq = [m.ts for m in batch if m.priority == 0]
check("批内时间正序（同优先级）", ts_seq == sorted(ts_seq), str(ts_seq))

print("== U3 路由 ==")
agents = ["agent:alpha", "agent:beta", "agent:gamma"]
targets, mentioned = pick_speaker(
    [{"content": "@alpha 早上好", "user_id": "userA"}], agents)
check("@ 单个点名优先", targets[0] == "agent:alpha" and mentioned == ["agent:alpha"],
      str(targets))
targets, mentioned = pick_speaker(
    [{"content": "@beta @gamma 你们好", "user_id": "userA"}], agents)
check("@ 多个点名按序", targets[:2] == ["agent:beta", "agent:gamma"], str(targets))
targets, mentioned = pick_speaker(
    [{"content": "大家好", "user_id": "userA"}], agents)
check("无点名全部参与", targets == agents and mentioned == [], str(targets))
check("别名点名（@alpha）", find_mentions("@alpha 在吗", ["agent:alpha"]) == ["agent:alpha"])

print("== U4 仲裁器 ==")
arb = SpeechOutputArbiter(bus=None, default_policy=ArbiterPolicy.QUEUE)
ok1 = arb.request_speech("agent:alpha", "第一条", priority=0)
ok2 = arb.request_speech("agent:beta", "第二条", priority=0)
ok3 = arb.request_speech("agent:gamma", "第三条", priority=0)
check("首个请求获得发言权", ok1 and arb.current_speaker == "agent:alpha")
check("QUEUE 后续请求排队", (not ok2) and (not ok3) and arb.queued == ["agent:beta", "agent:gamma"],
      str(arb.queued))
r = arb.release()
check("释放后补位（返回被释放者，补位者接管）",
      r["agent_id"] == "agent:alpha" and arb.current_speaker == "agent:beta",
      str(r))
arb.release()
arb.release()
check("排队全部放行后空", arb.current_speaker is None and not arb.queued)

arb2 = SpeechOutputArbiter(bus=None, default_policy=ArbiterPolicy.DROP)
a1 = arb2.request_speech("agent:alpha", "x")
a2 = arb2.request_speech("agent:beta", "y")
check("DROP 策略：发言中丢弃", a1 and (not a2) and arb2.current_speaker == "agent:alpha")

arb3 = SpeechOutputArbiter(bus=None, default_policy=ArbiterPolicy.QUEUE,
                           interrupt_priority=10)
arb3.request_speech("agent:alpha", "低优先级发言")
intr = arb3.request_speech("agent:beta", "打断", priority=20,
                           policy=ArbiterPolicy.INTERRUPT)
check("INTERRUPT 打断当前发言", intr and arb3.current_speaker == "agent:beta",
      str(arb3.current_speaker))

print("== U5 采集器 ==")
run_dir = os.path.join(TMP_IO, "runs", "20260808_000000_test", "run")
coll = ExperimentCollector(run_dir, gid="test")
coll.event(event="message_enqueued", user_id="userA", content="hi")
coll.decision(agent="agent:alpha", action="reply", content="你好",
              user_id="userA", 想法="打招呼", 心情="开心",
              personality={"warmth": 0.6}, mood=0.5)
coll.decision(agent="agent:alpha", action="silent", content="",
              user_id="userB", 想法="旁听", 心情="平静")
coll.set_rounds(3)
coll.chat(role="user", user_id="userA", content="hi")
coll.chat(role="agent", agent_id="agent:alpha", content="你好", round_no=1)
coll.write_evolution({"agent:alpha": {"end": {"warmth": 0.7},
                                      "other_cognition": {"userA": 2}}})
coll.close()
with open(os.path.join(run_dir, "events.jsonl"), encoding="utf-8") as f:
    ev_lines = [json.loads(x) for x in f if x.strip()]
with open(os.path.join(run_dir, "decisions.jsonl"), encoding="utf-8") as f:
    dc_lines = [json.loads(x) for x in f if x.strip()]
with open(os.path.join(run_dir, "chat_history.jsonl"), encoding="utf-8") as f:
    ch_lines = [json.loads(x) for x in f if x.strip()]
with open(os.path.join(run_dir, "evolution.json"), encoding="utf-8") as f:
    evo = json.load(f)
check("events.jsonl 落盘", len(ev_lines) == 1, str(len(ev_lines)))
check("decisions.jsonl 落盘 + 计数", len(dc_lines) == 2
      and coll._reply_count.get("agent:alpha") == 1
      and coll._silent_count.get("agent:alpha") == 1, str(dc_lines))
check("chat_history.jsonl 落盘（user + agent）", len(ch_lines) == 2
      and ch_lines[0]["role"] == "user" and ch_lines[1]["role"] == "agent",
      str(ch_lines))
check("evolution.json 汇总", evo["rounds"] == 3
      and evo["agents"]["agent:alpha"]["other_cognition"]["userA"] == 2, repr(evo)[:200])

print("\n单元部分结果: %d 通过 / %d 失败" % (PASS, FAIL))
if FAIL:
    sys.exit(1)

# ── U6 话题报告生成器（纯文件驱动，不依赖 AAA） ───────────────
print("\n== U6 话题报告生成（相互认知 + 人格漂移） ==")
from message_pool.topic_report import (generate_topic_report, _read_personality,
                                       _euclidean, _render_mutual_matrix,
                                       _initial_seed, _load_meta)
REPORT_DIR = os.path.join(TMP_IO, "report_fixture")
os.makedirs(os.path.join(REPORT_DIR, "db"), exist_ok=True)

# 构造三个 Agent 的假数据库：初始种子 + 认知记录 + 自我认知 + 情绪
# （n-agent 验证：报告必须涵盖全部 agent，而非写死 2 个）
_fixture_seeds = {
    "agent:0": {"vector": {"warmth": 0.5, "playfulness": 0.5,
                           "directness": 0.5, "curiosity": 0.5},
                "style": "测试风格"},
    "agent:1": {"vector": {"warmth": 0.6, "playfulness": 0.4,
                           "directness": 0.5, "curiosity": 0.5},
                "style": "测试风格"},
    "agent:2": {"vector": {"warmth": 0.4, "playfulness": 0.6,
                           "directness": 0.6, "curiosity": 0.3},
                "style": "测试风格"},
}


def _make_fixture_db(idx, persona, others, self_cogs):
    dbp = os.path.join(REPORT_DIR, "db", f"agent_{idx}.sqlite")
    conn = sqlite3.connect(dbp)
    conn.executescript("""
        CREATE TABLE personality_seed(identity_key TEXT, warmth REAL, playfulness REAL,
            directness REAL, curiosity REAL, style_description TEXT, preset_name TEXT);
        CREATE TABLE other_cognition(id INTEGER PRIMARY KEY, conversation_id TEXT,
            content TEXT, created_at TEXT, identity_key TEXT, user_id TEXT);
        CREATE TABLE self_cognition(id INTEGER PRIMARY KEY, conversation_id TEXT,
            content TEXT, created_at TEXT, identity_key TEXT);
        CREATE TABLE event_summary(id INTEGER PRIMARY KEY, conversation_id TEXT,
            summary TEXT, user_id TEXT, created_at TEXT, identity_key TEXT);
        CREATE TABLE self_info(id INTEGER PRIMARY KEY, identity_key TEXT, key TEXT,
            value TEXT, confidence REAL, created_at TEXT);
        CREATE TABLE feelings(id INTEGER PRIMARY KEY, conversation_id TEXT,
            mood TEXT, thought TEXT, created_at TEXT, identity_key TEXT);
        CREATE TABLE mood_value(id INTEGER PRIMARY KEY, identity_key TEXT,
            mood_value REAL, adjustment REAL, source_mood TEXT, conversation_id TEXT);
    """)
    identity = f"agent:{idx}"
    conn.execute("INSERT INTO personality_seed VALUES(?,?,?,?,?,?,?)",
                 (identity, *persona, "测试风格", "随机种子"))
    for uid, content in others:
        conn.execute("INSERT INTO other_cognition VALUES(NULL,'default',?,?,?,?)",
                     (content, "2026-08-08 09:00:00", identity, uid))
    for content in self_cogs:
        conn.execute("INSERT INTO self_cognition VALUES(NULL,'default',?,?,?)",
                     (content, "2026-08-08 09:00:00", identity))
    conn.execute("INSERT INTO event_summary VALUES(NULL,'default',?,?,?,?)",
                 ("测试沉淀事件", "userA", "2026-08-08 09:00:00", identity))
    conn.execute("INSERT INTO self_info VALUES(NULL,?,?,?,?,?)",
                 (identity, "name", "测试名", 0.8, "2026-08-08 09:00:00"))
    conn.execute("INSERT INTO feelings VALUES(NULL,'default',?,?,?,?)",
                 ("平静", "测试想法", "2026-08-08 09:00:00", identity))
    conn.execute("INSERT INTO mood_value VALUES(NULL,?,?,?,?,?)",
                 (identity, 0.0, 0.0, "平静", "default"))
    conn.commit()
    conn.close()
    return dbp


_make_fixture_db(0, (0.55, 0.45, 0.5, 0.52),
                 [("agent:1", "对方喜欢安静，习惯从日常小事中寻找话题"),
                  ("agent:1", "对方温和有礼，愿意倾听"),
                  ("agent:2", "对方思维直接，不爱绕弯子")],
                 ["我是一个温和的AI助手"])
_make_fixture_db(1, (0.6, 0.4, 0.5, 0.5),
                 [("agent:0", "对方擅长主动开启话题，语气温暖"),
                  ("agent:2", "对方好奇心很重")],
                 ["我话不多，但愿意倾听"])
_make_fixture_db(2, (0.4, 0.6, 0.6, 0.3),
                 [("agent:0", "对方说话很温暖")],
                 ["我说话直接，喜欢探索新鲜事物"])

with open(os.path.join(REPORT_DIR, "_run_meta.json"), "w", encoding="utf-8") as f:
    json.dump({"topic": "测试话题", "topic_rounds": 5, "model": "fake",
               "gid": "u6", "seeds": _fixture_seeds},
              f, ensure_ascii=False, indent=1)
# 假 decisions.jsonl：首条 personality 快照（报告回退用）
with open(os.path.join(REPORT_DIR, "decisions.jsonl"), "w", encoding="utf-8") as f:
    f.write(json.dumps({"agent": "agent:0", "action": "reply",
                        "personality": {"warmth": 0.5, "playfulness": 0.5,
                                        "directness": 0.5, "curiosity": 0.5},
                        "mood": 0.0}, ensure_ascii=False) + "\n")

rep_path = generate_topic_report(REPORT_DIR)
with open(rep_path, encoding="utf-8") as f:
    rep_text = f.read()
check("报告文件生成", os.path.exists(rep_path), rep_path)
check("报告含相互认知矩阵", "相互认知矩阵" in rep_text and "agent:0" in rep_text)
# n-agent 全覆盖：矩阵必须同时列出 agent:0/1/2（3 行 4 列 = 3 agent + 其他）
for _aid in ("agent:0", "agent:1", "agent:2"):
    check(f"矩阵涵盖 {_aid}", f"| {_aid} |" in rep_text, _aid)
check("矩阵包含『其他』对象列", "| 其他 |" in rep_text)
check("报告双向认知判定（agent:0↔1 相互形成）",
      "相互认知已形成" in rep_text, "判定缺失")
check("报告单向认知判定（agent:1→2 单向）",
      "单向认知" in rep_text, "单向判定缺失")
check("报告含人格漂移表（3 行）",
      "人格漂移倾向" in rep_text and "欧氏距离" in rep_text
      and rep_text.count("| agent:") >= 3, "漂移表行数不足")
check("报告含采集指标表（E3 对齐，3 Agent 全覆盖）",
      "自我认知" in rep_text and "情绪轨迹" in rep_text
      and "agent:2" in rep_text, "E3 表缺失 agent:2")
check("报告含相互认知内容摘录（agent:2 认知 agent:0）",
      "对方说话很温暖" in rep_text, "摘录缺失")
check("初始种子从 _run_meta 读取",
      _initial_seed(_load_meta(REPORT_DIR), "agent:0") ==
      {"warmth": 0.5, "playfulness": 0.5, "directness": 0.5, "curiosity": 0.5})
check("personality_seed 表读取最终向量",
      _read_personality(os.path.join(REPORT_DIR, "db", "agent_0.sqlite"),
                        "agent:0") == {"warmth": 0.55, "playfulness": 0.45,
                                       "directness": 0.5, "curiosity": 0.52})
check("欧氏距离计算正确",
      abs(_euclidean({"warmth": 0, "playfulness": 0, "directness": 0, "curiosity": 0},
                     {"warmth": 3, "playfulness": 0, "directness": 0, "curiosity": 4}) - 5.0) < 1e-9)
# 双向判定函数：单向认知应判定为"单向认知"
m, v = _render_mutual_matrix(
    {"agent:0": {"agent:1": ["a"]}, "agent:1": {"agent:0": []}},
    ["agent:0", "agent:1"])
check("单向认知判定正确（A→B 有、B→A 无）",
      "单向认知" in v and "未形成对 agent:0 的认知" in v, v)

# API 调用量统计节（llm_stats.json → 报告）：重新生成报告断言含统计
with open(os.path.join(REPORT_DIR, "llm_stats.json"), "w", encoding="utf-8") as f:
    json.dump({"mode": "subprocess", "fake_llm": True,
               "platform_direct": 3, "total": 25,
               "per_agent": {"agent:0": 8, "agent:1": 8, "agent:2": 9}},
              f, ensure_ascii=False, indent=1)
_rep2 = generate_topic_report(REPORT_DIR)
with open(_rep2, encoding="utf-8") as f:
    _rep2_text = f.read()
check("报告含 API 调用量统计节（总量）",
      "API 调用量" in _rep2_text and "25" in _rep2_text)
check("报告含各 Agent 调用量明细表",
      "agent:0 | 8" in _rep2_text and "agent:2 | 9" in _rep2_text
      and "占比" in _rep2_text)

# ── v6.2 回应上下文专项：prompt 条件节 / 旧数据重建 / 标注优先级 ──
print("\n== U8 回应上下文（v6.2） ==")
import prompt as _pt
from message_pool.data_export import (_load_decision_map,
                                      _reconstruct_round_batches,
                                      _reply_context_annotation)


def _min_ctx(**over):
    ctx = {"identity_key": "agent:0", "self_cognition": "", "fixed_cognition": "",
           "recent_feelings": "", "mood_trend": "", "other_cognition": "",
           "attachment_context": "", "current_date": "2026-08-08",
           "current_time": "10:00:00", "history_summary": "", "user_info": "",
           "self_info": "", "user_id": ""}
    ctx.update(over)
    return ctx


_p1v1 = _pt.build_direct(_min_ctx(user_text="你好"))
_pbatch = _pt.build_direct(_min_ctx(
    pool_batch_section="[agent:3] 你好\n[userA] 在吗"))
check("1对1 prompt 不含【回应对象】节（零影响）",
      "【回应对象】" not in _p1v1)
check("批量模式 prompt 含【回应对象】节（条件输出）",
      "【回应对象】" in _pbatch)

# 标注优先级：LLM 显式回应对象 > 批次作者列表
_anno1 = _reply_context_annotation(
    {"batch_size": 5, "action": "reply", "回应对象": "agent:3"}, None)
_anno2 = _reply_context_annotation(
    {"batch_size": 5, "action": "reply", "回应对象": "群聊"}, None)
_anno3 = _reply_context_annotation(
    {"batch_size": 3, "action": "reply"},
    [{"user_id": "agent:1", "content": "x"},
     {"user_id": "agent:2", "content": "y"},
     {"user_id": "agent:3", "content": "z"}])
check("回应对象标注（具体对象）", _anno1 == "（回应 agent:3）", _anno1)
check("回应对象标注（群聊）", _anno2 == "（回应群聊）", _anno2)
check("无回应对象→批次作者列表标注",
      _anno3 == "（回应上下文：agent:1, agent:2, agent:3（3 条））", _anno3)

# 旧数据回退：无 batch_context 的决策 → 从 chat_history 重建每轮批次
REC_DIR = os.path.join(TMP_IO, "reconstruct_fixture")
os.makedirs(REC_DIR, exist_ok=True)
with open(os.path.join(REC_DIR, "chat_history.jsonl"), "w", encoding="utf-8") as f:
    f.write(json.dumps({"ts": "2026-08-08T09:00:00.100", "role": "topic",
                        "user_id": "platform", "content": "话题"},
                       ensure_ascii=False) + "\n")
    f.write(json.dumps({"ts": "2026-08-08T09:00:01.100", "role": "user",
                        "user_id": "userA", "content": "你好"},
                       ensure_ascii=False) + "\n")
    f.write(json.dumps({"ts": "2026-08-08T09:00:02.100", "role": "user",
                        "user_id": "userB", "content": "在吗"},
                       ensure_ascii=False) + "\n")
    # 第 1 轮 alpha 发言回投（ts 晚于决策边界 → 不进本批）
    f.write(json.dumps({"ts": "2026-08-08T09:00:03.100", "role": "agent",
                        "agent_id": "agent:0", "content": "我是 alpha",
                        "round_no": 1}, ensure_ascii=False) + "\n")
with open(os.path.join(REC_DIR, "decisions.jsonl"), "w", encoding="utf-8") as f:
    f.write(json.dumps({"ts": "2026-08-08T09:00:03.000", "round": 1,
                        "agent": "agent:0", "batch_size": 3, "action": "reply"},
                       ensure_ascii=False) + "\n")
    f.write(json.dumps({"ts": "2026-08-08T09:00:03.000", "round": 1,
                        "agent": "agent:1", "batch_size": 3, "action": "silent"},
                       ensure_ascii=False) + "\n")
_rec_dec = _load_decision_map(REC_DIR)
_rec_batches = _reconstruct_round_batches(REC_DIR, _rec_dec)
_rec_authors = {m["user_id"] for m in _rec_batches.get(1, [])}
check("旧数据重建第 1 轮批次（平台话题 + userA/B）",
      _rec_authors == {"platform", "userA", "userB"},
      str(_rec_authors))


# ── 集成部分（Fake LLM，不调真实 API） ──────────────────────
print("\n== I1/I2 平台集成（Fake LLM） ==")
import main as aaa_main
import db
import memos
import review

# 禁用与验证无关的后台重建线程（防并发崩溃，与 self_evolution_test 一致）
memos.rebuild_index = lambda *a, **k: None
memos.rebuild_knowledge_index = lambda *a, **k: None
db._aggregate_mood = lambda *a, **k: None
# Review 注入空回执钩子，避免后台线程写节点目录
review.set_llm_call(lambda prompt: "")

DBP_A = os.path.join(TMP_IO, "db_alpha.db")
DBP_B = os.path.join(TMP_IO, "db_beta.db")
for p in (DBP_A, DBP_B):
    if os.path.exists(p):
        os.remove(p)

# Fake LLM：每 Agent 独立确定性输出（F9 并行决策下共享计数器会竞态，
# 第一批发言者不定导致断言不稳；按 agent 独立 LLM 保证 alpha 恒 reply、
# beta 首轮 silent 次轮 reply，第一批发言者确定 = alpha）
_REPLY_TEXT = ("【自然回复】\n你好呀！看到你的消息啦\n【回应对象】\nagent:beta\n"
               "【心情】\n开心\n"
               "【想法】\n想回应这条消息\n【情绪调整】\n0.05\n"
               "【事件摘要】\n用户发言，AI 回应 [重要性:3]\n"
               "【他人认知】\n这个用户很活跃")
_SILENT_TEXT = ("【心情】\n平静\n【想法】\n这条消息听过了，不必回应\n"
                "【情绪调整】\n0.0\n【事件摘要】\n用户闲聊 [重要性:2]")


def _llm_always_reply(prompt: str) -> str:
    return _REPLY_TEXT


def _llm_silent_then_reply(prompt: str) -> str:
    _llm_silent_then_reply.n = getattr(_llm_silent_then_reply, "n", 0) + 1
    return _SILENT_TEXT if _llm_silent_then_reply.n == 1 else _REPLY_TEXT

# 注意：MyNode() 内部 memos.preload() 会起后台线程加载模型，属正常行为（daemon）
from message_pool.agent_bridge import AgentBridge
from message_pool.platform_runner import MessagePoolPlatform

agent_a = AgentBridge("agent:alpha", "agent:alpha", DBP_A, _llm_always_reply)
agent_b = AgentBridge("agent:beta", "agent:beta", DBP_B, _llm_silent_then_reply)
run_dir2 = os.path.join(TMP_IO, "runs", "20260808_000000_platform")
plat = MessagePoolPlatform([agent_a, agent_b], run_dir=run_dir2, gid="platform",
                           max_batch=5, arbiter_policy=ArbiterPolicy.DROP)

# 初始化阶段：自我介绍（仅记录聊天历史）+ 平台发放话题（入池 + 记录）
plat.record_speech("agent:alpha", "大家好，我是 alpha，性格温和。", stage="self_intro")
plat.announce("今天我们来聊聊最近的生活吧")
with open(os.path.join(run_dir2, "chat_history.jsonl"), encoding="utf-8") as f:
    ch2 = [json.loads(x) for x in f if x.strip()]
stages = [e.get("stage") for e in ch2 if e.get("role") == "agent"]
topics = [e for e in ch2 if e.get("role") == "topic"]
check("自我介绍记录到聊天历史（stage=self_intro）", "self_intro" in stages, str(stages))
check("话题记录到聊天历史（role=topic + platform）", len(topics) == 1
      and topics[0]["user_id"] == "platform", str(topics))
check("话题已注入消息池", any(m.text.startswith("今天我们来聊聊")
      for m in plat.pool._queue), str([m.text for m in plat.pool._queue]))

plat.inject([
    {"content": "今天天气真好", "user_id": "userA"},
    {"content": "@alpha 在吗？", "user_id": "userB"},
    {"content": "有人吗", "user_id": "userC"},
])
s1 = plat.step()
check("step 返回至多一条发言", s1 is None or s1[0] in ("agent:alpha", "agent:beta"),
      str(s1))
with open(os.path.join(run_dir2, "decisions.jsonl"), encoding="utf-8") as f:
    dc1 = [json.loads(x) for x in f if x.strip()]
check("第一轮 2 条决策落盘（2 Agent）", len(dc1) == 2, str(len(dc1)))
check("第一轮含 reply 与 silent", {d["action"] for d in dc1} == {"reply", "silent"},
      str({d["action"] for d in dc1}))
# v6.2 回应上下文/回应对象：决策含批次消息作者 + LLM 显式回应对象
check("决策含批次上下文（batch_context=4 条：平台话题 + 3 用户）",
      all(d.get("batch_size") == 4 and len(d.get("batch_context", [])) == 4
          for d in dc1),
      str([(d["batch_size"], d.get("batch_context")) for d in dc1]))
check("批次上下文作者 = 平台 + userA/B/C",
      all({m["user_id"] for m in d.get("batch_context", [])} ==
          {"platform", "userA", "userB", "userC"} for d in dc1),
      str([{m["user_id"] for m in d.get("batch_context", [])} for d in dc1]))
check("决策含 LLM 显式回应对象（回复侧）",
      any(d.get("action") == "reply" and d.get("回应对象") == "agent:beta"
          for d in dc1), str([(d["action"], d.get("回应对象")) for d in dc1]))

# 校验 DB：批量写库 user_id 归属 + 静默也写事件摘要
conn = sqlite3.connect(DBP_A)
rows = conn.execute(
    "SELECT content, user_id FROM user_messages ORDER BY id").fetchall()
uids = {r[1] for r in rows}
check("userA/userB/userC 消息归属正确（含 platform 话题）",
      {"userA", "userB", "userC"} <= uids and "platform" in uids, str(rows))
ev = conn.execute(
    "SELECT COUNT(*) FROM event_summary").fetchone()[0]
check("事件摘要已写入（含静默轮）", ev >= 1, str(ev))
conn.close()

# 平台 write_evolution 落盘
meta = plat.write_evolution()
check("evolution.json 含按 user_id 分组的他人认知",
      os.path.exists(os.path.join(run_dir2, "evolution.json")))

# 再来一轮（先注入新消息），验证 DROP 策略下单一发言权 + decisions.jsonl 增长
plat.inject([
    {"content": "晚上好呀", "user_id": "userD"},
    {"content": "@beta 有什么新闻吗", "user_id": "userE"},
])
s2 = plat.step()
# 避让机制：上一批 alpha 刚发言，本批 alpha 被跳过，beta 独享决策与发言权
check("避让后上一位发言者不再接话（beta 发言）",
      s2 is not None and s2[0] == "agent:beta", str(s2))
with open(os.path.join(run_dir2, "decisions.jsonl"), encoding="utf-8") as f:
    dc = [json.loads(x) for x in f if x.strip()]
check("decisions.jsonl 两轮共 3 条决策（第二批避让 alpha，仅 beta 决策）",
      len(dc) == 3, str(len(dc)))
acts = {d["action"] for d in dc}
check("决策含 reply 与 silent", acts <= {"reply", "silent"} and acts == {"reply", "silent"},
      str(acts))
for d in dc:
    assert "personality" in d and "mood" in d and "batch_size" in d, d
check("决策含性格向量/心情/批大小快照", True)

# 平台 step 收敛：同一批至多一条广播（DROP 策略下第二个 reply 被丢弃）
check("DROP 策略单一发言权", plat.arbiter.current_speaker is None or
      s2 is not None, str(s2))

# v6.2 渲染层：聊天历史标注回应对象（LLM 显式优先于批次上下文）
from message_pool.data_export import render_chat_history_md as _render_md
_md2 = _render_md(run_dir2)
with open(_md2, encoding="utf-8") as f:
    _md2_text = f.read()
check("聊天历史渲染含回应对象标注（LLM 显式）",
      "回应 agent:beta" in _md2_text, _md2_text[:200])

# ── I3 话题轮数：agent 发言回投消息池 + N 轮后平台宣告话题结束 ──
print("\n== I3 话题轮数（agent 间多轮对话） ==")


def _fake_all_reply(prompt: str) -> str:
    if "自我介绍" in prompt:
        return "我是 AI 角色，很高兴认识大家。"
    return ("【自然回复】\n轮到我说两句，参与一下讨论\n【心情】\n愉快\n"
            "【想法】\n继续参与对话\n【情绪调整】\n0.05\n"
            "【事件摘要】\n群聊发言 [重要性:3]")


DBP_E = os.path.join(TMP_IO, "db_e.db")
DBP_F = os.path.join(TMP_IO, "db_f.db")
for p in (DBP_E, DBP_F):
    if os.path.exists(p):
        os.remove(p)
agent_e = AgentBridge("agent:e", "agent:e", DBP_E, _fake_all_reply)
agent_f = AgentBridge("agent:f", "agent:f", DBP_F, _fake_all_reply)
run_dir3 = os.path.join(TMP_IO, "runs", "20260808_000000_topic")
plat2 = MessagePoolPlatform([agent_e, agent_f], run_dir=run_dir3, gid="topic",
                            max_batch=5, arbiter_policy=ArbiterPolicy.QUEUE,
                            topic_rounds=2)
plat2.announce("今天我们来聊聊最近的生活吧")
s0 = plat2.step()  # 话题入池 → 首批处理 → 广播发言回投
check("agent 发言回投消息池（source=agent）",
      any(m.source == "agent" for m in plat2.pool._queue),
      str([m.text[:20] for m in plat2.pool._queue]))
for _ in range(6):  # 安全上限；topic_rounds=2 应提前触发结束
    s = plat2.step()
    while True:
        q = plat2.drain_queue()
        if q is None:
            break
    if plat2.topic_ended and len(plat2.pool) == 0 and not plat2.arbiter.is_busy:
        break
check("达到 N 轮后平台宣告话题结束", plat2.topic_ended
      and plat2.agent_speech_count == 2,
      f"ended={plat2.topic_ended} count={plat2.agent_speech_count}")
with open(os.path.join(run_dir3, "chat_history.jsonl"), encoding="utf-8") as f:
    ch3 = [json.loads(x) for x in f if x.strip()]
sys_msgs = [e for e in ch3 if e.get("role") == "system"]
check("结束公告写入聊天历史（role=system）", len(sys_msgs) == 1
      and "话题已结束" in sys_msgs[0]["content"], str(sys_msgs)[:120])

# ── I4 避让机制：上一条 agent 发言者下批被跳过，防自言自语 ──
print("\n== I4 避让机制（上一位发言者不接自己的话） ==")
from collections import Counter

run_dir4 = os.path.join(TMP_IO, "runs", "20260808_000000_yield")
plat3 = MessagePoolPlatform([agent_e, agent_f], run_dir=run_dir4, gid="yield",
                            max_batch=5, arbiter_policy=ArbiterPolicy.QUEUE,
                            topic_rounds=20)
plat3.announce("测试话题")
for _ in range(4):  # 4 轮（含排队补位广播）
    plat3.step()
    while plat3.drain_queue():
        pass
with open(os.path.join(run_dir4, "chat_history.jsonl"), encoding="utf-8") as f:
    ch4 = [json.loads(x) for x in f if x.strip()]
agent_msgs = [e for e in ch4
              if e.get("role") == "agent" and not e.get("stage")]
seq = [e["agent_id"] for e in agent_msgs]
cnt = Counter(seq)
check("两 Agent 都有广播发言", "agent:e" in cnt and "agent:f" in cnt,
      str(cnt))
check("发言次数不悬殊（≤3:1）",
      max(cnt.values()) <= max(1, min(cnt.values()) * 3), str(cnt))
check("无同一 Agent 连续广播（防自言自语）",
      all(seq[i] != seq[i + 1] for i in range(len(seq) - 1)), str(seq))

# ── U7 F9 子进程化专项验收（每 Agent 独立 AAA 子进程） ──────────
print("\n== U7 Agent 子进程化（F9） ==")
import time as _time
import subprocess as _subprocess
from message_pool.agent_bridge import AgentBridge as SubAgentBridge

SUBP_DIR = os.path.join(TMP_IO, "db_subp")
os.makedirs(SUBP_DIR, exist_ok=True)
# 轻量验收：跳过模型预加载/重建线程（fake LLM，不调 API）
subp_env = {"AAA_LLM_MODE": "fake", "AAA_SKIP_HEAVY": "1"}
_subp_agents = []
for _i in range(3):
    _identity = f"agent:s{_i}"
    _dbp = os.path.join(SUBP_DIR, f"agent_{_i}.sqlite")
    if os.path.exists(_dbp):
        os.remove(_dbp)
    _subp_agents.append(SubAgentBridge(_identity, _identity, _dbp, None,
                                       mode="subprocess", aaa_env=subp_env))

# 7.3.1 进程隔离：3 个独立 AAA 子进程，PID 各不相同
for _a in _subp_agents:
    _a._ensure_proc()
pids = {_a._proc.pid for _a in _subp_agents}
check("进程隔离：3 个独立 AAA 子进程", len(_subp_agents) == 3
      and len(pids) == 3 and all(_a._proc.poll() is None for _a in _subp_agents),
      f"pids={pids}")
check("子进程独立 DB（互不复用 memos 索引）",
      all(_a.db_path != _subp_agents[0].db_path or i == 0
          for i, _a in enumerate(_subp_agents)))

# 7.3.2 常驻通信：ping 往返 + 50 条请求无解析错误
# （先 _ensure_proc 预热，排除首次冷启动时间——启动属于启动成本，不属于通信往返；
#   阈值 2s：预热后首次 ping 仍可能带子进程初始化尾巴，常驻往返本质为亚毫秒级）
for _a in _subp_agents:
    _a._ensure_proc()
_t0 = _time.time()
check("探活 ping 往返 < 2s", all(_a.ping() for _a in _subp_agents)
      and (_time.time() - _t0) < 2.0, f"{( _time.time() - _t0):.3f}s")
_ok_count = 0
for _i in range(50):
    _a = _subp_agents[_i % 3]
    _resp = _a.process_batch(
        [{"user_id": "userA", "content": f"测试消息 {_i}"}], round_no=_i)
    if isinstance(_resp, dict) and _resp.get("action") in ("reply", "silent"):
        _ok_count += 1
check("50 条请求全部返回合法决策（无解析错误）", _ok_count == 50,
      f"{_ok_count}/50")

# 7.3.3 API 调用量统计（llm_stats）：各子进程独立计数且非零
_subp_stats = [_a.llm_stats() for _a in _subp_agents]
check("llm_stats 返回合法计数（int ≥ 0）",
      all(isinstance(s.get("calls"), int) and s.get("calls") >= 0
          for s in _subp_stats), str(_subp_stats))
check("50 条请求后每个子进程均有 LLM 调用（≥1）",
      all(s.get("calls", 0) >= 1 for s in _subp_stats), str(_subp_stats))

# 7.3.4 并行决策 + 优先级仲裁：@ 点名优先（即使决策完成较晚）
run_dir7 = os.path.join(TMP_IO, "runs", "20260808_000000_subproc")
from message_pool.platform_runner import MessagePoolPlatform
plat7 = MessagePoolPlatform(_subp_agents, run_dir=run_dir7, gid="subproc",
                            max_batch=5, arbiter_policy=ArbiterPolicy.QUEUE,
                            topic_rounds=10)
plat7.inject([{"content": "@agent:s2 你觉得呢", "user_id": "userA"},
              {"content": "今天天气不错", "user_id": "userB"}])
_s7 = plat7.step()
check("@ 点名优先：被点名 agent:s2 获得发言权", _s7 is not None
      and _s7[0] == "agent:s2", str(_s7))

# 7.3.5 崩溃恢复：kill 一个子进程 → 自动重启继续工作
_kill_agent = _subp_agents[0]
_kill_agent._proc.kill()
_kill_agent._proc.wait()
_resp_after = _kill_agent.process_batch(
    [{"user_id": "userC", "content": "崩溃后恢复测试"}], round_no=99)
check("崩溃恢复：kill 后自动重启并返回决策", _kill_agent._proc.poll() is None
      and isinstance(_resp_after, dict)
      and _resp_after.get("action") in ("reply", "silent"),
      str(_resp_after)[:120])

# 7.3.6 资源回收：close 后无孤儿进程
for _a in _subp_agents:
    _a.close()
# close() 内部把 _proc 置 None（正常回收），None 或已退出均视为回收成功
check("资源回收：close 后全部子进程退出",
      all(_a._proc is None or _a._proc.poll() is not None
          for _a in _subp_agents),
      str([None if _a._proc is None else _a._proc.poll()
           for _a in _subp_agents]))
# 清理可能残留的子进程（极端失败兜底）
for _a in _subp_agents:
    if _a._proc is not None and _a._proc.poll() is None:
        _a._proc.kill()

# ── U9 v6.3 修复验收（P0 数据污染 + P1 机制断链） ──────────────
print("\n== U9 v6.3 P0/P1 修复验收 ==")

# U9.1 P0-1a/b：inline 模式 LLM 调用失败 → action=error（不落 silent、不归因）
def _llm_boom(prompt: str) -> str:
    raise RuntimeError("HTTP Error 402: Payment Required")
_DBP_E2 = os.path.join(TMP_IO, "db_err.sqlite")
if os.path.exists(_DBP_E2):
    os.remove(_DBP_E2)
_bad_agent = AgentBridge("agent:err", "agent:err", _DBP_E2, _llm_boom)
_d = _bad_agent.process_batch(
    [{"user_id": "userA", "content": "测试消息"}], round_no=1)
check("P0-1a inline LLM 失败 → action=error（不落 silent）",
      _d.get("action") == "error", str(_d))
check("P0-1b error 记录 user_id 不归因", _d.get("user_id", "u") in ("", None),
      repr(_d.get("user_id")))

# U9.2 P0-1c/d：subprocess 失败响应（code=-1）→ action=error（mock _send）
_mock_bridge = SubAgentBridge("agent:m", "agent:m",
                              os.path.join(TMP_IO, "db_m.sqlite"),
                              None, mode="subprocess", aaa_env=subp_env)

def _fake_send(req, retries=1):
    return {"code": -1, "type": "pool_batch",
            "error": "HTTPError: HTTP Error 402: Payment Required"}

_mock_bridge._send = _fake_send
_dm = _mock_bridge.process_batch(
    [{"user_id": "userA", "content": "hi"}], round_no=1)
check("P0-1c subprocess 失败 → action=error（不落 silent）",
      _dm.get("action") == "error" and "402" in str(_dm.get("error", "")),
      str(_dm))
check("P0-1d subprocess 失败 user_id 不归因批次末位",
      _dm.get("user_id", "u") in ("", None), repr(_dm.get("user_id")))

# U9.3 P0-1e：collector error 独立计数（不进 silent_count）
_COL_DIR = os.path.join(TMP_IO, "runs", "20260808_000000_v63")
_col9 = ExperimentCollector(_COL_DIR, gid="v63")
_col9.decision(agent="agent:x", action="reply")
_col9.decision(agent="agent:x", action="silent")
_col9.decision(agent="agent:x", action="error")
_col9.set_rounds(1)
_col9.write_evolution({})
with open(os.path.join(_COL_DIR, "evolution.json"), encoding="utf-8") as f:
    _evo9 = json.load(f)
check("P0-1e error 独立计数（reply/silent/error 各 1，互不污染）",
      _evo9.get("error_count", {}).get("agent:x") == 1
      and _evo9.get("silent_count", {}).get("agent:x") == 1
      and _evo9.get("reply_count", {}).get("agent:x") == 1,
      str({k: v for k, v in _evo9.items() if k.endswith("_count")}))

# U9.4 P0-2a：批量 reply 决策 user_id 归因 = LLM 显式回应对象（非批次末位）
_DBP_U9 = os.path.join(TMP_IO, "db_u9.sqlite")
if os.path.exists(_DBP_U9):
    os.remove(_DBP_U9)
_node_u9 = aaa_main.MyNode()
_node_u9._on_pool_batch({
    "data_type": "pool_batch", "conversation_id": "default",
    "identity_key": "agent:u9", "request_id": "round_1_agent_u9",
    "messages": [{"user_id": "userA", "content": "早上好"},
                 {"user_id": "userB", "content": "今天天气真好"}],
}, _DBP_U9)

def _llm_u9(prompt: str) -> str:
    return ("【自然回复】\n早上好呀 userA\n【回应对象】\nuserA\n【心情】\n开心\n"
            "【想法】\n想回应 userA\n【情绪调整】\n0.05\n"
            "【事件摘要】\n用户发言，AI 回应 [重要性:3]")

_d_u9 = _node_u9._on_parsed({
    "data_type": "parsed", "source": "llm",
    "request_id": "round_1_agent_u9",
    "content": _llm_u9(""),
}, _DBP_U9, {}, user_id="", batch_mode=True)
check("P0-2a reply user_id = LLM 回应对象 userA（非批次末位 userB）",
      _d_u9.get("action") == "reply" and _d_u9.get("user_id") == "userA",
      repr(_d_u9.get("user_id")))

# U9.5 P0-2b：静默决策 user_id 不归因（LLM 无回应对象 → 空，不取末位）
_node_u9._on_pool_batch({
    "data_type": "pool_batch", "conversation_id": "default",
    "identity_key": "agent:u9", "request_id": "round_2_agent_u9",
    "messages": [{"user_id": "userA", "content": "早"},
                 {"user_id": "userB", "content": "晚"}],
}, _DBP_U9)

def _llm_u9_silent(prompt: str) -> str:
    return ("【心情】\n平静\n【想法】\n这条消息听过了，不必回应\n"
            "【情绪调整】\n0.0\n【事件摘要】\n用户闲聊 [重要性:2]")

_d_u9s = _node_u9._on_parsed({
    "data_type": "parsed", "source": "llm",
    "request_id": "round_2_agent_u9",
    "content": _llm_u9_silent(""),
}, _DBP_U9, {}, user_id="", batch_mode=True)
check("P0-2b 静默决策 user_id 不归因末位（→ 空）",
      _d_u9s.get("action") == "silent" and _d_u9s.get("user_id") == "",
      repr(_d_u9s.get("user_id")))

# U9.6 P1-3a/b：_batch_for 把 @ 该 Agent 的消息移到批次末尾
_plat_u9 = MessagePoolPlatform([], run_dir=None, gid="u9")
_batch_in = [{"user_id": "userA", "content": "大家好"},
             {"user_id": "userB", "content": "@agent:t 在吗"},
             {"user_id": "userC", "content": "有人吗"}]
_batch_out = _plat_u9._batch_for("agent:t", _batch_in)
check("P1-3a @ 消息移末位（末位偏置为 @ 优先服务）",
      _batch_out[-1]["user_id"] == "userB"
      and [m["user_id"] for m in _batch_out] == ["userA", "userC", "userB"],
      str([m["user_id"] for m in _batch_out]))
_batch_no_mention = [{"user_id": "userA", "content": "hi"}]
check("P1-3b 无 @ 时保持原序",
      [m["user_id"] for m in _plat_u9._batch_for("agent:t", _batch_no_mention)]
      == ["userA"], str(_batch_no_mention))

# U9.7 P1-3c：prompt 回应对象引导含"不一定是最后一条"与"@ 优先"
from prompt import _prepare_ctx
_ctx_u9 = {"pool_batch_section": "batch"}
_prepare_ctx(_ctx_u9)
check("P1-3c prompt 引导从批次中选择回应对象（非末位 + @ 优先）",
      "不一定" in _ctx_u9["reply_target_section"]
      and "优先回应点名的人" in _ctx_u9["reply_target_section"],
      _ctx_u9["reply_target_section"])

# U9.8 P1-4a/b：neutral 反馈触发人格演化（人格零漂移根因修复）
from personality import PersonalityEvolution
_evo_u9 = PersonalityEvolution({"warmth": 0.6, "playfulness": 0.4,
                                "directness": 0.5, "curiosity": 0.5})
_style_high = {"warmth": 0.9, "playfulness": 0.3,
               "directness": 0.5, "curiosity": 0.5}
for _i in range(10):
    _evo_u9.observe_feedback(_style_high, "neutral", mood=0.5)
check("P1-4a neutral 反馈触发演化（warmth 向 0.9 收敛）",
      _evo_u9.vector["warmth"] > 0.6,
      f"warmth={_evo_u9.vector['warmth']:.4f}")
_evo_stable = PersonalityEvolution({"warmth": 0.6, "playfulness": 0.4,
                                    "directness": 0.5, "curiosity": 0.5})
_stable_style = {"warmth": 0.6, "playfulness": 0.4,
                 "directness": 0.5, "curiosity": 0.5}
for _i in range(10):
    _evo_stable.observe_feedback(_stable_style, "neutral", mood=0.5)
check("P1-4b 自我一致 neutral 反馈不漂移（delta≈0）",
      abs(_evo_stable.vector["warmth"] - 0.6) < 1e-6,
      f"warmth={_evo_stable.vector['warmth']:.6f}")

# ── U10 v6.4 引用链（谁回应谁）注入验收 ─────────────────────
print("\n== U10 v6.4 引用链（谁回应谁）注入验收 ==")

# U10.1 Message 携带 reply_to（引用链随消息入池）
_pool10 = MessagePool()
_msg10 = _pool10.enqueue_input("你好", source="agent", user_id="agent:0",
                               dedup=False, reply_to="agent:3")
check("U10.1 消息携带 reply_to 字段（引用链入池）",
      _msg10.to_dict().get("reply_to") == "agent:3",
      repr(_msg10.to_dict().get("reply_to")))

# U10.2 仲裁器 reply_to 透传（请求 → 释放，排队补位不丢失引用链）
_arb10 = SpeechOutputArbiter()
_arb10.request_speech("agent:0", "内容", reply_to="agent:3")
_rel10 = _arb10.release()
check("U10.2 仲裁项透传 reply_to（排队补位不丢失引用链）",
      (_rel10 or {}).get("reply_to") == "agent:3", str(_rel10))

# U10.3 平台回投发言携带 reply_to（决策的【回应对象】进消息池）
def _llm_silent10(prompt: str) -> str:
    return ("【心情】\n平静\n【想法】\n这条消息不必回应\n"
            "【情绪调整】\n0.0\n【事件摘要】\n用户闲聊 [重要性:2]")

_DBP_U10A = os.path.join(TMP_IO, "db_u10a.db")
_DBP_U10B = os.path.join(TMP_IO, "db_u10b.db")
for _p in (_DBP_U10A, _DBP_U10B):
    if os.path.exists(_p):
        os.remove(_p)
_agent_u10a = AgentBridge("agent:alpha", "agent:alpha", _DBP_U10A,
                          _llm_always_reply)
_agent_u10b = AgentBridge("agent:beta", "agent:beta", _DBP_U10B,
                          _llm_silent10)
_plat10 = MessagePoolPlatform(
    [_agent_u10a, _agent_u10b],
    run_dir=os.path.join(TMP_IO, "runs", "20260808_000000_v64"), gid="v64")
_plat10.announce("今天我们来聊聊最近的生活吧")
_plat10.inject([{"content": "今天天气真好", "user_id": "userA"},
                {"content": "@alpha 在吗？", "user_id": "userB"},
                {"content": "有人吗", "user_id": "userC"}])
_sp10 = _plat10.step()
_pool_agent_msgs10 = [m for m in _plat10.pool._queue if m.source == "agent"]
check("U10.3 发言回投消息 reply_to = 决策的【回应对象】",
      any(getattr(m, "reply_to", "") == "agent:beta"
          for m in _pool_agent_msgs10),
      str([(m.user_id, getattr(m, "reply_to", ""))
           for m in _pool_agent_msgs10]))

# U10.4 AAA 批次上下文渲染"（回应 X）"引用链标注（LLM 决策可见谁回应谁）
check("U10.4 批次消息标注（回应 X）引用链",
      aaa_main.MyNode._fmt_pool_msg(
          {"user_id": "agent:1", "content": "你好呀", "reply_to": "agent:0"})
      == "[agent:1] 你好呀（回应 agent:0）")
check("U10.4b 群聊回应标注",
      aaa_main.MyNode._fmt_pool_msg(
          {"user_id": "agent:2", "content": "hello", "reply_to": "群聊"})
      == "[agent:2] hello（回应群聊）")
check("U10.4c 无回应对象不标注",
      aaa_main.MyNode._fmt_pool_msg(
          {"user_id": "userA", "content": "普通消息"})
      == "[userA] 普通消息")

# ═════════════════════════════════════════════════════════════════
# U11 v6.5 数据质量修复验收（5a30r 分析报告六项）
#   A 防自认知污染 / B 静默模板分 action / C 幽灵发言口径标注
#   D 截断防御（残缺节标记剥离）/ E 末位偏置冷板凳轮转 / F 情绪标签引导
# ═════════════════════════════════════════════════════════════════

# ── U11.1 A：batch_mode 归因排除"回应对象=自己"（防自认知污染） ──
_DBP_A = os.path.join(TMP_IO, "db_u11a.sqlite")
if os.path.exists(_DBP_A):
    os.remove(_DBP_A)
_node_a = aaa_main.MyNode()
_node_a._on_pool_batch({
    "data_type": "pool_batch", "conversation_id": "default",
    "identity_key": "agent:self", "request_id": "r1_a",
    "messages": [{"user_id": "agent:self", "content": "我自己的话"},
                 {"user_id": "agent:other", "content": "别人的话"}],
}, _DBP_A)

def _llm_self(prompt: str) -> str:
    return ("【自然回复】\n同意\n【回应对象】\nagent:self\n【心情】\n平静\n"
            "【想法】\n回自己一句\n【情绪调整】\n0.0\n"
            "【事件摘要】\n闲聊 [重要性:2]")

_d_a = _node_a._on_parsed({
    "data_type": "parsed", "source": "llm", "request_id": "r1_a",
    "content": _llm_self(""),
}, _DBP_A, {}, user_id="", batch_mode=True)
check("A1 回应对象=自己 → user_id 清空（防自认知污染）",
      _d_a.get("action") == "reply" and _d_a.get("user_id") == "",
      repr(_d_a.get("user_id")))

_node_a._on_pool_batch({
    "data_type": "pool_batch", "conversation_id": "default",
    "identity_key": "agent:self", "request_id": "r2_a",
    "messages": [{"user_id": "agent:self", "content": "我的话"},
                 {"user_id": "agent:other", "content": "接话"}],
}, _DBP_A)

def _llm_other(prompt: str) -> str:
    return ("【自然回复】\n好的\n【回应对象】\nagent:other\n【心情】\n平静\n"
            "【想法】\n回应别人\n【情绪调整】\n0.0\n"
            "【事件摘要】\n闲聊 [重要性:2]")

_d_a2 = _node_a._on_parsed({
    "data_type": "parsed", "source": "llm", "request_id": "r2_a",
    "content": _llm_other(""),
}, _DBP_A, {}, user_id="", batch_mode=True)
check("A2 回应对象=他人 → user_id 保留（对照）",
      _d_a2.get("action") == "reply" and _d_a2.get("user_id") == "agent:other",
      repr(_d_a2.get("user_id")))

# ── U11.2 B：想法 fallback 分 action（reply 不用静默模板） ──
_node_a._on_pool_batch({
    "data_type": "pool_batch", "conversation_id": "default",
    "identity_key": "agent:self", "request_id": "r3_a",
    "messages": [{"user_id": "agent:other", "content": "你好"}],
}, _DBP_A)

def _llm_reply_no_thought(prompt: str) -> str:
    return ("【自然回复】\n好的\n【回应对象】\nagent:other\n【心情】\n平静\n"
            "【情绪调整】\n0.0\n【事件摘要】\n闲聊 [重要性:2]")

_d_b1 = _node_a._on_parsed({
    "data_type": "parsed", "source": "llm", "request_id": "r3_a",
    "content": _llm_reply_no_thought(""),
}, _DBP_A, {}, user_id="", batch_mode=True)
check("B1 reply 无想法 → 想法为空（不复用静默模板）",
      _d_b1.get("action") == "reply" and _d_b1.get("想法") == "",
      repr(_d_b1.get("想法")))

_node_a._on_pool_batch({
    "data_type": "pool_batch", "conversation_id": "default",
    "identity_key": "agent:self", "request_id": "r4_a",
    "messages": [{"user_id": "agent:other", "content": "你好"}],
}, _DBP_A)

def _llm_silent_no_thought(prompt: str) -> str:
    return ("【心情】\n平静\n【情绪调整】\n0.0\n【事件摘要】\n闲聊 [重要性:2]")

_d_b2 = _node_a._on_parsed({
    "data_type": "parsed", "source": "llm", "request_id": "r4_a",
    "content": _llm_silent_no_thought(""),
}, _DBP_A, {}, user_id="", batch_mode=True)
check("B2 silent 无想法 → 保持观察模板（静默语义）",
      _d_b2.get("action") == "silent"
      and _d_b2.get("想法") == "收到消息，保持观察，暂不回应",
      repr(_d_b2.get("想法")))

# ── U11.3 C：幽灵发言口径标注（topic_ended 标记） ──
from message_pool.collector import ExperimentCollector
_C_DIR = os.path.join(TMP_IO, "run_c1")
_c11 = ExperimentCollector(_C_DIR, gid="c1")
_c11.decision(action="reply", agent="agent:x", content="a")
_c11.topic_ended = True
_c11.decision(action="reply", agent="agent:x", content="b")
_c11.close()
_rcs11 = []
with open(os.path.join(_C_DIR, "decisions.jsonl"), encoding="utf-8") as f:
    _rcs11 = [json.loads(l) for l in f]
check("C1 话题结束后决策附带 topic_ended=True（幽灵发言口径）",
      "topic_ended" not in _rcs11[0] and _rcs11[1].get("topic_ended") is True,
      str([r.get("topic_ended") for r in _rcs11]))

_p_end = MessagePoolPlatform([], run_dir=os.path.join(TMP_IO, "run_c2"),
                             gid="c2", topic_rounds=0)
_p_end._end_topic()
check("C2 平台宣告话题结束 → collector.topic_ended=True",
      _p_end.collector.topic_ended is True,
      str(_p_end.collector.topic_ended))
_p_end.write_evolution()
with open(os.path.join(TMP_IO, "run_c2", "evolution.json"),
          encoding="utf-8") as f:
    _evo_c = json.load(f)
check("C3 evolution 落 agent_speech_count/topic_ended/rounds_metric 口径",
      _evo_c.get("agent_speech_count") == _p_end.agent_speech_count
      and _evo_c.get("topic_ended") is True
      and _evo_c.get("rounds_metric") == "processed_batches",
      str({k: v for k, v in _evo_c.items() if k in (
          "agent_speech_count", "topic_ended", "rounds_metric")}))

# ── U11.4 D：残缺节标记剥离（max_tokens 截断防御） ──
from parser import parse_llm_output
_d_frag = parse_llm_output(
    "【想法】\n我想学着这种不催促的相处方式。\n\n【情绪调整\n")
check("D1 残缺节标记被剥离（想法不含残段、无情绪调整键）",
      "【情绪调整" not in _d_frag.get("想法", "")
      and "情绪调整" not in _d_frag,
      repr(_d_frag))
_d_ok = parse_llm_output(
    "【想法】\nabc\n【情绪调整】\n0.05\n【心情】\n平静")
check("D2 正常节标记解析不受影响",
      _d_ok.get("情绪调整") == "0.05" and _d_ok.get("想法") == "abc",
      repr(_d_ok))

# ── U11.5 E：末位偏置冷板凳轮转（被回应最少者移末位） ──
_p_e = MessagePoolPlatform([], run_dir=None, gid="e")
_p_e._responded = {"agent:a": 5, "agent:b": 0, "agent:c": 2}
_batch_e = [{"user_id": "agent:a", "content": "x"},
            {"user_id": "agent:b", "content": "y"},
            {"user_id": "agent:c", "content": "z"}]
_out_e = _p_e._batch_for("agent:x", _batch_e)
check("E1 无 @ 时被回应最少者移末位（冷板凳轮转）",
      [m["user_id"] for m in _out_e] == ["agent:a", "agent:c", "agent:b"],
      str([m["user_id"] for m in _out_e]))
_batch_e2 = [{"user_id": "agent:a", "content": "@agent:x 你好"},
             {"user_id": "agent:b", "content": "y"},
             {"user_id": "agent:c", "content": "z"}]
_out_e2 = _p_e._batch_for("agent:x", _batch_e2)
check("E2 @ 优先于冷板凳（@ 消息仍置末位）",
      _out_e2[-1]["user_id"] == "agent:a",
      str([m["user_id"] for m in _out_e2]))
_p_e._responded = {"agent:a": 5, "agent:b": 2, "agent:c": 0}
_out_e3 = _p_e._batch_for("agent:x", _batch_e)
check("E3 被回应最少者已在末位 → 保持原序",
      [m["user_id"] for m in _out_e3] == ["agent:a", "agent:b", "agent:c"],
      str([m["user_id"] for m in _out_e3]))
_batch_e4 = [{"user_id": "agent:a", "content": "x"},
             {"user_id": "platform", "content": "公告"}]
_out_e4 = _p_e._batch_for("agent:x", _batch_e4)
check("E4 平台消息不参与冷板凳轮转（保持原序）",
      [m["user_id"] for m in _out_e4] == ["agent:a", "platform"],
      str([m["user_id"] for m in _out_e4]))
_p_e5 = MessagePoolPlatform([], run_dir=None, gid="e5")
_p_e5._responded = {"agent:a": 0, "agent:b": 0}
_p_e5._feed_agent_speech("agent:a", "hi", reply_to="agent:b")
check("E5 发言回投 reply_to 命中 → 被回应者计数 +1",
      _p_e5._responded.get("agent:b") == 1 and _p_e5._responded.get("agent:a") == 0,
      str(_p_e5._responded))

# ── U11.6 F：情绪调整节引导（reply/silent 都必须输出） ──
from prompt import DIRECT_TEMPLATE
check("F1 prompt 强调【情绪调整】必须输出数字",
      "此节都必须输出一个数字" in DIRECT_TEMPLATE
      and "禁止留空或省略" in DIRECT_TEMPLATE,
      "情绪调整" in DIRECT_TEMPLATE)

# ═════════════════════════════════════════════════════════════════
# U12 v6.6 修复验收 + 数据采集方案实施验收（分析报告六项 + 采集清单七项）
#   P0-1 批次顺序事实源统一 / P0-2 空 user_id 过滤 / P1-4 截断重试
#   P1-5 末位偏置量化指标 / P1-6 演化阈值 30→10
#   采集：memory_hits(P0-1) / silent_cognition(P0-2) / trajectory(P0-3)
#         timeline(P1-4) / @提及归因(P1-5) / 位置对照(P2-6) / 情绪关联(P2-7)
# ═════════════════════════════════════════════════════════════════

# ── U12.1 P0-1：批次顺序事实源统一（decisions.batch_context.seq） ──
print("\n== U12.1 P0-1 批次顺序事实源（seq 唯一关联键） ==")
from message_pool.message_pool import MessagePool
_pool12 = MessagePool()
_msg_a = _pool12.enqueue_input("早上好", user_id="userA")
_msg_b = _pool12.enqueue_input("晚上好", user_id="userB")
_DBP_U12 = os.path.join(TMP_IO, "db_u12.sqlite")
if os.path.exists(_DBP_U12):
    os.remove(_DBP_U12)
_agent12 = AgentBridge("agent:u12", "agent:u12", _DBP_U12, _llm_always_reply)
_d12 = _agent12.process_batch([_msg_a, _msg_b], round_no=1)
check("U12.1a batch_context 携带 seq（与 Message.seq 一致）",
      [m["seq"] for m in _d12["batch_context"]] == [_msg_a.seq, _msg_b.seq],
      str([m["seq"] for m in _d12["batch_context"]]))
check("U12.1b Message.to_dict() 含 seq 字段（关联键落盘）",
      _msg_a.to_dict().get("seq") == _msg_a.seq, repr(_msg_a.to_dict()))
# 同一批次派发给不同 Agent：seq 集合必须相同（顺序事实源唯一）
_DBP_U12B = os.path.join(TMP_IO, "db_u12b.sqlite")
if os.path.exists(_DBP_U12B):
    os.remove(_DBP_U12B)
_agent12b = AgentBridge("agent:u12b", "agent:u12b", _DBP_U12B, _llm_silent_then_reply)
_d12b = _agent12b.process_batch([_msg_a, _msg_b], round_no=1)
check("U12.1c 同批不同 Agent 的 seq 集合相同（顺序事实源唯一）",
      {m["seq"] for m in _d12["batch_context"]} ==
      {m["seq"] for m in _d12b["batch_context"]},
      f"{[m['seq'] for m in _d12['batch_context']]} vs "
      f"{[m['seq'] for m in _d12b['batch_context']]}")

# ── U12.2 P0-2：空 user_id 不写 other_cognition（skip_empty_other） ──
print("\n== U12.2 P0-2 空 user_id 过滤（skip_empty_other） ==")
_DBP_U12C = os.path.join(TMP_IO, "db_u12c.sqlite")
if os.path.exists(_DBP_U12C):
    os.remove(_DBP_U12C)
db.ensure(_DBP_U12C)
_parsed_oc = {"他人认知": "这个用户很活跃", "事件摘要": "闲聊 [重要性:2]"}
# skip_empty_other=True + user_id="" → 跳过 other_cognition 写入
db._write_parsed(_parsed_oc, _DBP_U12C, "default", identity_key="agent:u12",
                 user_id="", skip_empty_other=True)
_conn_u12 = sqlite3.connect(_DBP_U12C)
_n_empty = _conn_u12.execute(
    "SELECT COUNT(*) FROM other_cognition WHERE user_id=''").fetchone()[0]
check("U12.2a skip_empty_other=True + 空 user_id → 不写 other_cognition",
      _n_empty == 0, str(_n_empty))
# skip_empty_other=False（GUI 1对1 兜底）→ 照常写入
db._write_parsed(_parsed_oc, _DBP_U12C, "default", identity_key="agent:u12",
                 user_id="", skip_empty_other=False)
_n_empty2 = _conn_u12.execute(
    "SELECT COUNT(*) FROM other_cognition WHERE user_id=''").fetchone()[0]
check("U12.2b skip_empty_other=False（GUI 兜底）→ 正常写入",
      _n_empty2 == 1, str(_n_empty2))
_conn_u12.close()
# 报告读取侧过滤空键
from message_pool.topic_report import _read_other_cognition
_oc_u12 = _read_other_cognition(_DBP_U12C, "agent:u12")
check("U12.2c _read_other_cognition 过滤空 user_id 键",
      "" not in _oc_u12 and not _oc_u12, str(_oc_u12))

# ── U12.3 P1-4：截断检测 is_truncated ──
print("\n== U12.3 P1-4 截断检测（is_truncated） ==")
from parser import is_truncated
check("U12.3a 未闭合节标记结尾 → 截断",
      is_truncated("【想法】\n我想学着这样。\n\n【情绪调整") is True)
check("U12.3b 完整输出 → 非截断",
      is_truncated("【想法】\nabc\n【情绪调整】\n0.05\n【心情】\n平静") is False)
check("U12.3c 有回复缺情绪调整 → 截断（信号2）",
      is_truncated("【自然回复】\n你好呀\n【想法】\nabc") is True)
check("U12.3d 空输出 → 非截断（静默视为合法）",
      is_truncated("") is False)

# ── U12.4 P1-5：末位偏置量化指标 + @提及/归因（数据采集 P1-5/P2-6） ──
print("\n== U12.4 P1-5 末位偏置 + @提及指标 ==")
_msgs_u12 = [
    {"user_id": "userA", "content": "早上好", "seq": 1},
    {"user_id": "userB", "content": "@agent:u12 你觉得呢", "seq": 2},
    {"user_id": "userC", "content": "最后一句", "seq": 3},
]


def _llm_reply_userB(prompt: str) -> str:
    return ("【自然回复】\n在的\n【回应对象】\nuserB\n【心情】\n平静\n"
            "【想法】\n回应点名者\n【情绪调整】\n0.05\n"
            "【事件摘要】\n闲聊 [重要性:2]")


def _llm_reply_userC(prompt: str) -> str:
    return ("【自然回复】\n好的\n【回应对象】\nuserC\n【心情】\n平静\n"
            "【想法】\n回应末位\n【情绪调整】\n0.05\n"
            "【事件摘要】\n闲聊 [重要性:2]")


_DBP_U12D = os.path.join(TMP_IO, "db_u12d.sqlite")
if os.path.exists(_DBP_U12D):
    os.remove(_DBP_U12D)
_agent12d = AgentBridge("agent:u12", "agent:u12", _DBP_U12D, _llm_reply_userB)
_d12d = _agent12d.process_batch(_msgs_u12, round_no=1, mention_targets=["agent:u12"])
check("U12.4a reply 决策含 reply_target_pos（userB 在 pos=1）",
      _d12d.get("reply_target_pos") == 1, repr(_d12d.get("reply_target_pos")))
check("U12.4b batch_last_author 记录批次末位作者 userC",
      _d12d.get("batch_last_author") == "userC", repr(_d12d.get("batch_last_author")))
check("U12.4c mention_targets 记录本批被点名列表",
      _d12d.get("mention_targets") == ["agent:u12"], str(_d12d.get("mention_targets")))
check("U12.4d 被 @ 且回应点名者 userB → mention_responded=True",
      _d12d.get("mention_responded") is True, repr(_d12d.get("mention_responded")))
check("U12.4e attribution_ok（user_id=userB=回应对象）",
      _d12d.get("attribution_ok") is True and _d12d.get("user_id") == "userB",
      repr((_d12d.get("user_id"), _d12d.get("attribution_ok"))))
# 回应他人（非点名者）→ mention_responded=False
_DBP_U12E = os.path.join(TMP_IO, "db_u12e.sqlite")
if os.path.exists(_DBP_U12E):
    os.remove(_DBP_U12E)
_agent12e = AgentBridge("agent:u12", "agent:u12", _DBP_U12E, _llm_reply_userC)
_d12e = _agent12e.process_batch(_msgs_u12, round_no=1, mention_targets=["agent:u12"])
check("U12.4f 被 @ 但回应他人 userC → mention_responded=False",
      _d12e.get("mention_responded") is False, repr(_d12e.get("mention_responded")))
check("U12.4g 回应末位 → reply_target_pos=len-1（末位偏置可量化）",
      _d12e.get("reply_target_pos") == len(_msgs_u12) - 1,
      repr(_d12e.get("reply_target_pos")))

# ── U12.5 P1-6：演化兜底阈值 30→10（降阈值生效） ──
print("\n== U12.5 P1-6 演化兜底阈值 ==")
from personality import _FALLBACK_TRIGGER_COUNT
check("U12.5a 兜底触发阈值已降至 10",
      _FALLBACK_TRIGGER_COUNT == 10, str(_FALLBACK_TRIGGER_COUNT))
_evo12 = PersonalityEvolution({"warmth": 0.6, "playfulness": 0.4,
                               "directness": 0.5, "curiosity": 0.5})
_style_hi = {"warmth": 0.9, "playfulness": 0.3,
             "directness": 0.5, "curiosity": 0.5}
for _i in range(9):
    _evo12.observe_feedback(_style_hi, "neutral", mood=0.0)
check("U12.5b 9 次 neutral 高风格观测仍未触发（阈值=10）",
      abs(_evo12.vector["warmth"] - 0.6) < 1e-9,
      f"warmth={_evo12.vector['warmth']:.6f}")
_evo12.observe_feedback(_style_hi, "neutral", mood=0.0)
check("U12.5c 第 10 次触发演化（warmth 向 0.9 收敛）",
      _evo12.vector["warmth"] > 0.6,
      f"warmth={_evo12.vector['warmth']:.6f}")

# ── U12.6 数据采集：memory_hits / silent_cognition 落盘（P0-1/P0-2） ──
print("\n== U12.6 采集字段落盘（memory_hits / silent_cognition） ==")
from memos import _record_hits as _memos_record_hits
# 决策层：pending 携带 memory_hits → 批量决策返回该字段
_memos_record_hits([{"id": 7, "table": "long_term_memory", "score": 0.83,
                     "adopted": True}])
_DBP_U12F = os.path.join(TMP_IO, "db_u12f.sqlite")
if os.path.exists(_DBP_U12F):
    os.remove(_DBP_U12F)
_node12 = aaa_main.MyNode()
_node12._pending_contexts["r1_u12"] = {
    "user_text": "测试", "identity_key": "agent:u12", "user_id": "userA",
    "memory_hits": memos.get_last_hits(),
}
_d12f = _node12._on_parsed({
    "data_type": "parsed", "source": "llm", "request_id": "r1_u12",
    "content": _SILENT_TEXT,
}, _DBP_U12F, {}, user_id="", batch_mode=True)
check("U12.6a 静默决策返回 memory_hits 字段（P0-1 采集）",
      isinstance(_d12f.get("memory_hits"), list)
      and _d12f["memory_hits"] and _d12f["memory_hits"][0]["id"] == 7,
      repr(_d12f.get("memory_hits")))
check("U12.6b silent_cognition_written / cognition_sections 字段（P0-2 采集）",
      "silent_cognition_written" in _d12f and "cognition_sections" in _d12f,
      str({k: _d12f.get(k) for k in ("silent_cognition_written",
                                     "cognition_sections")}))
# DB 层：_on_parsed 已异步触发 record_memory_usage / record_silent_cognition
# （上面 U12.6a/b 的调用即写入），此处用独立库直测同步写函数本身
from db import _write_memory_usage as _mu_write, _write_silent_cognition as _sc_write
_DBP_U12G = os.path.join(TMP_IO, "db_u12g.sqlite")
if os.path.exists(_DBP_U12G):
    os.remove(_DBP_U12G)
db.ensure(_DBP_U12G)
_mu_write(_DBP_U12G, "agent:u12", "r1_u12",
          [{"id": 7, "table": "long_term_memory", "score": 0.83, "adopted": True}])
_sc_write(_DBP_U12G, "agent:u12", "r1_u12", "这条消息听过了，不必回应",
          True, "他人认知,事件摘要")
_conn_u12f = sqlite3.connect(_DBP_U12G)
_n_mu = _conn_u12f.execute("SELECT COUNT(*) FROM memory_usage").fetchone()[0]
_n_sc = _conn_u12f.execute("SELECT COUNT(*) FROM silent_cognition").fetchone()[0]
_conn_u12f.close()
check("U12.6c memory_usage 表落盘（决策→命中记忆证据链）",
      _n_mu == 1, str(_n_mu))
check("U12.6d silent_cognition 表落盘（静默≠无认知）",
      _n_sc == 1, str(_n_sc))

# ── U12.7 数据采集：topic_report 新统计节渲染（P0-3/P1-4/P1-5/P2-6/P2-7） ──
print("\n== U12.7 topic_report 数据采集统计节 ==")
from message_pool.topic_report import (
    _render_position_bias, _render_mention_attribution, _render_mood_behavior,
    _render_memory_hits, _render_silent_cognition, _render_trajectory,
    _render_cognition_timeline)
_fix_dec = [
    {"agent": "agent:0", "action": "reply", "round": 1, "回应对象": "userA",
     "reply_target_pos": 0, "batch_last_author": "userC",
     "batch_context": [{"user_id": "userA", "seq": 1}, {"user_id": "userB", "seq": 2},
                       {"user_id": "userC", "seq": 3}],
     "mention_targets": ["agent:0"], "mention_responded": True,
     "attribution_ok": True, "user_id": "userA",
     "memory_hits": [{"id": 1, "table": "long_term_memory", "score": 0.8}],
     "silent_cognition_written": False, "cognition_sections": "",
     "personality": {"warmth": 0.6, "playfulness": 0.5, "directness": 0.5,
                     "curiosity": 0.5}, "mood": 0.5},
    {"agent": "agent:0", "action": "reply", "round": 2, "回应对象": "userC",
     "reply_target_pos": 2, "batch_last_author": "userC",
     "batch_context": [{"user_id": "userA", "seq": 4}, {"user_id": "userB", "seq": 5},
                       {"user_id": "userC", "seq": 6}],
     "mention_targets": [], "mention_responded": False,
     "attribution_ok": True, "user_id": "userC",
     "memory_hits": [], "silent_cognition_written": False, "cognition_sections": "",
     "personality": {"warmth": 0.62, "playfulness": 0.5, "directness": 0.5,
                     "curiosity": 0.5}, "mood": 0.3},
    {"agent": "agent:0", "action": "silent", "round": 3, "user_id": "",
     "memory_hits": [], "silent_cognition_written": True,
     "cognition_sections": "他人认知,事件摘要",
     "personality": {"warmth": 0.62, "playfulness": 0.5, "directness": 0.5,
                     "curiosity": 0.5}, "mood": 0.0},
    # 认知网络时序：r3 写「他人认知」且归因到另一 agent → 认知边
    {"agent": "agent:0", "action": "reply", "round": 3, "回应对象": "agent:1",
     "reply_target_pos": 1, "batch_last_author": "agent:1",
     "batch_context": [{"user_id": "agent:1", "seq": 7}],
     "mention_targets": [], "mention_responded": False,
     "attribution_ok": True, "user_id": "agent:1",
     "memory_hits": [], "silent_cognition_written": False,
     "cognition_sections": "他人认知",
     "personality": {"warmth": 0.62, "playfulness": 0.5, "directness": 0.5,
                     "curiosity": 0.5}, "mood": 0.1},
    # 反向认知边（agent:1 → agent:0）→ 双向认知组形成
    {"agent": "agent:1", "action": "reply", "round": 4, "回应对象": "agent:0",
     "reply_target_pos": 0, "batch_last_author": "agent:0",
     "batch_context": [{"user_id": "agent:0", "seq": 8}],
     "mention_targets": [], "mention_responded": False,
     "attribution_ok": True, "user_id": "agent:0",
     "memory_hits": [], "silent_cognition_written": False,
     "cognition_sections": "他人认知",
     "personality": {"warmth": 0.6, "playfulness": 0.5, "directness": 0.5,
                     "curiosity": 0.5}, "mood": 0.1},
]
_fix_evo = {"trajectory": {"agent:0": [
    {"round": 1, "vector": {"warmth": 0.6, "playfulness": 0.5,
                            "directness": 0.5, "curiosity": 0.5}},
    {"round": 2, "vector": {"warmth": 0.62, "playfulness": 0.5,
                            "directness": 0.5, "curiosity": 0.5}},
    {"round": 3, "vector": {"warmth": 0.62, "playfulness": 0.5,
                            "directness": 0.5, "curiosity": 0.5}}]}}
_pos_bias = _render_position_bias(_fix_dec)
_mention = _render_mention_attribution(_fix_dec, ["agent:0"])
_mood_beh = _render_mood_behavior(_fix_dec, ["agent:0"])
_mem_hits = _render_memory_hits(_fix_dec, ["agent:0"])
_sil_cog = _render_silent_cognition(_fix_dec, ["agent:0"])
_traj = _render_trajectory(_fix_evo)
_tl = _render_cognition_timeline(_fix_dec, ["agent:0", "agent:1"])
check("U12.7a 位置对照节（P2-6）：末位回应率量化",
      "末位回应率" in _pos_bias and "50.0%" in _pos_bias, _pos_bias[:120])
check("U12.7b @提及节（P1-5）：点名响应率 + 归因正确率",
      "点名者被回应" in _mention and "归因正确" in _mention, _mention[:160])
check("U12.7c 情绪-行为节（P2-7）：reply/silent 平均 mood 对照",
      "reply 平均 mood" in _mood_beh and "silent 平均 mood" in _mood_beh,
      _mood_beh[:120])
check("U12.7d 记忆命中节（P0-1）：命中条目统计",
      "命中 1 条记忆" in _mem_hits, _mem_hits[:120])
check("U12.7e 静默认知节（P0-2）：仍写认知计数",
      "静默轮仍在沉淀认知" in _sil_cog and "他人认知×1" in _sil_cog,
      _sil_cog[:160])
check("U12.7f 轨迹节（P0-3）：首动轮次标注（r2 首次变化）",
      "首动轮次" in _traj and "r2" in _traj, _traj[:160])
check("U12.7g 认知网络时序节（P1-4）：逐轮累计边 + 双向组数",
      "累计边数" in _tl and "agent:0↔agent:1" in _tl, _tl[:160])

print("\n== U13 v7.0 兴趣门控 ==")
import numpy as np
from message_pool.interest_gate import InterestGate


def _fake_enc(texts):
    """确定性伪编码器（验收用，不加载模型）：关键词→正交向量，其余→兜底向量。"""
    _KW = [("猫", [1.0, 0.0, 0.0, 0.0]),
           ("做饭", [0.0, 1.0, 0.0, 0.0]),
           ("天气", [0.0, 0.0, 1.0, 0.0])]
    out = []
    for t in texts:
        v = [0.0, 0.0, 0.0, 1.0]
        for kw, vec in _KW:
            if kw in t:
                v = vec
                break
        out.append(v)
    a = np.asarray(out, dtype="float64")
    return a / np.linalg.norm(a, axis=1, keepdims=True)


# U13.1 编码一次（同文本只编码一次，缓存复用）
_g = InterestGate(threshold=0.6, encoder=_fake_enc)
_v = _g.encode(["我养了一只猫", "我养了一只猫"])
check("U13.1a 编码一次：批内同文本只编码一次（encode_calls==1）",
      _g.encode_calls == 1, f"calls={_g.encode_calls}")
check("U13.1b 编码缓存：同文本两次向量一致",
      bool(np.allclose(_v[0], _v[1])))
_g.encode(["我养了一只猫"])
check("U13.1c 编码缓存：重复调用不再触发编码（calls 仍为 1）",
      _g.encode_calls == 1, f"calls={_g.encode_calls}")

# U13.2 门控判定（阈值 0.6：同主题 sim=1.0 过门，异主题 sim=0.0 拒绝）
_g2 = InterestGate(threshold=0.6, encoder=_fake_enc)
_g2.set_anchor("agent:0", "我养了一只猫")
_msgs = [{"seq": 1, "user_id": "userA", "content": "有人推荐个电影吗", "reply_to": ""},
         {"seq": 2, "user_id": "userB", "content": "今天天气真好", "reply_to": ""},
         {"seq": 3, "user_id": "userC", "content": "我也喜欢猫", "reply_to": ""}]
_j = _g2.judge("agent:0", _msgs)
check("U13.2a 兴趣过门：最高兴趣消息命中（猫=1.0），检测文本+seq 正确",
      _j["passed"] and _j["reason"] == "interest"
      and _j["detected_text"] == "我也喜欢猫" and _j["seq"] == 3
      and _j["interest_value"] == 1.0, str(_j))
_jn = _g2.judge("agent:0", _msgs[:2])
check("U13.2b 兴趣不足：max_sim=0.0 < 0.6 → 未过门（reason=none）",
      (not _jn["passed"]) and _jn["reason"] == "none"
      and _jn["interest_value"] == 0.0, str(_jn))
_hit = {"seq": 9, "user_id": "userX", "content": "随便聊聊", "reply_to": "agent:0"}
_jd = _g2.judge("agent:0", [dict(_hit)], direct_hits=[dict(_hit)])
check("U13.2c 直接过门：reply_to==agent → reason=direct 过门（不经阈值）",
      _jd["passed"] and _jd["reason"] == "direct" and _jd["seq"] == 9, str(_jd))
_g3 = InterestGate(threshold=0.95, encoder=_fake_enc)
_g3.set_anchor("agent:0", "我养了一只猫")
check("U13.2d 阈值可配：0.95 下猫(1.0)过门、电影(0.0)拒绝",
      _g3.judge("agent:0", _msgs[2:])["passed"]
      and not _g3.judge("agent:0", _msgs[:1])["passed"])

# U13.3 兴趣锚点更新
_g4 = InterestGate(threshold=0.6, encoder=_fake_enc)
check("U13.3a 初始无锚点", _g4.get_anchor("agent:0") == "")
_g4.set_anchor("agent:0", "我今天做了饭")
check("U13.3b 锚点=最近发言", _g4.get_anchor("agent:0") == "我今天做了饭")
_g4.set_anchor("agent:0", "   ")
check("U13.3c 空文本不覆盖锚点", _g4.get_anchor("agent:0") == "我今天做了饭")

# U13.4 判定落库（用户要求：检测文本 + 兴趣值写入数据库）
_DBP_U13G = os.path.join(TMP_IO, "db_u13g.sqlite")
if os.path.exists(_DBP_U13G):
    os.remove(_DBP_U13G)
_g5 = InterestGate(threshold=0.6, encoder=_fake_enc)
_g5.set_anchor("agent:0", "我养了一只猫")
_g5.write_judgment(_DBP_U13G, "agent:0", 1,
                   _g5.judge("agent:0", [{"seq": 5, "user_id": "userC",
                                          "content": "我也喜欢猫", "reply_to": ""}]))
_g5.write_judgment(_DBP_U13G, "agent:0", 2,
                   _g5.judge("agent:0", [{"seq": 6, "user_id": "userA",
                                          "content": "推荐个电影", "reply_to": ""}]))
_c13g = sqlite3.connect(_DBP_U13G)
_r13g = _c13g.execute(
    "SELECT detected_text, interest_value, passed, reason "
    "FROM interest_judgment ORDER BY rowid").fetchall()
_c13g.close()
check("U13.4a 落库字段：检测文本/兴趣值/过门/原因 逐条写入",
      len(_r13g) == 2 and _r13g[0] == ("我也喜欢猫", 1.0, 1, "interest")
      and _r13g[1][2] == 0 and _r13g[1][3] == "none", str(_r13g))

# U13.5 平台集成：门控预筛（未过门 agent 不调 LLM）+ 判定自动落库
_U13_A = os.path.join(TMP_IO, "db_u13a.sqlite")
_U13_B = os.path.join(TMP_IO, "db_u13b.sqlite")
for _p_ in (_U13_A, _U13_B):
    if os.path.exists(_p_):
        os.remove(_p_)


def _u13_llm(prompt):
    return ("【自然回复】\n猫真可爱\n【回应对象】\nuserC\n【心情】\n开心\n"
            "【想法】\n想回应\n【情绪调整】\n0.05\n"
            "【事件摘要】\n用户发言，AI 回应 [重要性:3]\n"
            "【他人认知】\n这个用户很活跃")


_gate5 = InterestGate(threshold=0.6, encoder=_fake_enc)
_a5 = AgentBridge("agent:alpha", "agent:alpha", _U13_A, _u13_llm)
_b5 = AgentBridge("agent:beta", "agent:beta", _U13_B, _u13_llm)
_gate5.set_anchor("agent:alpha", "我养了一只猫")
_gate5.set_anchor("agent:beta", "我想学做饭")
_p5 = MessagePoolPlatform([_a5, _b5], run_dir=None, gate=_gate5, topic_rounds=0)
_p5.inject([{"content": "我也养猫了", "user_id": "userC"}])
_sp5 = _p5.step()
check("U13.5a 平台集成：感兴趣者（alpha）过门并发言",
      _sp5 is not None and _sp5[0] == "agent:alpha", str(_sp5))
check("U13.5b 平台集成：不感兴趣者（beta）未过门，不调 LLM",
      _b5._inline_llm_calls == 0, f"beta calls={_b5._inline_llm_calls}")
_ca = sqlite3.connect(_U13_A)
_na = _ca.execute("SELECT COUNT(*) FROM interest_judgment").fetchone()[0]
_ca.close()
_cb = sqlite3.connect(_U13_B)
_nb = _cb.execute("SELECT COUNT(*) FROM interest_judgment").fetchone()[0]
_cb.close()
check("U13.5c 平台集成：每 agent 判定落库 1 条",
      _na == 1 and _nb == 1, f"alpha={_na} beta={_nb}")

# U13.6 仲裁优先级：@ 点名 > 兴趣 > 冷板凳（被回应少者优先）
_U13_C = os.path.join(TMP_IO, "db_u13c.sqlite")
_U13_D = os.path.join(TMP_IO, "db_u13d.sqlite")
_U13_E = os.path.join(TMP_IO, "db_u13e.sqlite")
_U13_F = os.path.join(TMP_IO, "db_u13f.sqlite")
for _p_ in (_U13_C, _U13_D, _U13_E, _U13_F):
    if os.path.exists(_p_):
        os.remove(_p_)


def _u13_llm6(prompt):
    return ("【自然回复】\n好的\n【回应对象】\nuserD\n【心情】\n开心\n"
            "【想法】\n想回应\n【情绪调整】\n0.05\n"
            "【事件摘要】\n用户发言，AI 回应 [重要性:3]\n"
            "【他人认知】\n这个用户很活跃")


_gate6 = InterestGate(threshold=0.6, encoder=_fake_enc)
_a6 = AgentBridge("agent:alpha", "agent:alpha", _U13_C, _u13_llm6)
_b6 = AgentBridge("agent:beta", "agent:beta", _U13_D, _u13_llm6)
_gate6.set_anchor("agent:alpha", "我养了一只猫")
_gate6.set_anchor("agent:beta", "我养了一只猫")
_p6 = MessagePoolPlatform([_a6, _b6], run_dir=None, gate=_gate6, topic_rounds=0)
_p6.inject([{"content": "@agent:beta 你也养猫吗", "user_id": "userD"}])
_sp6 = _p6.step()
check("U13.6a 仲裁 @ 优先：被点名者（beta）先发言",
      _sp6 is not None and _sp6[0] == "agent:beta", str(_sp6))

_gate7 = InterestGate(threshold=0.6, encoder=_fake_enc)
_a7 = AgentBridge("agent:alpha", "agent:alpha", _U13_E, _u13_llm6)
_b7 = AgentBridge("agent:beta", "agent:beta", _U13_F, _u13_llm6)
_gate7.set_anchor("agent:alpha", "我养了一只猫")
_gate7.set_anchor("agent:beta", "我养了一只猫")
_p7 = MessagePoolPlatform([_a7, _b7], run_dir=None, gate=_gate7, topic_rounds=0)
_p7._responded["agent:alpha"] = 0
_p7._responded["agent:beta"] = 5
_p7.inject([{"content": "我也养猫了", "user_id": "userE"}])
_sp7 = _p7.step()
check("U13.6b 仲裁 冷板凳优先：同兴趣时被回应少者（alpha）先发言",
      _sp7 is not None and _sp7[0] == "agent:alpha", str(_sp7))

# ── U13.7 v7.1 近期观察记录注入（interest_judgment 未过门文本回流上下文） ──
print("\n== U13.7 v7.1 近期观察记录注入 ==")
_OBS_DB = os.path.join(TMP_IO, "obs_gate.sqlite")
if os.path.exists(_OBS_DB):
    os.remove(_OBS_DB)
_oconn = sqlite3.connect(_OBS_DB)
_oconn.executescript(InterestGate._TABLE_SQL)
_oconn.execute(
    "INSERT INTO interest_judgment(identity_key, round_no, message_seq, detected_text, "
    "anchor_text, interest_value, passed, reason) VALUES(?,?,?,?,?,?,?,?)",
    ("agent:alpha", 1, 1, "冷笑话挺好笑的", "我养了一只猫", 0.30, 0, "none"))
_oconn.execute(
    "INSERT INTO interest_judgment(identity_key, round_no, message_seq, detected_text, "
    "anchor_text, interest_value, passed, reason) VALUES(?,?,?,?,?,?,?,?)",
    ("agent:alpha", 2, 2, "冷笑话挺好笑的", "我养了一只猫", 0.29, 0, "none"))  # 重复文本
_oconn.execute(
    "INSERT INTO interest_judgment(identity_key, round_no, message_seq, detected_text, "
    "anchor_text, interest_value, passed, reason) VALUES(?,?,?,?,?,?,?,?)",
    ("agent:alpha", 3, 3, "拼盘这比喻贴切", "我养了一只猫", 0.51, 0, "none"))
_oconn.execute(
    "INSERT INTO interest_judgment(identity_key, round_no, message_seq, detected_text, "
    "anchor_text, interest_value, passed, reason) VALUES(?,?,?,?,?,?,?,?)",
    ("agent:alpha", 4, 4, "我回应了这条消息", "冷笑话挺好笑的", 0.95, 1, "interest"))  # 过门不注入
_oconn.execute(
    "INSERT INTO interest_judgment(identity_key, round_no, message_seq, detected_text, "
    "anchor_text, interest_value, passed, reason) VALUES(?,?,?,?,?,?,?,?)",
    ("agent:alpha", 5, 5, "今天天气不错", "冷笑话挺好笑的", 0.42, 0, "none"))
_oconn.execute(
    "INSERT INTO interest_judgment(identity_key, round_no, message_seq, detected_text, "
    "anchor_text, interest_value, passed, reason) VALUES(?,?,?,?,?,?,?,?)",
    ("agent:beta", 5, 5, "别人的记录不该注入", "别人锚点", 0.50, 0, "none"))  # 其他 agent 隔离
_oconn.commit()
_obs_full = db.read_recent_observations(_oconn, "agent:alpha", 5)
check("U13.7a 观察记录：只取 passed=0 且按 id 倒序去重（含天气/拼盘/冷笑话，不含过门与它人）",
      ("今天天气不错" in _obs_full and "拼盘这比喻贴切" in _obs_full
       and "冷笑话挺好笑的" in _obs_full
       and "我回应了这条消息" not in _obs_full
       and "别人的记录不该注入" not in _obs_full), repr(_obs_full))
_obs_lim = db.read_recent_observations(_oconn, "agent:alpha", 2)
check("U13.7b 观察记录上限：limit=2 只取最新 2 条",
      _obs_lim.count("今天天气不错") == 1 and _obs_lim.count("拼盘这比喻贴切") == 1
      and "冷笑话挺好笑的" not in _obs_lim, repr(_obs_lim))
_oconn.close()
_empty_db = os.path.join(TMP_IO, "obs_empty.sqlite")
if os.path.exists(_empty_db):
    os.remove(_empty_db)
_econn = sqlite3.connect(_empty_db)  # 无 interest_judgment 表
check("U13.7c 观察记录容错：表不存在返回空串（不报错）",
      db.read_recent_observations(_econn, "agent:alpha", 5) == "")
_econn.close()
# prompt 渲染集成：观察记录注入【近期观察记录】节；为空时不渲染该节
_obs_conn = sqlite3.connect(_OBS_DB)
_obs_ctx = {
    "identity_key": "agent:alpha", "self_cognition": "", "fixed_cognition": "",
    "recent_feelings": "", "other_cognition": "", "user_text": "本轮测试",
    "current_date": "2026-08-08", "current_time": "12:00:00",
    "history_summary": "", "user_info": "", "self_info": "",
    "attachment_context": "",
    "recent_observations": db.read_recent_observations(_obs_conn, "agent:alpha", 5),
}
_obs_conn.close()
_obs_prompt = _pt.build(dict(_obs_ctx))
check("U13.7d prompt 集成：上下文含【近期观察记录】节与最新检测文本",
      "【近期观察记录】（你最近看过但未回应的消息，可参考）" in _obs_prompt
      and "今天天气不错" in _obs_prompt, "节缺失")
_obs_ctx["recent_observations"] = ""
_obs_empty_prompt = _pt.build(dict(_obs_ctx))
check("U13.7e prompt 集成：观察记录为空时不渲染该节（1对1/无记录不干扰）",
      "近期观察记录" not in _obs_empty_prompt, "空记录仍渲染")

# ── U13.8 v7.2 接话切入判定 + 窗口拼接 ──────────────────────
print("\n== U13.8 v7.2 接话切入判定 + 窗口拼接 ==")
_g8 = InterestGate(threshold=0.6, encoder=_fake_enc)
_g8.set_anchor("agent:3", "我养了一只猫")
_msgs8 = [{"seq": 1, "user_id": "userA", "content": "今天天气不错", "reply_to": ""},
          {"seq": 2, "user_id": "agent:2", "content": "我也养猫了！", "reply_to": ""},
          {"seq": 3, "user_id": "userA", "content": "聊点电影吧", "reply_to": ""}]
_res8 = _g8.judge_sequence("agent:3", _msgs8)
# 逐条发言判定（不去重）：seq1 天气拒 → seq2 猫过门（次早）→ seq3 电影拒
check("U13.8a 时间从旧到新逐条判定：第一个过门者为接话切入点（天气拒→猫过门→电影拒）",
      _res8["target"] is not None
      and _res8["target"]["seq"] == 2
      and _res8["target"]["target_speaker"] == "agent:2"
      and _res8["target"]["reason"] == "interest"
      and len(_res8["records"]) == 3
      and _res8["records"][0]["seq"] == 1       # 最早：1 的第一次发言
      and not _res8["records"][0]["passed"]
      and _res8["records"][1]["seq"] == 2       # 次早：2 的发言（第二条）
      and _res8["records"][1]["passed"]
      and _res8["records"][2]["seq"] == 3
      and not _res8["records"][2]["passed"],
      str([(r["seq"], r["interest_value"], r["passed"]) for r in _res8["records"]]))
_msgs8b = [{"seq": 1, "user_id": "userA", "content": "我也养猫了", "reply_to": ""},
           {"seq": 2, "user_id": "userB", "content": "我想学做饭", "reply_to": ""}]
_res8b = _g8.judge_sequence("agent:3", _msgs8b)
check("U13.8b 时间从旧到新：先判最早的猫(seq1)过门 → 切入点=猫 seq1",
      _res8b["target"]["seq"] == 1
      and _res8b["records"][0]["seq"] == 1
      and _res8b["records"][0]["passed"]
      and _res8b["records"][1]["seq"] == 2
      and not _res8b["records"][1]["passed"],
      str([(r["seq"], r["passed"]) for r in _res8b["records"]]))
_direct8c = {"seq": 6, "user_id": "userX", "content": "@agent:3 你在吗", "reply_to": ""}
_res8c = _g8.judge_sequence("agent:3",
                            [{"seq": 5, "user_id": "userA",
                              "content": "推荐个电影", "reply_to": ""},
                             dict(_direct8c)],
                            direct_hits=[dict(_direct8c)])
check("U13.8c direct 优先：@ 命中直接过门，切入点=点名消息（不经兴趣）",
      _res8c["target"]["reason"] == "direct"
      and _res8c["target"]["seq"] == 6, str(_res8c["target"]))

# U13.8d 窗口计算（platform）：从 agent 最近发言后到切入消息，不含自己发言
_p8d = MessagePoolPlatform([_a6, _b6], run_dir=None, gate=None, topic_rounds=0)
_p8d.announce("今天聊猫", user_id="platform")                            # seq1
_p8d._feed_agent_speech("agent:alpha", "我喜欢猫", reply_to="")           # seq2
_p8d.inject([{"content": "你们觉得呢", "user_id": "userA"}])               # seq3
_p8d._feed_agent_speech("agent:beta", "我也养猫了", reply_to="agent:alpha")  # seq4
_p8d.inject([{"content": "猫真可爱", "user_id": "userB"}])                 # seq5
_w8d = _p8d._window_for("agent:alpha", 5)
check("U13.8d 窗口计算：alpha 窗口=(seq2,seq5]，不含自己发言",
      [m["seq"] for m in _w8d] == [3, 4, 5]
      and all(m["user_id"] != "agent:alpha" for m in _w8d), str(_w8d))
_w8d2 = _p8d._window_for("agent:gamma", 5)  # 未发言 → 下界=消息池起点
check("U13.8d2 窗口计算：未发言 agent 窗口下界=消息池起点（seq1 起）",
      [m["seq"] for m in _w8d2] == [1, 2, 3, 4, 5], str(_w8d2))

# U13.8e 平台集成：step 传窗口 → decisions batch_context=窗口 / batch_full=完整批
# 两个 Fake LLM 回复各自主题（alpha 回"猫"、beta 回"做饭"），避免锚点漂移导致
# alpha 对 beta 的"好的"发言过门（U13.8e 旧失败根因）。
def _u13_llm_a8(prompt):
    return ("【自然回复】\n我也喜欢猫\n【回应对象】\nuserC\n【心情】\n开心\n"
            "【想法】\n想回应\n【情绪调整】\n0.05\n"
            "【事件摘要】\n用户发言，AI 回应 [重要性:3]\n"
            "【他人认知】\n这个用户很活跃")


def _u13_llm_b8(prompt):
    return ("【自然回复】\n我想学做饭了\n【回应对象】\nuserC\n【心情】\n开心\n"
            "【想法】\n想回应\n【情绪调整】\n0.05\n"
            "【事件摘要】\n用户发言，AI 回应 [重要性:3]\n"
            "【他人认知】\n这个用户很活跃")


_U13_G1 = os.path.join(TMP_IO, "db_u13g1.sqlite")
_U13_G2 = os.path.join(TMP_IO, "db_u13g2.sqlite")
for _p_ in (_U13_G1, _U13_G2):
    if os.path.exists(_p_):
        os.remove(_p_)
_run8 = os.path.join(TMP_IO, "runs", "20260808_u138e", "run")
_gate8e = InterestGate(threshold=0.6, encoder=_fake_enc)
_a8e = AgentBridge("agent:alpha", "agent:alpha", _U13_G1, _u13_llm_a8)
_b8e = AgentBridge("agent:beta", "agent:beta", _U13_G2, _u13_llm_b8)
_gate8e.set_anchor("agent:alpha", "我养了一只猫")
_gate8e.set_anchor("agent:beta", "我想学做饭")
_p8e = MessagePoolPlatform([_a8e, _b8e], run_dir=_run8, gate=_gate8e,
                           topic_rounds=0)
_p8e.inject([{"content": "我也养猫了", "user_id": "userC"}])              # seq1
_p8e.step()                                                          # alpha 发言 → seq2
_p8e.inject([{"content": "我想学做饭", "user_id": "userC"}])             # seq3
_p8e.step()                                                          # beta 发言 → seq4（alpha 避让）
_p8e.inject([{"content": "今天天气不错", "user_id": "userA"},             # seq5
             {"content": "我也喜欢猫", "user_id": "userB"},              # seq6
             {"content": "我想学做饭", "user_id": "userC"}])             # seq7
_p8e.step()                                                          # beta 避让，alpha 判定
_alpha_d = None
with open(os.path.join(_run8, "decisions.jsonl"), encoding="utf-8") as _f8:
    for _line in _f8:
        if not _line.strip():
            continue
        _d = json.loads(_line)
        if _d.get("agent") == "agent:alpha" and _d.get("round") == 3:
            _alpha_d = _d
check("U13.8e 平台集成：alpha 决策上下文=窗口(seq2,seq6]=[3,4,5,6]，"
      "batch_full=[4,5,6]（seq7 与 seq3 同文去重不入池）",
      _alpha_d is not None
      and [m["seq"] for m in _alpha_d["batch_context"]] == [3, 4, 5, 6]
      and _alpha_d["window_size"] == 4
      and [m["seq"] for m in _alpha_d["batch_full"]] == [4, 5, 6]
      and _alpha_d["batch_size"] == 3,
      str(_alpha_d and ([m["seq"] for m in _alpha_d.get("batch_context", [])],
                        [m["seq"] for m in _alpha_d.get("batch_full", [])])))

print(f"\n总结果: {PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
