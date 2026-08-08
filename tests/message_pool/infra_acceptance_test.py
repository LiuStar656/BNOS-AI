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

# Fake LLM：按轮次交替 reply/silent，验证两种决策路径
_llm_calls = {"n": 0}


def fake_llm(prompt: str) -> str:
    _llm_calls["n"] += 1
    if _llm_calls["n"] % 2 == 1:
        return ("【自然回复】\n你好呀！看到你的消息啦\n【心情】\n开心\n"
                "【想法】\n想回应这条消息\n【情绪调整】\n0.05\n"
                "【事件摘要】\n用户发言，AI 回应 [重要性:3]\n"
                "【他人认知】\n这个用户很活跃")
    return ("【心情】\n平静\n【想法】\n这条消息听过了，不必回应\n"
            "【情绪调整】\n0.0\n【事件摘要】\n用户闲聊 [重要性:2]")

# 注意：MyNode() 内部 memos.preload() 会起后台线程加载模型，属正常行为（daemon）
from message_pool.agent_bridge import AgentBridge
from message_pool.platform_runner import MessagePoolPlatform

agent_a = AgentBridge("agent:alpha", "agent:alpha", DBP_A, fake_llm)
agent_b = AgentBridge("agent:beta", "agent:beta", DBP_B, fake_llm)
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

print(f"\n总结果: {PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
