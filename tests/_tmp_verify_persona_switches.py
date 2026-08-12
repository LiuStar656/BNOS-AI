# -*- coding: utf-8 -*-
"""v8.x 人格注入双开关验证：
1. build_personality_section 四态组合输出正确（锚点/指令是否出现）
2. set_personality_mode 热切换 + 持久化（写库 → 重读 → 确认）
3. save_personality 位置参数兼容（第5位 identity_key 不被破坏）
"""
import os
import sys
import tempfile

NODE_DIR = r"E:\杂项\BNOS_AI_project\nodes\node_python_aaa_cognition"
sys.path.insert(0, NODE_DIR)

import personality as prs
import db

FAIL = []


def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    if not cond:
        FAIL.append(name)
    print(f"[{tag}] {name}  {detail}")


V = {"warmth": 0.8, "playfulness": 0.9, "directness": 0.3, "curiosity": 0.6}
STYLE = "你说话热情好奇。"

# ── 1. 四态组合输出 ──────────────────────────────
s_both = prs.build_personality_section(V, STYLE, True, True)
s_anchor = prs.build_personality_section(V, STYLE, True, False)
s_instr = prs.build_personality_section(V, STYLE, False, True)
s_bare = prs.build_personality_section(V, STYLE, False, False)

def dims_line(s):
    """取维度行（第3行），锚点判断只针对它（标题/定义行本身含全角括号）"""
    return s.split("\n")[2]

check("锚点开: 含五档描述（（）括号锚点）", "（" in dims_line(s_anchor), dims_line(s_anchor)[:80])
check("锚点关: 无括号描述", "（" not in dims_line(s_instr), dims_line(s_instr)[:80])
check("指令开: 含激活指令", "以上性格数值" in s_instr)
check("指令关: 无激活指令", "以上性格数值" not in s_anchor)
check("两者开=锚点+指令", "（" in dims_line(s_both) and "以上性格数值" in s_both)
check("两者关=纯数值(有定义行无锚点无指令)",
      "（" not in dims_line(s_bare) and "以上性格数值" not in s_bare
      and "0-1 范围" in s_bare)
check("style_description 四态都保留", all(STYLE in s for s in (s_both, s_anchor, s_instr, s_bare)))
check("默认参数=锚点开指令关（生产现状）",
      "（" in dims_line(prs.build_personality_section(V, STYLE))
      and "以上性格数值" not in prs.build_personality_section(V, STYLE))

print("\n── 四态输出对比（playfulness 行）──")
for name, s in (("锚+令", s_both), ("锚", s_anchor), ("令", s_instr), ("裸数值", s_bare)):
    line = [l for l in s.split("\n") if "活泼度" in l][0]
    print(f"  {name}: {line}")

# ── 2. set_personality_mode 热切换 + 持久化 ──────
tmp = os.path.join(tempfile.gettempdir(), "persona_switch_test.sqlite")
if os.path.exists(tmp):
    os.remove(tmp)
db.ensure(tmp)

r = db.set_personality_mode(tmp, anchor_enabled=False, instruction_enabled=True)
check("热切换: 写库返回新配置", r.get("anchor_enabled") is False
      and r.get("instruction_enabled") is True, repr(r))
r2 = db.get_personality(tmp)
check("持久化: 重读库仍为新配置", r2.get("anchor_enabled") is False
      and r2.get("instruction_enabled") is True)
check("持久化: 向量未被清空", r2.get("warmth") == 0.6 and r2.get("playfulness") == 0.4)

# 再切回（模拟开关往返）
r3 = db.set_personality_mode(tmp, anchor_enabled=True, instruction_enabled=False)
check("开关往返: 切回默认", r3.get("anchor_enabled") is True
      and r3.get("instruction_enabled") is False)

# ── 3. save_personality 位置参数兼容 ─────────────
ok = db.save_personality(tmp, V, STYLE, "活泼型", "gui:default")
g = db.get_personality(tmp, "gui:default")
check("save_personality: 第5位 identity_key 位置参数不破坏",
      ok and g.get("exists") and g.get("warmth") == 0.8,
      f"warmth={g.get('warmth')} preset={g.get('preset_name')}")
check("save_personality: 默认写入后开关=锚开令关",
      g.get("anchor_enabled") is True and g.get("instruction_enabled") is False)

# 演化写回保留开关：模拟 main.py _persist_evolution 流程（读 seed → 传回开关）
db.set_personality_mode(tmp, anchor_enabled=False, instruction_enabled=True)
_seed = db.get_personality(tmp, "gui:default")
db.save_personality(tmp, {"warmth": 0.5, "playfulness": 0.5,
                          "directness": 0.5, "curiosity": 0.5},
                    style_description="x", preset_name="默认",
                    anchor_enabled=_seed.get("anchor_enabled", True),
                    instruction_enabled=_seed.get("instruction_enabled", False),
                    identity_key="gui:default")
g2 = db.get_personality(tmp, "gui:default")
check("演化写回保留开关: 锚关令开仍保持",
      g2.get("anchor_enabled") is False and g2.get("instruction_enabled") is True)

os.remove(tmp)
print("\n" + ("全部通过" if not FAIL else f"失败: {FAIL}"))
sys.exit(1 if FAIL else 0)
