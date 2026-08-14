"""
LLM 推理节点 - 路由入口

业务能力：
  - 本地推理（backends.py） → llama-server HTTP / llama-cli CLI
  - 云端推理（backends.py） → OpenAI / Anthropic / Google / DeepSeek / custom
  - 配置加载（config.py） → 惰性加载 node_config.json
"""
import sys
import json
import os
import time
import requests
import subprocess
from pathlib import Path

from config import load_config, extract_params
from backends import create_backend, LlamaServerBackend

# 节点任务活动状态文件（GUI 等待气泡实时文案的数据源，原子写）
_ACTIVITY_FILE = (
    Path(__file__).resolve().parent.parent / "shared" / "node_activity.json"
)


def _write_activity(stage: str, text: str, rid: str = "") -> None:
    """原子写节点活动状态（tmp + replace，避免并发写撕裂）。"""
    try:
        data = {"stage": stage, "text": text, "ts": time.time()}
        if rid:
            data["request_id"] = rid
        _ACTIVITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _ACTIVITY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_ACTIVITY_FILE)
    except OSError:
        pass


# ════════════════════════════════════════════════════════════════
#  ★ 开发者在此类中编写所有业务逻辑 — 其他代码不要修改 ★
# ════════════════════════════════════════════════════════════════

class MyNode:
    """
    LLM 推理节点业务逻辑处理器。

    后端懒初始化 —— 首次调用 process() 时才读取配置和启动后端。
    支持三种后端：http_server / cli_local / cloud（多供应商）。
    """

    def __init__(self):
        self._backend = None
        self._cfg = None

    # ── 框架入口 ──────────────────────────────────────────────
    def process(self, data: dict) -> dict:
        """
        框架入口，按 data_type / cmd 路由到对应 handler。

        参数:
            data: 上游传入的 JSON dict

        返回:
            dict / list[dict]: 带 _port 字段的路由结果
        """
        cmd = data.get("cmd")
        if cmd == "init_check":
            return self._handle_init_check()

        # 懒初始化后端
        if self._backend is None:
            self._cfg = load_config()
            params = extract_params(self._cfg)
            model_type = params.get("model_type", "http_server")
            self._backend = create_backend(model_type, params)

        # 透传 request_id（由 GUI 生成，节点间原样传递，用于 GUI 过滤过期回复）
        rid = data.get("request_id")

        # 提取 prompt 文本（兼容多种上游格式）
        prompt_text = (data.get("content") or data.get("data") or data.get("prompt") or "").strip()
        if not prompt_text:
            return {
                "_port": "default",
                "data_type": "text",
                "content": "",
                "error": "empty prompt",
                "request_id": rid,
            }

        params = extract_params(self._cfg)
        max_tokens = params.get("max_tokens", 2048)
        temperature = params.get("temperature", 0.7)

        # 上报活动状态：LLM 推理中（GUI 等待气泡实时显示，超时可定位卡点）
        _write_activity("llm", "LLM 推理中…", rid)

        try:
            result_text = self._backend.infer(prompt_text, max_tokens, temperature)
        except requests.RequestException as e:
            return {"_port": "default", "data_type": "text", "content": "", "error": str(e), "request_id": rid}
        except (subprocess.TimeoutExpired, TimeoutError) as e:
            return {"_port": "default", "data_type": "text", "content": "", "error": str(e), "request_id": rid}
        except FileNotFoundError as e:
            return {"_port": "default", "data_type": "text", "content": "", "error": str(e), "request_id": rid}
        except RuntimeError as e:
            return {"_port": "default", "data_type": "text", "content": "", "error": str(e), "request_id": rid}
        except Exception as e:
            return {"_port": "default", "data_type": "text", "content": "", "error": f"{type(e).__name__}: {e}", "request_id": rid}

        # 认知反思 prompt → review_response 端口，走独立通道回 AAA
        if data.get("source") == "review":
            output_port, output_source = "review_response", "review"
        # 日记 prompt → diary_response 端口，走独立通道回 AAA
        elif data.get("source") == "diary":
            output_port, output_source = "diary_response", "diary"
        else:
            output_port, output_source = "default", "llm"
        return {"_port": output_port, "data_type": "parsed", "content": result_text, "source": output_source, "request_id": rid}

    # ── init_check ────────────────────────────────────────────
    def _handle_init_check(self) -> dict:
        """处理初始化检测请求"""
        info = {"status": "ok"}
        if self._backend is not None:
            info["backend_type"] = self._backend.__class__.__name__
            if hasattr(self._backend, "health"):
                info["healthy"] = self._backend.health()
        else:
            info["backend_type"] = "not_initialized"
            info["healthy"] = False
        return {"_port": "status", **info}


# ════════════════════════════════════════════════════════════════
#  框架桥接（开发者不要修改）
# ════════════════════════════════════════════════════════════════

_node = MyNode()


def process(data: dict) -> dict:
    """框架入口，由 listener.py 或 __main__ 调用。"""
    return _node.process(data)


# ════════════════════════════════════════════════════════════════
#  __main__ 入口（仅直接运行 python main.py 时执行）
# ════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    input_data = {}
    if len(sys.argv) >= 2:
        try:
            input_data = json.loads(sys.argv[1])
        except Exception:
            pass
    if not input_data:
        try:
            s = sys.stdin.read().strip()
            if s:
                input_data = json.loads(s)
        except Exception:
            pass
    if not input_data:
        print(json.dumps({"code": -1, "error": "no input"}, ensure_ascii=False))
        sys.exit(1)

    result = process(input_data)
    cfg = load_config()

    if isinstance(result, list):
        print(json.dumps({"code": 0, "data": result}, ensure_ascii=False))
    else:
        port = result.pop("_port", cfg.get("output_type", "default"))
        print(json.dumps({"code": 0, "type": port, "data": result}, ensure_ascii=False))
