"""
LLM 推理后端模块 - 本地 llama.cpp + 云端多供应商
"""
import os
import json
import time
import subprocess
import requests
import tempfile


# ════════════════════════════════════════════════════════════════
#  工具函数
# ════════════════════════════════════════════════════════════════

def find_cli_path(basename: str) -> str:
    """
    跨平台查找 llama.cpp 可执行文件。
    - Windows: 优先找 {basename}.exe
    - Linux/Mac: 优先找 {basename}（无后缀）

    候选目录：
      1. 节点目录下的 llama_cpp_bin/
      2. 节点目录本身
    """
    node_dir = os.path.dirname(os.path.abspath(__file__))
    if os.name == "nt":
        names = [basename + ".exe", basename]
    else:
        names = [basename, basename + ".exe"]
    candidates = [
        os.path.join(node_dir, "llama_cpp_bin", n) for n in names
    ] + [
        os.path.join(node_dir, n) for n in names
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    display = basename + (".exe" if os.name == "nt" else "")
    raise FileNotFoundError(f"未找到 {display}，请放在 llama_cpp_bin/ 目录下")


# ════════════════════════════════════════════════════════════════
#  云端供应商默认值
# ════════════════════════════════════════════════════════════════

def _check_response(resp):
    """增强错误报告：包含响应体"""
    if not resp.ok:
        try:
            body = resp.json()
            detail = json.dumps(body, ensure_ascii=False)
        except Exception:
            detail = resp.text[:500]
        raise requests.HTTPError(
            f"{resp.status_code} {resp.reason} | {detail}",
            response=resp,
        )


CLOUD_VENDOR_DEFAULTS = {
    "openai": {
        "api_base": "https://api.openai.com/v1",
        "model": "gpt-4o",
    },
    "anthropic": {
        "api_base": "https://api.anthropic.com",
        "model": "claude-3-5-sonnet-20241022",
    },
    "google": {
        "api_base": "https://generativelanguage.googleapis.com",
        "model": "gemini-2.0-flash",
    },
    "deepseek": {
        "api_base": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
    },
    "custom_openai": {
        "api_base": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
}


# ════════════════════════════════════════════════════════════════
#  后端一：llama-server HTTP 服务（本地，低延迟，模型常驻）
# ════════════════════════════════════════════════════════════════

class LlamaServerBackend:
    """llama.cpp HTTP Server 后端 - 模型常驻，低延迟"""

    def __init__(self, config: dict):
        self.model_path = config.get("model_path", "")
        self.port = int(config.get("llama_port", 8080))
        self.host = "127.0.0.1"
        self.api_base = f"http://{self.host}:{self.port}/v1"
        self.server_process = None

    def start(self) -> bool:
        """启动 llama-server 子进程并等待就绪。

        幂等设计：如果 server 已在运行（/health 响应 200），直接返回 True。
        """
        if self.health():
            return True

        if not self.model_path or not os.path.isfile(self.model_path):
            return False
        try:
            cli_path = find_cli_path("llama-server")
        except FileNotFoundError:
            return False

        cmd = [
            cli_path, "-m", self.model_path,
            "--host", self.host, "--port", str(self.port),
            "-c", "4096", "-ngl", "99", "--no-webui",
        ]
        self.server_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        for _ in range(60):
            try:
                r = requests.get(f"http://{self.host}:{self.port}/health", timeout=2)
                if r.ok:
                    return True
            except requests.RequestException:
                pass
            time.sleep(1)
        return False

    def infer(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.7) -> str:
        """调用 OpenAI 兼容 API 推理"""
        resp = requests.post(
            f"{self.api_base}/chat/completions",
            json={
                "model": "local",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            },
            timeout=300,
        )
        _check_response(resp)
        return resp.json()["choices"][0]["message"]["content"]

    def health(self) -> bool:
        """检查服务是否存活"""
        try:
            r = requests.get(f"http://{self.host}:{self.port}/health", timeout=2)
            return r.ok
        except requests.RequestException:
            return False

    def stop(self):
        """停止 server 进程"""
        if self.server_process:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            self.server_process = None


# ════════════════════════════════════════════════════════════════
#  后端二：llama-cli CLI 子进程（本地，零配置，每次加载模型）
# ════════════════════════════════════════════════════════════════

class LlamaCliBackend:
    """llama.cpp CLI 后端 - 零配置，每次调用加载模型"""

    def __init__(self, config: dict):
        self.model_path = config.get("model_path", "")

    def infer(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.7) -> str:
        cli_path = find_cli_path("llama-cli")

        fd, prompt_file = tempfile.mkstemp(suffix=".txt", text=True)
        try:
            os.write(fd, prompt.encode("utf-8"))
            os.close(fd)

            cmd = [
                cli_path, "-m", self.model_path,
                "-f", prompt_file,
                "-n", str(max_tokens),
                "--temp", str(temperature),
                "--top-p", "0.9",
                "--no-display-prompt",
                "-no-cnv",
            ]
            result = subprocess.run(
                cmd, capture_output=True, timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

            raw = result.stdout or b""
            try:
                output = raw.decode("utf-8", errors="replace")
            except Exception:
                output = raw.decode("gbk", errors="replace")

            debug_prefixes = (
                "load_backend:", "build:", "main:", "llama_model_loader:",
                "load:", "load_tensors:", "llama_context:", "llama_kv_cache:",
                "common_init_from_params:", "system_info:", "sampler:",
                "generate:", "llama_perf_", "=== Running", "Press Ctrl+C",
                "Press Return", "error:", "usage:",
            )
            lines = []
            for line in output.split("\n"):
                stripped = line.strip()
                if stripped and not stripped.startswith(debug_prefixes):
                    lines.append(stripped)
            return "\n".join(lines).strip()

        except subprocess.TimeoutExpired:
            raise TimeoutError("llama-cli 调用超时（300s）")
        finally:
            try:
                os.unlink(prompt_file)
            except OSError:
                pass


# ════════════════════════════════════════════════════════════════
#  后端三：云端 API（多供应商）
# ════════════════════════════════════════════════════════════════

class CloudApiBackend:
    """
    云端 API 后端 - 多供应商适配。

    支持供应商（cloud_vendor）：
      - openai       : OpenAI / Azure OpenAI（标准 /v1/chat/completions）
      - anthropic    : Anthropic Claude（/v1/messages）
      - google       : Google Gemini（/v1/models/{model}:generateContent）
      - deepseek     : DeepSeek（标准 /v1/chat/completions，格式同 openai）
      - custom_openai: 任意 OpenAI 兼容 API（格式同 openai）
    """

    def __init__(self, config: dict):
        self.vendor = config.get("cloud_vendor", "openai")
        defaults = CLOUD_VENDOR_DEFAULTS.get(self.vendor, CLOUD_VENDOR_DEFAULTS["openai"])
        self.api_key = config.get("api_key", "")
        self.api_base = (config.get("api_base") or "").strip() or defaults["api_base"]
        self.cloud_model = (config.get("cloud_model") or "").strip() or defaults["model"]

    # ── OpenAI / 自定义兼容 ──────────────────────────────────

    def _infer_openai(self, prompt: str, max_tokens: int, temperature: float) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = requests.post(
            f"{self.api_base}/chat/completions",
            headers=headers,
            json={
                "model": self.cloud_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            },
            timeout=120,
        )
        _check_response(resp)
        return resp.json()["choices"][0]["message"]["content"]

    # ── Anthropic Claude ─────────────────────────────────────

    def _infer_anthropic(self, prompt: str, max_tokens: int, temperature: float) -> str:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        resp = requests.post(
            f"{self.api_base}/v1/messages",
            headers=headers,
            json={
                "model": self.cloud_model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=120,
        )
        _check_response(resp)
        body = resp.json()
        return "".join(
            block["text"]
            for block in body.get("content", [])
            if block.get("type") == "text"
        )

    # ── Google Gemini ───────────────────────────────────────

    def _infer_google(self, prompt: str, max_tokens: int, temperature: float) -> str:
        url = f"{self.api_base}/v1/models/{self.cloud_model}:generateContent"
        params = {}
        if self.api_key:
            params["key"] = self.api_key
        resp = requests.post(
            url, params=params,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": temperature,
                },
            },
            timeout=120,
        )
        _check_response(resp)
        body = resp.json()
        candidates = body.get("candidates", [])
        if not candidates:
            return ""
        return "".join(
            part.get("text", "")
            for part in candidates[0].get("content", {}).get("parts", [])
        )

    # ── 统一入口 ─────────────────────────────────────────────

    def infer(self, prompt: str, max_tokens: int = 2048, temperature: float = 0.7) -> str:
        if self.vendor == "anthropic":
            return self._infer_anthropic(prompt, max_tokens, temperature)
        elif self.vendor == "google":
            return self._infer_google(prompt, max_tokens, temperature)
        else:
            return self._infer_openai(prompt, max_tokens, temperature)


# ════════════════════════════════════════════════════════════════
#  后端工厂
# ════════════════════════════════════════════════════════════════

def create_backend(model_type: str, params: dict):
    """根据 model_type 创建并启动对应后端"""
    if model_type == "http_server":
        backend = LlamaServerBackend(params)
        if not backend.start():
            raise RuntimeError("llama-server 启动失败，请检查模型路径和端口")
        return backend
    elif model_type == "cli_local":
        return LlamaCliBackend(params)
    elif model_type == "cloud":
        return CloudApiBackend(params)
    else:
        raise ValueError(f"未知后端类型: {model_type}")
