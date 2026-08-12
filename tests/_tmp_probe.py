# -*- coding: utf-8 -*-
"""探测真实模型名可用性（DashScope）"""
import json, os, urllib.request, urllib.error

KEY = os.environ.get("QWEN_API_KEY", "sk-ebf313d84a9e45ce9529dc197e2ea848")
URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MODELS = ["qwen3.7-max", "glm-5.2", "qwen3.5-flash", "qwen3.7-plus"]

def probe(model):
    body = {"model": model,
            "messages": [{"role": "user", "content": "ping"}],
            "temperature": 0.0, "max_tokens": 5}
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + KEY})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return "OK: " + str(data["choices"][0]["message"]["content"])[:40]
    except urllib.error.HTTPError as e:
        return "HTTP {}: {}".format(e.code, e.read().decode("utf-8")[:200])
    except Exception as e:
        return "ERR: " + str(e)[:150]

for m in MODELS:
    print("[{}] -> {}".format(m, probe(m)), flush=True)
