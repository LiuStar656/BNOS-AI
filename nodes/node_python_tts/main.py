"""
node_python_tts — TTS 语音合成节点

单进程架构（无 listener）：
- 主线程：HTTP 服务 (:8084)，供前端 fetch 音频
- 后台线程：轮询 AAA 的 output_reply.json，检测到新回复即合成并播放

引擎直接 Popen main.py 即可，参数从 node_config.json 读取。
"""
from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import re
import signal
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# ─── 路径 ───────────────────────────────────────────
NODE_DIR = Path(__file__).resolve().parent
CACHE_DIR = NODE_DIR / "tts_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
MAX_CACHED_FILES = 10

# ─── PID 文件（无 listener，被引擎直接拉起时需要 PID） ───
PID_FILE = NODE_DIR / f"{NODE_DIR.name}.pid"


def _cleanup_pid():
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except OSError:
        pass


atexit.register(_cleanup_pid)

# ─── 引擎注册 ───────────────────────────────────────
sys.path.insert(0, str(NODE_DIR))
from tts_engines import create_engine, list_engines, BaseTTSEngine


def load_node_params() -> dict:
    """从 node_config.json 读取参数"""
    cfg_path = NODE_DIR / "node_config.json"
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return {p["name"]: p.get("default") for p in cfg.get("parameters", [])}
    except Exception:
        return {}


# ─── 参数 ──────────────────────────────────────────
PARAMS = load_node_params()
PORT = int(PARAMS.get("port", 8084))
INPUT_FILE = str((NODE_DIR / PARAMS.get("input_file", "../node_python_aaa_cognition/output_reply.json")).resolve())
ENGINE_NAME = PARAMS.get("engine", "edge_tts")
VOICE = PARAMS.get("voice", "zh-CN-XiaoxiaoNeural")

# ─── 状态 ──────────────────────────────────────────
_last_req_id: str = ""  # 去重：已处理的 request_id


def extract_emotion(text: str) -> str:
    """从文本中提取情绪标签：`<开心>你好` → `开心`"""
    m = re.match(r"^<([\u4e00-\u9fff]{2,4})>", text)
    return m.group(1) if m else ""


def extract_clean_text(text: str) -> str:
    """去掉情绪标签返回纯文本"""
    return re.sub(r"^<[\u4e00-\u9fff]{2,4}>", "", text).strip()


# ─── HTTP Server ────────────────────────────────────

class TTSHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器，与旧 tts_server.py 保持兼容"""

    engine: BaseTTSEngine | None = None
    voice: str = VOICE
    rate: str = "+0%"
    pitch: str = "+0Hz"

    def log_message(self, format, *args):
        print(f"[TTS] {args[0]}")

    def _json_response(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs_dict = parse_qs(parsed.query)

        if path == "/":
            self._json_response(200, self._status_data())
        elif path == "/health":
            self._json_response(200, self._status_data())
        elif path == "/engines":
            self._json_response(200, self._list_engines())
        elif path == "/tts":
            text = qs_dict.get("text", [""])[0].strip()
            if not text:
                self._json_response(400, {"error": "text required"})
                return
            engine = qs_dict.get("engine", [None])[0]
            self._serve_audio(text, engine)
        elif path.startswith("/audio/"):
            filename = path.rsplit("/", 1)[-1]
            filepath = CACHE_DIR / filename
            if filepath.exists():
                self.send_response(200)
                self.send_header("Content-Type", "audio/mpeg")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(filepath.read_bytes())
            else:
                self._json_response(404, {"error": "not found"})
        else:
            self._json_response(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/tts":
            self._json_response(404, {"error": "not found"})
            return
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8")
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            self._json_response(400, {"error": "invalid JSON"})
            return
        text = req.get("text", "").strip()
        engine = req.get("engine")
        self._serve_audio(text, engine)

    def _status_data(self) -> dict:
        info = {}
        if self.engine:
            info = {
                "name": self.engine.meta.name,
                "display": self.engine.meta.display_name,
                "category": self.engine.meta.category,
            }
        return {"status": "ok", "engine": info, "voice": self.voice}

    def _list_engines(self) -> dict:
        result = {}
        for name, display in list_engines().items():
            inst = create_engine(name, voice=self.voice)
            result[name] = {
                "display": display,
                "available": inst.check_available() if inst else False,
            }
        return {"engines": result, "current": ENGINE_NAME}

    def _serve_audio(self, text: str, req_engine: str | None = None):
        if not text.strip():
            self._json_response(400, {"error": "text is empty"})
            return
        engine = self.engine
        if req_engine and req_engine != ENGINE_NAME:
            alt = create_engine(req_engine, voice=self.voice)
            if alt and alt.check_available():
                engine = alt
            else:
                self._json_response(400, {"error": f"engine '{req_engine}' unavailable"})
                return
        if engine is None:
            self._json_response(500, {"error": "no engine configured"})
            return

        cache_key = hashlib.md5(f"{engine.meta.name}:{self.voice}:{text}".encode("utf-8")).hexdigest()
        cached = CACHE_DIR / f"{cache_key}.{engine.extension}"

        if cached.exists():
            audio_data = cached.read_bytes()
        else:
            try:
                audio_data = engine.synthesize(text, voice=self.voice, rate=self.rate, pitch=self.pitch)
                if audio_data:
                    cached.write_bytes(audio_data)
                    _cleanup_cache()
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._json_response(500, {"error": str(e)})
                return

        if not audio_data:
            self._json_response(500, {"error": "empty audio"})
            return

        self.send_response(200)
        self.send_header("Content-Type", engine.content_type)
        self.send_header("Content-Length", str(len(audio_data)))
        self.send_header("Cache-Control", "max-age=86400")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(audio_data)


def _cleanup_cache():
    """清理缓存，只保留最新的 MAX_CACHED_FILES 个文件"""
    try:
        files = sorted(CACHE_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files[MAX_CACHED_FILES:]:
            f.unlink()
    except OSError:
        pass


# ─── 文件轮询 ──────────────────────────────────────

def _write_speaking(v: bool):
    """写 speaking.json，供 Live2D 渲染器获取说话状态驱动口型同步"""
    try:
        p = Path(__file__).resolve().parent.parent / "shared" / "speaking.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"speaking": v}), "utf-8")
    except OSError:
        pass


def _tts_enabled() -> bool:
    """读 GUI 语音开关共享 flag（nodes/shared/tts_enabled.json）。

    GUI「语音：开/关」按钮写入；文件缺失或非法默认开启（兼容节点独立运行）。
    """
    try:
        p = Path(__file__).resolve().parent.parent / "shared" / "tts_enabled.json"
        if p.is_file():
            return bool(json.loads(p.read_text("utf-8")).get("tts_enabled", True))
    except (OSError, json.JSONDecodeError, AttributeError):
        pass
    return True


def _play_audio(audio_data: bytes):
    """播放音频（尝试 pygame.mixer，失败则静默跳过）"""
    def _play():
        _write_speaking(True)
        try:
            import pygame
            if not pygame.get_init():
                pygame.mixer.init()
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.write(audio_data)
            tmp.close()
            pygame.mixer.music.load(tmp.name)
            pygame.mixer.music.play()
            # 等待播放完成
            while pygame.mixer.music.get_busy():
                pygame.time.wait(100)
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
        except Exception:
            pass  # 播放失败不阻塞
        finally:
            _write_speaking(False)
    threading.Thread(target=_play, daemon=True).start()


def _unwrap_reply(raw: dict) -> dict:
    """解包 {"code": 0, "data": {...}} 格式，提取内层 data"""
    if isinstance(raw, dict) and "code" in raw and "data" in raw:
        inner = raw["data"]
        if isinstance(inner, dict):
            return inner
    return raw


def _poll_input():
    """轮询 AAA 的 output_reply.json，检测新回复"""
    global _last_req_id
    path = Path(INPUT_FILE)

    # 初始化：记录当前文件 mtime 和 request_id，避免刚启动时重播旧内容
    last_mtime = path.stat().st_mtime if path.exists() else 0.0
    if path.exists() and last_mtime > 0:
        try:
            raw = path.read_text("utf-8").strip()
            if raw:
                data = _unwrap_reply(json.loads(raw))
                _last_req_id = data.get("request_id", "") or data.get("_port", "")
        except Exception:
            pass

    while True:
        try:
            if path.exists():
                mtime = path.stat().st_mtime
                if mtime > last_mtime:
                    last_mtime = mtime
                    raw = path.read_text("utf-8").strip()
                    if not raw:
                        continue
                    raw_data = json.loads(raw)
                    data = _unwrap_reply(raw_data)
                    rid = data.get("request_id", "") or data.get("_port", "")
                    if rid and rid == _last_req_id:
                        continue  # 去重
                    _last_req_id = rid

                    content = data.get("content", "")
                    if not content:
                        continue

                    # 提取情绪和纯文本
                    emotion = extract_emotion(content)
                    clean_text = extract_clean_text(content)
                    if not clean_text:
                        continue

                    print(f"[TTS] 新回复: {clean_text[:60]}...")
                    sys.stdout.flush()

                    # 语音开关（GUI「语音：开/关」共享 flag）：关闭则跳过合成播放，
                    # 文本仍由 Live2D 渲染器打字机显示（不受影响）。
                    if not _tts_enabled():
                        print("[TTS] 语音已关闭（GUI 开关），跳过播放")
                        sys.stdout.flush()
                        continue

                    # 合成并播放
                    engine = TTSHandler.engine
                    if engine is None:
                        continue
                    audio = engine.synthesize(clean_text, voice=VOICE)
                    if audio:
                        _play_audio(audio)
                        # 缓存
                        ck = hashlib.md5(f"{engine.meta.name}:{VOICE}:{clean_text}".encode()).hexdigest()
                        cache_file = CACHE_DIR / f"{ck}.{engine.extension}"
                        if not cache_file.exists():
                            cache_file.write_bytes(audio)
        except (json.JSONDecodeError, OSError):
            pass
        except Exception:
            pass
        time.sleep(0.5)


# ─── 主入口 ─────────────────────────────────────────

def main():
    # 写入 PID 文件（引擎通过 PID 文件管理进程生命周期）
    PID_FILE.write_text(str(os.getpid()))
    print(f"[TTS] PID: {os.getpid()} -> {PID_FILE}")

    # 注册信号处理器
    def _signal_handler(signum, frame):
        print(f"[TTS] Signal {signum} received, shutting down...")
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # 初始化引擎
    engine = create_engine(ENGINE_NAME, voice=VOICE)
    if engine is None:
        print(f"[TTS] 错误: 未知引擎 '{ENGINE_NAME}'", file=sys.stderr)
        print(f"[TTS] 可用: {', '.join(list_engines().keys())}", file=sys.stderr)
        sys.exit(1)
    if not engine.check_available():
        print(f"[TTS] 错误: 引擎 '{ENGINE_NAME}' 当前不可用", file=sys.stderr)
        sys.exit(1)

    TTSHandler.engine = engine
    TTSHandler.voice = VOICE

    # 启动文件轮询线程
    poller = threading.Thread(target=_poll_input, daemon=True)
    poller.start()

    # 启动 HTTP 服务
    server = HTTPServer(("127.0.0.1", PORT), TTSHandler)
    print(f"[TTS] 引擎: {engine.meta.display_name} ({engine.meta.category})")
    print(f"[TTS] 音色: {VOICE}")
    print(f"[TTS] HTTP 服务: http://127.0.0.1:{PORT}")
    print(f"[TTS] 输入文件: {INPUT_FILE}")
    print(f"[TTS] 可用引擎: {', '.join(list_engines().keys())}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("[TTS] 服务已关闭")


if __name__ == "__main__":
    main()
