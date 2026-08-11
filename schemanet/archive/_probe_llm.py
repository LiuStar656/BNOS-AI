# -*- coding: utf-8 -*-
# 整理归档：项目根目录加入 import 路径（引擎/共享模块在根目录）
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""临时：DeepSeek API 连通性测试（用完即删）。"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _grow_v11 import _llm_chat

txt = _llm_chat([{"role": "user", "content": "请只回复两个字：连通"}])
if txt is None:
    print("连通测试失败：_llm_chat 返回 None（无 key / 调用失败）")
else:
    print("连通测试 OK，回复:", repr(txt))
