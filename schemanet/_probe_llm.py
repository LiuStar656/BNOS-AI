# -*- coding: utf-8 -*-
"""临时：DeepSeek API 连通性测试（用完即删）。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _grow_v11 import _llm_chat

txt = _llm_chat([{"role": "user", "content": "请只回复两个字：连通"}])
if txt is None:
    print("连通测试失败：_llm_chat 返回 None（无 key / 调用失败）")
else:
    print("连通测试 OK，回复:", repr(txt))
