# -*- coding: utf-8 -*-
"""验证 LLM 触发时机收紧（只有 reply/ask/silence 触发）：
monkey-patch mom_once 为计数桩（不真调 LLM），跑完整 440 tick，
统计触发分布。用法：python _tmp_verify_llm_trigger.py
"""
import sys
import io
import contextlib
from collections import Counter

sys.path.insert(0, "stage")
import _scene_mom_llm as S

calls = []


def stub(self, need_story, junk_txt, net_say, is_reply=False, is_ask=False):
    calls.append({"tick": self.tick, "story": need_story, "junk": bool(junk_txt),
                  "say": net_say, "reply": is_reply, "ask": is_ask})
    return None


S.SceneMomLLM.mom_once = stub
S._save_scene = lambda *a, **k: "test-no-save"   # 防污染快照链

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    S.main()

print(f"═══ LLM 触发时机验证（440 tick 完整场景，mom_once 桩）═══\n")
print(f"触发总次数: {len(calls)}（旧逻辑: 每次表达都触发——预计 30+ 次）")
print(f"触发类型分布:")
cnt = Counter()
for c in calls:
    if c["story"]:
        cnt["③沉默超时(讲故事)"] += 1
    elif c["reply"]:
        cnt["①守一主动回答"] += 1
    elif c["ask"]:
        cnt["②守一主动提问"] += 1
    else:
        cnt["其他(不应出现)"] += 1
for k, v in cnt.most_common():
    print(f"  {k:<20}{v} 次")
print(f"\n触发时刻: {[c['tick'] for c in calls][:40]}")
# 合法性：need_story 触发时 net_say 应为 None（沉默时没有表达）
bad = [c["tick"] for c in calls if c["story"] and c["say"]]
print(f"沉默触发却带表达（异常）: {bad if bad else '无 ✓'}")
# 间隔检查：last_call_tick 节流 ≥15
gaps = [calls[i+1]["tick"] - calls[i]["tick"] for i in range(len(calls)-1)]
print(f"调用间隔: min={min(gaps) if gaps else '-'}, max={max(gaps) if gaps else '-'}"
      f"（节流应 ≥15）")
