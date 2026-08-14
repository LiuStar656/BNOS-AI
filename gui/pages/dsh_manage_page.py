"""DSH 管理页 — DSH 的设置/修改/控制组件搬到 BNOS GUI（原生表单，不进入 DSH）。

分区（QTabWidget）：
1. 模型配置 — provider baseURL / 默认模型 / 模型列表 / 最大 Token（headless + web 双 patch 同步）
2. 会话管理 — dsh_home/sessions 会话列表（继续/复制 id/导出/删除/清理）
3. 任务控制 — 提交任务（同步等待）、取消运行中任务、最近结果
4. 工具开关 — base/headless bundle 挂载工具清单 + 启用/禁用（extra.patch 覆盖行）
5. 插件 — dsh plugin add/remove 封装 + 已装插件组合清单
6. 工作区 — nodes/shared/dsh_workspace 文件浏览/新建/删除/重命名
7. 运行参数 — extra.patch.yml 附加 patch 编辑（YAML 校验）
8. 通用/安全 — 沙箱权限模式 + 会话遥测 + 默认温度（sandbox-policy / session-telemetry-otel / runtime.json）
9. Agent 预设 — 默认预设选择 + 复制创建自定义 Agent + 人格（dsh-persona 行）+ agent.cordis.yml/preset.yml 编辑 + 删除
    （默认预设存 runtime.json → node_dsh 注入 DSH_PRESET → headless roster 挂载）

人格归属：DSH 官方语义是「人格属于预设」——每个预设的 agent.cordis.yml 可挂
`id: persona`（@deepseek-ai/dsh-persona）行，为该 agent 提供人格；无该行则继承
部署默认（bundle 的 system-prompt persona）。因此人格编辑入口在「Agent 预设」分区，
不再有独立的全局「目标/人格」标签页（原 system-prompt.persona 全局注入入口已移除，
残留的 system-prompt 行在首次打开本页时被迁移清理）。

原则：所有耗时可阻塞 GUI 的操作（任务等待 / 插件命令 / 进程清理）放子线程，
结果经 Qt Signal 回主线程；避免界面冻结。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import yaml

from gui.core.utils.widget_utils import fit_button_width

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.core.theme_engine import theme_engine

_NODE_DIR = Path(__file__).resolve().parent.parent.parent / "nodes" / "node_dsh"
_DSH_HOME = _NODE_DIR / "dsh_home"
_SESSIONS_DIR = _DSH_HOME / "sessions"
_PROFILES = {
    "headless": _DSH_HOME / "profiles" / "headless" / "cordis.patch.yml",
    "web": _DSH_HOME / "profiles" / "web" / "cordis.patch.yml",
}
_EXTRA_PATCH = _DSH_HOME / "profiles" / "headless" / "extra.patch.yml"
_LLM_CFG = _NODE_DIR.parent / "node_python_llm_infer" / "node_config.json"
_OUTPUT_JSON = _NODE_DIR / "output.json"
_HARNESS = _NODE_DIR / "harness"

_PROVIDER_ID = "bnos-deepseek"


def _style(color: str, size: int = 12, bold: bool = False) -> str:
    weight = "font-weight: bold;" if bold else ""
    return f"font-size: {size}px; {weight}color: {color};"


def _sec_color() -> str:
    return theme_engine.get("text_secondary")


def _primary_color() -> str:
    return theme_engine.get("text_primary")


def _accent_color() -> str:
    return theme_engine.get("accent_color")


def _warn_color() -> str:
    return theme_engine.get("warn_color", theme_engine.get("text_secondary"))


# ════════════════════════════════════════════════════════════
#  共享数据读写（模型配置 + 附加 patch）
# ════════════════════════════════════════════════════════════

def _read_llm_key_configured() -> bool:
    try:
        cfg = json.loads(_LLM_CFG.read_text(encoding="utf-8"))
        for p in cfg.get("parameters", []):
            if p.get("name") == "api_key" and str(p.get("default", "")).strip():
                return True
    except (OSError, json.JSONDecodeError):
        pass
    return False


def _load_patch(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except (OSError, yaml.YAMLError):
        return []


def read_model_config() -> dict:
    out = {"base_url": "", "default_model": "", "models": [], "max_tokens": ""}
    for row in _load_patch(_PROFILES["headless"]):
        if row.get("id") == "llm-pi-ai":
            providers = (row.get("config") or {}).get("providers") or {}
            prov = providers.get(_PROVIDER_ID) or {}
            out["base_url"] = prov.get("baseURL", "")
            out["models"] = [m.get("id", "") for m in (prov.get("models") or []) if m.get("id")]
            out["max_tokens"] = str(prov.get("defaultMaxTokens", "")) if prov.get("defaultMaxTokens") else ""
        elif row.get("id") == "agent-default-model":
            out["default_model"] = (row.get("config") or {}).get("model", "")
    return out


def save_model_config(base_url: str, default_model: str, models: list[str], max_tokens: str = "") -> None:
    models = [m.strip() for m in models if m.strip()]
    if not models:
        raise ValueError("模型列表不能为空")
    if not base_url.strip():
        raise ValueError("Base URL 不能为空")
    if not default_model.strip():
        raise ValueError("默认模型不能为空")
    max_tokens_val = None
    if max_tokens.strip():
        try:
            max_tokens_val = int(max_tokens.strip())
            if max_tokens_val <= 0:
                raise ValueError
        except ValueError:
            raise ValueError("最大 Token 必须是正整数（留空则使用默认）")
    for path in _PROFILES.values():
        docs = _load_patch(path)
        found_provider = found_default = False
        for row in docs:
            if row.get("id") == "llm-pi-ai":
                cfg = row.setdefault("config", {})
                prov = cfg.setdefault("providers", {}).setdefault(_PROVIDER_ID, {})
                prov["baseURL"] = base_url.strip()
                prov["models"] = [{"id": m} for m in models]
                if max_tokens_val is None:
                    prov.pop("defaultMaxTokens", None)
                else:
                    prov["defaultMaxTokens"] = max_tokens_val
                found_provider = True
            elif row.get("id") == "agent-default-model":
                cfg = row.setdefault("config", {})
                cfg["provider"] = _PROVIDER_ID
                cfg["model"] = default_model.strip()
                found_default = True
        if not found_provider:
            new_prov = {
                "apiKeyEnv": "DEEPSEEK_API_KEY",
                "api": "openai-completions",
                "baseURL": base_url.strip(),
                "models": [{"id": m} for m in models],
            }
            if max_tokens_val is not None:
                new_prov["defaultMaxTokens"] = max_tokens_val
            docs.append({
                "id": "llm-pi-ai",
                "config": {"providers": {_PROVIDER_ID: new_prov}},
            })
        if not found_default:
            docs.append({"id": "agent-default-model", "config": {"provider": _PROVIDER_ID, "model": default_model.strip()}})
        body = yaml.safe_dump(docs, allow_unicode=True, sort_keys=False)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("# 由 BNOS GUI「DSH 管理-模型配置」统一维护（provider 配置）。\n" + body, encoding="utf-8")
        tmp.replace(path)


def _headless_pids() -> list[str]:
    """找出正在运行 DSH 任务的 node 进程 PID（命令行含 --profile headless）。"""
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='node.exe'", "get", "ProcessId,CommandLine"],
            capture_output=True, text=True, timeout=15,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    pids = []
    for ln in out.splitlines()[1:]:
        ln = ln.strip()
        if not ln:
            continue
        parts = ln.rsplit(None, 1)
        if len(parts) == 2 and "--profile headless" in parts[0] and parts[1].isdigit():
            pids.append(parts[1])
    return pids


def list_sessions() -> list[dict]:
    """扫描 dsh_home/sessions/<workspace-hash>/<session-id>/session.jsonl.zstd。"""
    sessions = []
    if not _SESSIONS_DIR.is_dir():
        return sessions
    for ws_dir in sorted(_SESSIONS_DIR.iterdir()):
        if not ws_dir.is_dir():
            continue
        for sess_dir in sorted(ws_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            blob = sess_dir / "session.jsonl.zstd"
            if not blob.is_file():
                continue
            st = blob.stat()
            sessions.append({
                "id": sess_dir.name,
                "workspace": ws_dir.name,
                "mtime": st.st_mtime,
                "size": st.st_size,
            })
    sessions.sort(key=lambda s: s["mtime"], reverse=True)
    return sessions


def read_recent_result() -> dict:
    if not _OUTPUT_JSON.is_file():
        return {}
    try:
        data = json.loads(_OUTPUT_JSON.read_text(encoding="utf-8"))
        inner = data.get("data", data) if isinstance(data, dict) else data
        return inner if isinstance(inner, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


# ════════════════════════════════════════════════════════════
#  共享：extra.patch.yml（工具开关 / 运行参数共用）
# ════════════════════════════════════════════════════════════

_EXTRA_HEADER = "# 由 BNOS GUI「DSH 管理」维护（工具开关 / 运行参数共用），node_dsh 以 --patch 加载。\n"


def _load_extra_patch() -> list[dict]:
    return _load_patch(_EXTRA_PATCH)


def _save_extra_patch(rows: list[dict]) -> None:
    _EXTRA_PATCH.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(rows, allow_unicode=True, sort_keys=False) if rows else ""
    tmp = _EXTRA_PATCH.with_name(_EXTRA_PATCH.name + ".tmp")
    tmp.write_text(_EXTRA_HEADER + body, encoding="utf-8")
    tmp.replace(_EXTRA_PATCH)


_BUNDLE_BASE = _NODE_DIR / "harness" / "packages" / "bundle" / "base" / "cordis.patch.yml"
_BUNDLE_HEADLESS = _NODE_DIR / "harness" / "packages" / "bundle" / "headless" / "cordis.patch.yml"
_WORKSPACE = _NODE_DIR.parent / "shared" / "dsh_workspace"

# 工具清单按层合并：base bundle → headless bundle → profile patch → extra patch（后层覆盖前层）
_TOOL_LAYERS = (_BUNDLE_BASE, _BUNDLE_HEADLESS, _PROFILES["headless"], _EXTRA_PATCH)


def _scan_rows(text: str, id_prefix: str = "") -> list[dict]:
    """从 patch 文本提取行（id/name/disabled）。

    不完整解析 YAML（base bundle 含 !!js 表达式，safe_load 会失败），
    只按行提取所需的三个字段。
    """
    rows = []
    pattern = re.compile(rf"^(\s*)- id: ({id_prefix}[A-Za-z0-9_.\-/]+)\s*$")
    lines = text.splitlines()
    i, n = 0, len(lines)
    while i < n:
        m = pattern.match(lines[i])
        if m:
            rid = m.group(2)
            row = {"id": rid, "name": "", "disabled": None}
            j = i + 1
            while j < n and lines[j][:1] in (" ", "\t") and not re.match(r"^\s*- id:", lines[j]):
                nm = re.match(r"^\s+name:\s*['\"]?([^'\"]+)['\"]?\s*$", lines[j])
                if nm:
                    row["name"] = nm.group(1).strip()
                dm = re.match(r"^\s+disabled:\s*(.+?)\s*$", lines[j])
                if dm:
                    row["disabled"] = dm.group(1).strip()
                j += 1
            rows.append(row)
            i = j
        else:
            i += 1
    return rows


def _eval_disabled(value: str | None) -> bool | None:
    """把行里的 disabled 值归一为布尔（支持 !!js 平台表达式）。"""
    if value is None:
        return None
    s = value.strip()
    if s == "true":
        return True
    if s == "false":
        return False
    if "win32" in s:
        on_win32 = "===" in s
        return sys.platform == "win32" if on_win32 else sys.platform != "win32"
    return None


def list_tool_rows() -> list[dict]:
    """合并各层 patch 后的工具行（id/name/是否启用）。"""
    merged: dict[str, dict] = {}
    for path in _TOOL_LAYERS:
        if not path.is_file():
            continue
        for row in _scan_rows(path.read_text(encoding="utf-8"), "tool-"):
            entry = merged.setdefault(row["id"], {"id": row["id"], "name": row["name"], "disabled": None})
            if row["name"]:
                entry["name"] = row["name"]
            if row["disabled"] is not None:
                entry["disabled"] = row["disabled"]
    out = []
    for entry in merged.values():
        out.append({
            "id": entry["id"],
            "name": entry["name"],
            "enabled": _eval_disabled(entry["disabled"]) is not True,
        })
    return sorted(out, key=lambda t: t["id"])


def list_composed_rows() -> list[dict]:
    """合并各层 patch 的全部插件行（id/name/disabled），用于插件组合展示。"""
    seen: dict[str, dict] = {}
    for path in _TOOL_LAYERS:
        if not path.is_file():
            continue
        for row in _scan_rows(path.read_text(encoding="utf-8")):
            entry = seen.setdefault(row["id"], {"id": row["id"], "name": row["name"], "disabled": None})
            if row["name"]:
                entry["name"] = row["name"]
            if row["disabled"] is not None:
                entry["disabled"] = row["disabled"]
    out = []
    for entry in seen.values():
        disabled = _eval_disabled(entry["disabled"])
        out.append({
            "id": entry["id"],
            "name": entry["name"],
            "state": "已禁用" if disabled is True else "启用",
        })
    return sorted(out, key=lambda r: (r["state"] != "启用", r["id"]))


def _find_session_dir(session_id: str) -> Path | None:
    if not _SESSIONS_DIR.is_dir():
        return None
    for ws_dir in _SESSIONS_DIR.iterdir():
        target = ws_dir / session_id
        if target.is_dir():
            return target
    return None


# ════════════════════════════════════════════════════════════
#  共享：通用/安全（沙箱权限 / 会话遥测 / 默认温度）
# ════════════════════════════════════════════════════════════

_RUNTIME_JSON = _DSH_HOME / "runtime.json"

# 沙箱权限模式（sandbox-policy.mode，等价 DSH_PERMISSION_MODE）
SANDBOX_MODES = (
    ("read-only", "只读", "Agent 只能读取文件，不能写入/修改任何文件"),
    ("workspace-write", "工作区可写", "Agent 只能读写 dsh_workspace 工作区（当前默认，推荐日常使用）"),
    ("danger-full-access", "全部权限", "Agent 可读写机器上任何文件并执行任意命令（危险，仅可信环境）"),
)

# 会话遥测（session-telemetry-otel.mode；base 层默认 DISABLED）
TELEMETRY_MODES = (
    ("DISABLED", "仅本地", "会话日志只保存在本机，不上传（当前默认）"),
    ("FEEDBACK_ONLY", "仅反馈", "只上报匿名反馈（仍会外传部分数据到 DeepSeek 遥测端点）"),
    ("FULL", "完整共享", "完整上报会话日志到 DeepSeek 遥测端点（含对话内容，谨慎选择）"),
)
_TELEMETRY_EXPORTER = {
    "url": "https://harness-telemetry.deepseeksvc.com/v1/logs",
    "compression": "gzip",
    "timeoutMillis": 1000,
}
_TELEMETRY_PROCESSOR = {
    "scheduledDelayMillis": 10000,
    "maxQueueSize": 2048,
    "maxExportBatchSize": 2048,
    "exportTimeoutMillis": 1500,
}


def read_runtime_params() -> dict:
    """读 dsh_home/runtime.json（默认温度等运行时参数）。"""
    if not _RUNTIME_JSON.is_file():
        return {}
    try:
        data = json.loads(_RUNTIME_JSON.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_runtime_params(temperature: float | None) -> None:
    """写 dsh_home/runtime.json；temperature 为 None 时不写入该字段（留空文件也可）。"""
    data = read_runtime_params()
    if temperature is None:
        data.pop("temperature", None)
    else:
        data["temperature"] = float(temperature)
    _RUNTIME_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = _RUNTIME_JSON.with_name(_RUNTIME_JSON.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_RUNTIME_JSON)


def _extra_row_config(row_id: str) -> dict | None:
    """从 extra.patch 找指定行的 config（无则 None）。"""
    for row in _load_extra_patch():
        if row.get("id") == row_id:
            cfg = row.get("config")
            return cfg if isinstance(cfg, dict) else {}
    return None


def read_sandbox_mode() -> str:
    """当前沙箱权限模式；extra.patch 未覆盖时为 base 默认 workspace-write。"""
    cfg = _extra_row_config("sandbox-policy")
    mode = (cfg or {}).get("mode", "workspace-write")
    return mode if mode in {m[0] for m in SANDBOX_MODES} else "workspace-write"


def save_sandbox_mode(mode: str) -> None:
    """写 extra.patch 的 sandbox-policy.config.mode（整体替换 config，workspaceRoot 回落 base）。"""
    rows = [r for r in _load_extra_patch() if r.get("id") != "sandbox-policy"]
    rows.append({"id": "sandbox-policy", "config": {"mode": mode}})
    _save_extra_patch(rows)


def read_telemetry_mode() -> str:
    """当前会话遥测模式；extra.patch 未覆盖时为 base 默认 DISABLED。"""
    cfg = _extra_row_config("session-telemetry-otel")
    mode = (cfg or {}).get("mode", "DISABLED")
    return mode if mode in {m[0] for m in TELEMETRY_MODES} else "DISABLED"


def save_telemetry_mode(mode: str) -> None:
    """写 extra.patch 的 session-telemetry-otel.config.mode。

    patch 是整体替换 config，因此非 DISABLED 时必须带完整 exporter/processor，
    否则 OTLP 校验（url 必填）会失败。
    """
    cfg = {"mode": mode}
    if mode != "DISABLED":
        cfg.update({
            "shutdownTimeoutMillis": 3000,
            "exporter": dict(_TELEMETRY_EXPORTER),
            "processor": dict(_TELEMETRY_PROCESSOR),
        })
    rows = [r for r in _load_extra_patch() if r.get("id") != "session-telemetry-otel"]
    rows.append({"id": "session-telemetry-otel", "config": cfg})
    _save_extra_patch(rows)


# ════════════════════════════════════════════════════════════
#  共享：Agent 预设（roster）读写
# ════════════════════════════════════════════════════════════

# 预设根目录：内置（安装目录，只读，system trust）+ 自定义（dsh_home/.agent-presets，
# 可写，user trust）。自定义目录由 headless 的 agent-presets 插件自动追加到 roster。
_SHIPPED_PRESETS = _NODE_DIR / "harness" / "apps" / "cli" / "config" / "agent-presets"
_USER_PRESETS = _DSH_HOME / ".agent-presets"
# 预设 id = 目录名，须匹配 DSH 的 PRESET_ID 正则 ^[a-z0-9][a-z0-9-]*$
_PRESET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PRESET_FILES = ("agent.cordis.yml", "preset.yml")


def _validate_preset_composition(text: str) -> str | None:
    """校验 agent.cordis.yml 是否为合法插件行列表；返回错误信息，None 表示合法。

    支持 !!js 标签（安全装载为字符串）——shipped 预设用 !!js process.platform 表达式。
    """

    class _JsSafeLoader(yaml.SafeLoader):
        pass

    _JsSafeLoader.add_constructor(
        "tag:yaml.org,2002:js", lambda loader, node: loader.construct_scalar(node)
    )
    try:
        doc = yaml.load(text, Loader=_JsSafeLoader)
    except yaml.YAMLError as exc:
        return f"YAML 解析失败：{exc}"
    return _entry_list_problem(doc)


def _entry_list_problem(rows, at: str = "") -> str | None:
    """浅层结构检查（镜像 DSH discovery 的 entryListProblem）：顶层/组内必须是插件行列表。"""
    if not isinstance(rows, list):
        return "组合必须是顶层插件行列表" if not at else f"组 {at} 必须是插件行列表"
    for i, row in enumerate(rows):
        label = f"第 {i + 1} 行" if not at else f"{at} 第 {i + 1} 行"
        if not isinstance(row, dict):
            return f"{label} 不是插件行（需要带 name 的映射）"
        name = row.get("name")
        if not isinstance(name, str) or name == "":
            return f"{label} 缺少 name（插件名必填）"
        if row.get("group") is True:
            inner = _entry_list_problem(row.get("config"), label)
            if inner is not None:
                return inner
    return None


def _scan_preset_root(root: Path, trust: str) -> list[dict]:
    """扫描一个预设根目录，返回预设卡片数据（id/信任/元数据/是否损坏）。"""
    if not root.is_dir():
        return []
    out = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or not _PRESET_ID_RE.match(child.name):
            continue
        broken = ""
        comp = child / "agent.cordis.yml"
        if not comp.is_file():
            broken = "缺少 agent.cordis.yml（目录仍占用该 id，可删除或恢复）"
        else:
            problem = _validate_preset_composition(comp.read_text(encoding="utf-8"))
            if problem:
                broken = f"组合文件不可用：{problem}"
        name, description = "", ""
        meta_file = child / "preset.yml"
        if meta_file.is_file():
            try:
                meta = yaml.safe_load(meta_file.read_text(encoding="utf-8")) or {}
                if isinstance(meta, dict):
                    name = str(meta.get("name", "")).strip()
                    description = str(meta.get("description", "")).strip()
            except (OSError, yaml.YAMLError):
                pass
        out.append({
            "id": child.name,
            "trust": trust,
            "name": name,
            "description": description,
            "broken": broken,
            "dir": str(child),
        })
    return out


def list_presets() -> list[dict]:
    """全部预设：内置在前、自定义在后，同名 id 内置优先（与 DSH discoverPresets 一致）。"""
    by_id: dict[str, dict] = {}
    for root, trust in ((_SHIPPED_PRESETS, "system"), (_USER_PRESETS, "user")):
        for p in _scan_preset_root(root, trust):
            by_id.setdefault(p["id"], p)
    return [by_id[k] for k in sorted(by_id)]


def _find_preset(preset_id: str) -> dict | None:
    for p in list_presets():
        if p["id"] == preset_id:
            return p
    return None


def read_preset_default() -> str:
    """当前默认预设（runtime.json preset 字段）；空表示跟随 DSH 部署默认（standard）。"""
    v = read_runtime_params().get("preset")
    return str(v).strip() if isinstance(v, str) else ""


def save_preset_default(preset_id: str | None) -> None:
    """写 runtime.json preset 字段（None/空 = 跟随部署默认）；node_dsh 注入 DSH_PRESET。"""
    data = read_runtime_params()
    if preset_id:
        data["preset"] = preset_id
    else:
        data.pop("preset", None)
    _RUNTIME_JSON.parent.mkdir(parents=True, exist_ok=True)
    tmp = _RUNTIME_JSON.with_name(_RUNTIME_JSON.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_RUNTIME_JSON)


def create_custom_preset(source_id: str, new_id: str, name: str = "") -> str:
    """复制一个已有预设为自定义 Agent（写入 dsh_home/.agent-presets/<new_id>/）。

    与 DSH 的 copy() 语义一致：整体复制目录，preset.yml 重写为 name + 源描述。
    """
    if not _PRESET_ID_RE.match(new_id):
        raise ValueError(f"预设 id 需匹配 ^[a-z0-9][a-z0-9-]*$（当前：{new_id!r}）")
    source = _find_preset(source_id)
    if source is None:
        raise ValueError(f"源预设不存在：{source_id}")
    target = _USER_PRESETS / new_id
    if target.exists():
        raise ValueError(f"预设 id 已存在：{new_id}（复制不会覆盖）")
    _USER_PRESETS.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(Path(source["dir"]), target)
    except OSError as exc:
        raise ValueError(f"复制失败：{exc}") from exc
    meta = {"name": name.strip() or new_id}
    if source["description"]:
        meta["description"] = source["description"]
    (target / "preset.yml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return new_id


def delete_custom_preset(preset_id: str) -> None:
    """删除自定义预设（仅 user 根；内置预设拒绝删除，删除默认预设时同步清空默认）。"""
    if not _PRESET_ID_RE.match(preset_id):
        raise ValueError(f"预设 id 不合法：{preset_id!r}")
    target = (_USER_PRESETS / preset_id).resolve()
    if not target.is_relative_to(_USER_PRESETS.resolve()) or not target.is_dir():
        raise ValueError(f"该预设不是自定义预设或不存在：{preset_id}")
    shutil.rmtree(target, ignore_errors=True)
    if read_preset_default() == preset_id:
        save_preset_default(None)


def _user_preset_dir(preset_id: str) -> Path:
    if not _PRESET_ID_RE.match(preset_id):
        raise ValueError(f"预设 id 不合法：{preset_id!r}")
    p = (_USER_PRESETS / preset_id).resolve()
    if not p.is_relative_to(_USER_PRESETS.resolve()):
        raise ValueError("预设目录越界")
    return p


def read_preset_file(preset_id: str, filename: str) -> str:
    if filename not in _PRESET_FILES:
        raise ValueError("仅支持编辑 agent.cordis.yml / preset.yml")
    p = _user_preset_dir(preset_id) / filename
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8")


def save_preset_file(preset_id: str, filename: str, content: str) -> None:
    """保存自定义预设文件；agent.cordis.yml 需通过组合校验，preset.yml 需为 YAML 映射。"""
    if filename not in _PRESET_FILES:
        raise ValueError("仅支持编辑 agent.cordis.yml / preset.yml")
    if filename == "agent.cordis.yml":
        problem = _validate_preset_composition(content)
        if problem:
            raise ValueError(problem)
    else:
        try:
            meta = yaml.safe_load(content) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"preset.yml 不是合法 YAML：{exc}") from exc
        if not isinstance(meta, dict):
            raise ValueError("preset.yml 必须是映射（name/description/order）")
    p = _user_preset_dir(preset_id) / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(p)


# ─── 预设人格（dsh-persona 行）───

# DSH 官方语义：人格属于预设。预设组合里 `id: persona`（@deepseek-ai/dsh-persona）
# 行为该 agent 提供人格，无该行则继承部署默认（bundle system-prompt persona）。
_PERSONA_PLUGIN = "@deepseek-ai/dsh-persona"
_JS_TAG = "tag:yaml.org,2002:js"


class _JsExpr(str):
    """带 !!js 标签的字符串（roundtrip 保留平台表达式，如 !!js process.platform === 'win32'）"""


class _PresetLoader(yaml.SafeLoader):
    pass


class _PresetDumper(yaml.SafeDumper):
    pass


_PresetLoader.add_constructor(_JS_TAG, lambda loader, node: _JsExpr(loader.construct_scalar(node)))
_PresetDumper.add_representer(_JsExpr, lambda dumper, value: dumper.represent_scalar(_JS_TAG, str(value)))


def _load_preset_doc(preset_id: str) -> tuple[list | None, str]:
    """读取预设组合为插件行列表；返回 (doc, error)。doc 为 None 时 error 有效。"""
    p = _find_preset(preset_id)
    if p is None:
        return None, f"预设不存在：{preset_id}"
    f = Path(p["dir"]) / "agent.cordis.yml"
    if not f.is_file():
        return None, "缺少 agent.cordis.yml"
    try:
        doc = yaml.load(f.read_text(encoding="utf-8"), Loader=_PresetLoader) or []
    except yaml.YAMLError as exc:
        return None, f"组合 YAML 解析失败：{exc}"
    if not isinstance(doc, list):
        return None, "组合必须是插件行列表"
    return doc, ""


def read_preset_persona(preset_id: str) -> str:
    """读取预设的人格文本（agent.cordis.yml 的 `id: persona` 行 config.text；无则空）。"""
    doc, _ = _load_preset_doc(preset_id)
    if not isinstance(doc, list):
        return ""
    for row in doc:
        if isinstance(row, dict) and row.get("id") == "persona":
            cfg = row.get("config")
            if isinstance(cfg, dict) and isinstance(cfg.get("text"), str):
                return cfg["text"]
    return ""


def write_preset_persona(preset_id: str, text: str) -> None:
    """写入预设人格（仅自定义）：upsert `id: persona` 行；空文本 = 移除该行（继承部署默认）。

    !!js 平台表达式经 _JsExpr/_PresetDumper 原样保留，不影响组合其他行。
    """
    dirp = _user_preset_dir(preset_id)
    comp = dirp / "agent.cordis.yml"
    content = comp.read_text(encoding="utf-8") if comp.is_file() else ""
    doc = yaml.load(content, Loader=_PresetLoader) or []
    if not isinstance(doc, list):
        raise ValueError("组合不是插件行列表，无法写入人格")
    persona = text.strip()
    doc = [r for r in doc if not (isinstance(r, dict) and r.get("id") == "persona")]
    if persona:
        doc.insert(0, {"id": "persona", "name": _PERSONA_PLUGIN, "config": {"text": persona}})
    problem = _entry_list_problem(doc)
    if problem:
        raise ValueError(problem)
    dirp.mkdir(parents=True, exist_ok=True)
    tmp = comp.with_name(comp.name + ".tmp")
    tmp.write_text(yaml.dump(doc, Dumper=_PresetDumper, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(comp)


def _migrate_drop_global_persona() -> None:
    """迁移：移除 extra.patch.yml 中残留的全局 system-prompt 行（原「目标/人格」Tab 写入）。

    人格已归预设（dsh-persona 行），全局注入入口已删除；残留行会静默覆盖所有任务的人格，
    与「人格属预设」语义冲突，故首次打开本页时清理。幂等。
    """
    rows = _load_extra_patch()
    kept = [r for r in rows if r.get("id") != "system-prompt"]
    if len(kept) != len(rows):
        try:
            _save_extra_patch(kept)
        except OSError:
            pass


# ════════════════════════════════════════════════════════════
#  Tab 1：模型配置
# ════════════════════════════════════════════════════════════

class ModelConfigTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        hint = QLabel(
            "管理 DeepSeek Harness 的模型提供方与默认模型，保存后同步写入 headless（任务）与 web 两份 profile，"
            "下次任务生效。「最大 Token」为请求级默认上限（provider defaultMaxTokens）。"
            "API Key 不在此维护：复用 llm_infer 节点配置（或环境变量 DEEPSEEK_API_KEY），不落盘。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(_style(_sec_color()))
        layout.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)
        self._base_url_edit = QLineEdit()
        form.addRow("Base URL", self._base_url_edit)
        self._model_edit = QLineEdit()
        form.addRow("默认模型", self._model_edit)
        self._models_edit = QPlainTextEdit()
        self._models_edit.setFixedHeight(88)
        self._models_edit.setPlaceholderText("每行一个模型 id，如：deepseek-v4-flash")
        form.addRow("模型列表", self._models_edit)
        self._max_tokens_edit = QLineEdit()
        self._max_tokens_edit.setPlaceholderText("留空使用模型默认（如 4096 / 32768）")
        form.addRow("最大 Token", self._max_tokens_edit)
        key_ok = _read_llm_key_configured()
        key_label = QLabel("已配置（llm_infer 节点）" if key_ok else "未配置（将回退到环境变量 DEEPSEEK_API_KEY）")
        key_label.setStyleSheet(_style(_accent_color() if key_ok else _warn_color()))
        form.addRow("API Key", key_label)
        layout.addLayout(form)

        row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save)
        row.addStretch()
        row.addWidget(save_btn)
        layout.addLayout(row)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        layout.addStretch()
        self._load()

    def _load(self):
        cfg = read_model_config()
        self._base_url_edit.setText(cfg["base_url"])
        self._model_edit.setText(cfg["default_model"])
        self._models_edit.setPlainText("\n".join(cfg["models"]))
        self._max_tokens_edit.setText(cfg["max_tokens"])

    def _save(self):
        try:
            save_model_config(
                base_url=self._base_url_edit.text(),
                default_model=self._model_edit.text(),
                models=self._models_edit.toPlainText().splitlines(),
                max_tokens=self._max_tokens_edit.text(),
            )
        except ValueError as exc:
            self._status.setText(f"保存失败：{exc}")
            self._status.setStyleSheet(_style(_warn_color()))
            return
        self._status.setText("已保存（headless + web 两份 profile 已同步更新）")
        self._status.setStyleSheet(_style(_accent_color()))


# ════════════════════════════════════════════════════════════
#  Tab 2：会话管理
# ════════════════════════════════════════════════════════════

class SessionsTab(QWidget):
    def __init__(self, on_resume=None):
        super().__init__()
        self._on_resume = on_resume
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "DSH 会话持久化在 dsh_home/sessions 下（每个会话 = 一段连续上下文，可续接多轮对话）。"
            "「继续」会把会话 id 填入任务控制页的会话框。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(_style(_sec_color()))
        layout.addWidget(hint)

        row = QHBoxLayout()
        self._count_label = QLabel("")
        self._count_label.setStyleSheet(_style(_sec_color()))
        row.addWidget(self._count_label)
        row.addStretch()
        for text, handler in (("刷新", self._refresh), ("清理全部", self._clear_all)):
            btn = QPushButton(text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(handler)
            row.addWidget(btn)
        layout.addLayout(row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._container = QWidget()
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, 1)
        self._refresh()

    def _refresh(self):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        sessions = list_sessions()
        self._count_label.setText(f"共 {len(sessions)} 个会话")
        if not sessions:
            empty = QLabel("暂无会话。通过任务控制提交一次任务后会自动生成。")
            empty.setStyleSheet(_style(_sec_color()))
            empty.setAlignment(Qt.AlignCenter)
            self._list_layout.insertWidget(0, empty)
            return
        for s in sessions:
            self._list_layout.insertWidget(self._list_layout.count() - 1, self._make_row(s))

    def _make_row(self, s: dict) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background: {theme_engine.get('bg_secondary')}; border-radius: 6px;"
            f"border: 1px solid {theme_engine.get('border_color')};"
        )
        lay = QHBoxLayout(card)
        lay.setContentsMargins(10, 6, 10, 6)
        info = QVBoxLayout()
        id_label = QLabel(s["id"])
        id_label.setStyleSheet(_style(_primary_color(), 13, True))
        meta = QLabel(
            f"{time.strftime('%m-%d %H:%M', time.localtime(s['mtime']))}  ·  {s['size'] // 1024} KB"
        )
        meta.setStyleSheet(_style(_sec_color(), 11))
        info.addWidget(id_label)
        info.addWidget(meta)
        lay.addLayout(info, 1)
        for text, handler in (
            ("继续", lambda _, sid=s["id"]: self._resume(sid)),
            ("复制", lambda _, sid=s["id"]: self._copy(sid)),
            ("导出", lambda _, sid=s["id"]: self._export(sid)),
            ("删除", lambda _, sid=s["id"]: self._delete(sid)),
        ):
            btn = QPushButton(text)
            fit_button_width(btn)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(handler)
            lay.addWidget(btn)
        return card

    def _resume(self, session_id: str):
        if self._on_resume:
            self._on_resume(session_id)

    @staticmethod
    def _copy(session_id: str):
        QGuiApplication.clipboard().setText(session_id)

    def _export(self, session_id: str):
        src = _find_session_dir(session_id)
        if src is None:
            QMessageBox.warning(self, "导出会话", f"未找到会话目录：{session_id}")
            return
        default_name = f"dsh-session-{session_id[:12]}.zip"
        target, _ = QFileDialog.getSaveFileName(
            self, "导出会话", str(Path.home() / default_name), "ZIP 压缩包 (*.zip)"
        )
        if not target:
            return
        try:
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in src.rglob("*"):
                    if f.is_file():
                        zf.write(f, str(f.relative_to(src)))
        except OSError as exc:
            QMessageBox.warning(self, "导出会话", f"导出失败：{exc}")
            return
        QMessageBox.information(self, "导出会话", f"已导出到：\n{target}")

    def _delete(self, session_id: str):
        if QMessageBox.question(
            self, "删除会话", f"确认删除会话 {session_id}？\n（该会话上下文将不可恢复）"
        ) != QMessageBox.Yes:
            return
        for ws_dir in _SESSIONS_DIR.iterdir() if _SESSIONS_DIR.is_dir() else []:
            target = ws_dir / session_id
            if target.is_dir():
                import shutil
                shutil.rmtree(target, ignore_errors=True)
        self._refresh()

    def _clear_all(self):
        if QMessageBox.question(
            self, "清理全部", "确认删除所有 DSH 会话？\n（所有会话上下文将不可恢复）"
        ) != QMessageBox.Yes:
            return
        if _SESSIONS_DIR.is_dir():
            import shutil
            for ws_dir in _SESSIONS_DIR.iterdir():
                if ws_dir.is_dir():
                    shutil.rmtree(ws_dir, ignore_errors=True)
        self._refresh()


# ════════════════════════════════════════════════════════════
#  Tab 3：任务控制
# ════════════════════════════════════════════════════════════

class TasksTab(QWidget):
    _result_ready = Signal(dict)
    _status_ready = Signal(str)

    def __init__(self):
        super().__init__()
        self._busy = False
        self._result_ready.connect(self._on_result)
        self._status_ready.connect(self._set_status)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "把任务交给 DeepSeek Harness（node_dsh）执行并等待完成。传会话 id 可续接同一会话的多轮对话"
            "（在会话管理页点「继续」自动填入）。「取消」终止当前正在运行的任务。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(_style(_sec_color()))
        layout.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)
        self._task_edit = QPlainTextEdit()
        self._task_edit.setFixedHeight(80)
        self._task_edit.setPlaceholderText("自然语言任务描述，如：把 dsh_workspace 里 test.md 的 TODO 列出来")
        form.addRow("任务", self._task_edit)
        self._session_edit = QLineEdit()
        self._session_edit.setPlaceholderText("（可选）续接的会话 id")
        form.addRow("会话 id", self._session_edit)
        self._timeout_edit = QLineEdit("600")
        form.addRow("超时(秒)", self._timeout_edit)
        layout.addLayout(form)

        row = QHBoxLayout()
        for text, handler in (("提交并等待", self._run), ("取消任务", self._cancel), ("查看最近结果", self._show_recent)):
            btn = QPushButton(text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(handler)
            row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._result_box = QPlainTextEdit()
        self._result_box.setReadOnly(True)
        self._result_box.setFixedHeight(180)
        layout.addWidget(self._result_box, 1)

    def set_session_id(self, session_id: str):
        self._session_edit.setText(session_id)

    def _run(self):
        if self._busy:
            return
        task = self._task_edit.toPlainText().strip()
        if not task:
            self._status_ready.emit("请输入任务描述")
            return
        self._busy = True
        self._status_ready.emit("任务已提交，正在执行（可点「取消任务」终止）...")
        threading.Thread(target=self._run_worker, args=(task,), daemon=True).start()

    def _run_worker(self, task: str):
        session_id = self._session_edit.text().strip()
        try:
            timeout = max(1, int(self._timeout_edit.text() or 600))
        except ValueError:
            timeout = 600
        # 与 tool_registry 的 dsh.run_task_sync 同链路：提交 + 轮询 output.json（task_id 匹配）
        import uuid
        task_id = uuid.uuid4().hex[:12]
        req = _NODE_DIR.parent / "shared" / "dsh_task_in.json"
        try:
            payload = {"data_type": "dsh_task", "task": task, "task_id": task_id, "_ts": time.time()}
            if session_id:
                payload["session_id"] = session_id
            req.parent.mkdir(parents=True, exist_ok=True)
            req.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            self._status_ready.emit(f"提交失败：{exc}")
            self._busy = False
            return
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(1.0)
            try:
                data = json.loads(_OUTPUT_JSON.read_text(encoding="utf-8"))
                inner = data.get("data", data) if isinstance(data, dict) else data
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(inner, dict) and inner.get("task_id") == task_id:
                self._result_ready.emit(inner)
                self._busy = False
                return
        self._status_ready.emit(f"等待超时（>{timeout}s），任务仍在后台，可用「查看最近结果」补查")
        self._busy = False

    def _cancel(self):
        pids = _headless_pids()
        if not pids:
            self._status_ready.emit("当前没有正在运行的 DSH 任务")
            return
        for pid in pids:
            try:
                subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=10)
            except (OSError, subprocess.SubprocessError):
                pass
        self._status_ready.emit(f"已终止 {len(pids)} 个 DSH 任务进程")

    def _show_recent(self):
        r = read_recent_result()
        if not r:
            self._result_box.setPlainText("（尚无任务结果）")
            return
        self._result_box.setPlainText(
            json.dumps(r, ensure_ascii=False, indent=2)[:4000]
        )

    def _on_result(self, r: dict):
        ok = bool(r.get("ok"))
        self._status_ready.emit(r.get("message", "DSH 任务完成") if ok else f"DSH 任务失败：{r.get('message', '')}")
        final = r.get("final") or r.get("result") or json.dumps(r, ensure_ascii=False, indent=2)
        self._result_box.setPlainText(str(final)[:4000])
        sid = r.get("session_id", "")
        if sid:
            self._session_edit.setText(sid)

    def _set_status(self, text: str):
        self._status.setText(text)
        self._status.setStyleSheet(_style(_accent_color() if "完成" in text or "已" in text else _warn_color()))


# ════════════════════════════════════════════════════════════
#  Tab 4：运行参数（extra.patch.yml）
# ════════════════════════════════════════════════════════════

_EXTRA_TEMPLATES = {
    "温度": "- id: llm-pi-ai\n  config:\n    temperature: 0.7\n",
    "最大 Token": "- id: llm-pi-ai\n  config:\n    maxTokens: 4096\n",
    "系统提示": "- id: agent-presets\n  config:\n    systemPrompt: |\n      你是一个乐于助人的助手。\n",
}


class ParamsTab(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "编辑附加 patch（extra.patch.yml）——由 node_dsh 以 --patch 加载，所有 headless 任务生效。"
            "可添加 llm / agent 等插件的运行时参数（值以插件实际接受的键为准）。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(_style(_sec_color()))
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.addWidget(QLabel("模板："))
        for name in _EXTRA_TEMPLATES:
            btn = QPushButton(name)
            fit_button_width(btn, padding=28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, n=name: self._append_template(n))
            row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)

        self._editor = QPlainTextEdit()
        self._editor.setPlaceholderText("# 每行一个插件 patch 项，例如：\n- id: llm-pi-ai\n  config:\n    temperature: 0.7")
        layout.addWidget(self._editor, 1)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._load()

    def _load(self):
        if _EXTRA_PATCH.is_file():
            self._editor.setPlainText(_EXTRA_PATCH.read_text(encoding="utf-8"))

    def _append_template(self, name: str):
        text = self._editor.toPlainText().strip()
        if text:
            text += "\n"
        self._editor.setPlainText(text + _EXTRA_TEMPLATES[name])

    def _save(self):
        text = self._editor.toPlainText().strip()
        if not text:
            # 清空附加 patch
            try:
                _EXTRA_PATCH.unlink(missing_ok=True)
            except OSError:
                pass
            self._status.setText("已清空附加 patch")
            self._status.setStyleSheet(_style(_accent_color()))
            return
        try:
            parsed = yaml.safe_load(text)
            if not isinstance(parsed, list):
                raise ValueError("附加 patch 必须是列表（每项一个插件配置）")
        except yaml.YAMLError as exc:
            self._status.setText(f"YAML 语法错误：{exc}")
            self._status.setStyleSheet(_style(_warn_color()))
            return
        except ValueError as exc:
            self._status.setText(str(exc))
            self._status.setStyleSheet(_style(_warn_color()))
            return
        try:
            _EXTRA_PATCH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _EXTRA_PATCH.with_name(_EXTRA_PATCH.name + ".tmp")
            tmp.write_text(
                "# 由 BNOS GUI「DSH 管理-运行参数」维护，node_dsh 以 --patch 加载。\n" + text + "\n",
                encoding="utf-8",
            )
            tmp.replace(_EXTRA_PATCH)
        except OSError as exc:
            self._status.setText(f"保存失败：{exc}")
            self._status.setStyleSheet(_style(_warn_color()))
            return
        self._status.setText(f"已保存（{len(parsed)} 个插件配置项，下次 headless 任务生效）")
        self._status.setStyleSheet(_style(_accent_color()))


# ════════════════════════════════════════════════════════════
#  人格编辑已并入「Agent 预设」分区（dsh-persona 行，见 PresetsTab）。
#  原「目标/人格」Tab（全局 system-prompt.persona 注入）已删除，迁移见
#  _migrate_drop_global_persona()。
# ════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════
#  Tab 6：工具开关
# ════════════════════════════════════════════════════════════

class ToolsTab(QWidget):
    """已挂载工具清单 + 启用/禁用开关（写入 extra.patch.yml 的 disabled 行）。"""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "headless 挂载的工具（tool-* 行，来自 base/headless bundle + profile patch 的合并视图）。"
            "「启用/禁用」写入 extra.patch.yml，下一次任务生效；禁用后该工具不会出现在模型的工具清单里。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(_style(_sec_color()))
        layout.addWidget(hint)

        row = QHBoxLayout()
        self._count_label = QLabel("")
        self._count_label.setStyleSheet(_style(_sec_color()))
        row.addWidget(self._count_label)
        row.addStretch()
        refresh_btn = QPushButton("刷新")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self._refresh)
        row.addWidget(refresh_btn)
        layout.addLayout(row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._container = QWidget()
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, 1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._refresh()

    def _refresh(self):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        tools = list_tool_rows()
        self._count_label.setText(f"共 {len(tools)} 个工具")
        if not tools:
            empty = QLabel("未发现工具行（base bundle 未读取到 tool-* 配置）")
            empty.setStyleSheet(_style(_sec_color()))
            empty.setAlignment(Qt.AlignCenter)
            self._list_layout.insertWidget(0, empty)
            return
        for t in tools:
            self._list_layout.insertWidget(self._list_layout.count() - 1, self._make_row(t))

    def _make_row(self, t: dict) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background: {theme_engine.get('bg_secondary')}; border-radius: 6px;"
            f"border: 1px solid {theme_engine.get('border_color')};"
        )
        lay = QHBoxLayout(card)
        lay.setContentsMargins(10, 6, 10, 6)
        info = QVBoxLayout()
        id_label = QLabel(t["id"])
        id_label.setStyleSheet(_style(_primary_color(), 13, True))
        info.addWidget(id_label)
        if t["name"]:
            name_label = QLabel(t["name"])
            name_label.setStyleSheet(_style(_sec_color(), 11))
            info.addWidget(name_label)
        lay.addLayout(info, 1)
        state_label = QLabel("已启用" if t["enabled"] else "已禁用")
        state_label.setStyleSheet(_style(_accent_color() if t["enabled"] else _warn_color(), 12, True))
        lay.addWidget(state_label)
        text = "禁用" if t["enabled"] else "启用"
        toggle_btn = QPushButton(text)
        fit_button_width(toggle_btn, padding=28)
        toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle_btn.clicked.connect(lambda _, tid=t["id"], en=t["enabled"]: self._toggle(tid, en))
        lay.addWidget(toggle_btn)
        return card

    def _toggle(self, tool_id: str, was_enabled: bool):
        enable = not was_enabled
        try:
            rows = [r for r in _load_extra_patch() if r.get("id") != tool_id]
            rows.append({"id": tool_id, "disabled": not enable})
            _save_extra_patch(rows)
        except OSError as exc:
            self._status.setText(f"操作失败：{exc}")
            self._status.setStyleSheet(_style(_warn_color()))
            return
        self._status.setText(f"{tool_id} 已{'启用' if enable else '禁用'}（下一次任务生效）")
        self._status.setStyleSheet(_style(_accent_color()))
        self._refresh()


# ════════════════════════════════════════════════════════════
#  Tab 7：插件/工具
# ════════════════════════════════════════════════════════════

class PluginsTab(QWidget):
    _output_ready = Signal(str)

    def __init__(self):
        super().__init__()
        self._busy = False
        self._output_ready.connect(self._on_output)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "管理 headless profile 的插件依赖（转发 dsh plugin 命令 → pnpm）。"
            "工具（bash/pwsh/code/web 等）由 agent preset 挂载，本页可增删插件；"
            "修改需先保存运行参数页的配置并重启节点生效。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(_style(_sec_color()))
        layout.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignRight)
        self._pkg_edit = QLineEdit()
        self._pkg_edit.setPlaceholderText("插件包名，如 @deepseek-ai/dsh-tool-http")
        form.addRow("包名", self._pkg_edit)
        layout.addLayout(form)

        row = QHBoxLayout()
        for text, op in (("安装", "add"), ("移除", "remove")):
            btn = QPushButton(text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, o=op: self._plugin(o))
            row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)

        combo_label = QLabel("已装插件组合（base/headless bundle + profile patch 合并视图）")
        combo_label.setStyleSheet(_style(_primary_color(), 13, True))
        layout.addWidget(combo_label)

        self._combo = QPlainTextEdit()
        self._combo.setReadOnly(True)
        self._combo.setFixedHeight(150)
        layout.addWidget(self._combo)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setPlaceholderText("命令输出会显示在这里")
        layout.addWidget(self._output, 1)
        self._refresh_combo()

    def _refresh_combo(self):
        lines = []
        for r in list_composed_rows():
            pkg = f"  ({r['name']})" if r["name"] else ""
            lines.append(f"[{r['state']}] {r['id']}{pkg}")
        self._combo.setPlainText("\n".join(lines) if lines else "（未读取到插件行）")

    def _plugin(self, op: str):
        if self._busy:
            return
        pkg = self._pkg_edit.text().strip()
        if not pkg:
            return
        self._busy = True
        self._output.setPlainText(f"正在 {op} {pkg} ...\n")
        threading.Thread(target=self._plugin_worker, args=(op, pkg), daemon=True).start()

    def _plugin_worker(self, op: str, pkg: str):
        env = dict(os.environ)
        env["DSH_HOME"] = str(_DSH_HOME)
        try:
            proc = subprocess.run(
                ["node", "--import", "tsx/esm", str(_HARNESS / "apps" / "cli" / "src" / "bin.ts"),
                 "plugin", "--profile", "headless", op, pkg],
                cwd=str(_HARNESS),
                env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=300,
            )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as exc:
            self._output_ready.emit(f"执行失败：{exc}")
            self._busy = False
            return
        self._busy = False
        self._output_ready.emit((proc.stdout or "") + (proc.stderr or "") or f"{op} {pkg} 完成（无输出）")

    def _on_output(self, text: str):
        self._output.setPlainText(text)


# ════════════════════════════════════════════════════════════
#  Tab 8：工作区（dsh_workspace 文件浏览器）
# ════════════════════════════════════════════════════════════

_MAX_VIEW_BYTES = 200 * 1024


class WorkspaceTab(QWidget):
    """浏览/查看/新建/删除/重命名 DSH 工作区沙箱（nodes/shared/dsh_workspace）。"""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "DSH 工作区沙箱（nodes/shared/dsh_workspace）——任务可读写的唯一目录。"
            "文件操作即时生效；新建文件后可在任务控制页引用（例如「把 test.md 读出来总结」）。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(_style(_sec_color()))
        layout.addWidget(hint)

        row = QHBoxLayout()
        for text, handler in (
            ("刷新", self._reload),
            ("新建文件", self._new_file),
            ("新建目录", self._new_dir),
            ("重命名", self._rename),
            ("删除", self._delete),
        ):
            btn = QPushButton(text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(handler)
            row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)

        split = QHBoxLayout()
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["名称"])
        self._tree.setColumnWidth(0, 240)
        self._tree.itemSelectionChanged.connect(self._show_content)
        split.addWidget(self._tree, 3)
        self._viewer = QPlainTextEdit()
        self._viewer.setReadOnly(True)
        self._viewer.setPlaceholderText("选择文件查看内容")
        split.addWidget(self._viewer, 4)
        layout.addLayout(split, 1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._reload()

    # ── 路径安全 ──

    def _safe(self, rel: str) -> Path | None:
        try:
            p = (_WORKSPACE / rel).resolve()
        except OSError:
            return None
        return p if p.is_relative_to(_WORKSPACE.resolve()) else None

    # ── 树加载 ──

    def _reload(self):
        self._tree.clear()
        self._viewer.clear()
        root = _WORKSPACE.resolve()
        root.mkdir(parents=True, exist_ok=True)
        self._tree.addTopLevelItem(self._make_item(root, Path(".")))
        self._tree.expandToDepth(0)
        self._status.setText("")

    def _make_item(self, path: Path, rel: Path) -> QTreeWidgetItem:
        item = QTreeWidgetItem([path.name if rel != Path(".") else "dsh_workspace"])
        item.setData(0, Qt.UserRole, str(rel))
        if path.is_dir():
            for child in sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                child_rel = rel / child.name
                if child.is_dir():
                    item.addChild(self._make_item(child, child_rel))
                else:
                    leaf = QTreeWidgetItem([child.name])
                    leaf.setData(0, Qt.UserRole, str(child_rel))
                    item.addChild(leaf)
        return item

    # ── 查看 ──

    def _show_content(self):
        items = self._tree.selectedItems()
        if not items:
            return
        rel = items[0].data(0, Qt.UserRole)
        path = self._safe(rel or "")
        if path is None or path.is_dir():
            self._viewer.clear()
            return
        try:
            size = path.stat().st_size
            if size > _MAX_VIEW_BYTES:
                self._viewer.setPlainText(f"（文件过大 {size // 1024} KB，仅支持预览 {_MAX_VIEW_BYTES // 1024} KB 以内）")
                return
            data = path.read_bytes()
            if b"\x00" in data[:4096]:
                self._viewer.setPlainText("（二进制文件，不支持预览）")
                return
            self._viewer.setPlainText(data.decode("utf-8", errors="replace"))
        except OSError as exc:
            self._viewer.setPlainText(f"读取失败：{exc}")

    # ── 操作 ──

    def _selected_rel(self) -> str | None:
        items = self._tree.selectedItems()
        if not items:
            return None
        return items[0].data(0, Qt.UserRole) or None

    def _new_file(self):
        parent = self._selected_rel() or "."
        path = self._safe(parent)
        if path is None:
            return
        if path.is_file():
            path = path.parent
        name, ok = QInputDialog.getText(self, "新建文件", "文件名：", text="new.md")
        if not ok or not name.strip():
            return
        target = path / name.strip()
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch(exist_ok=True)
        except OSError as exc:
            self._status.setText(f"新建失败：{exc}")
            self._status.setStyleSheet(_style(_warn_color()))
            return
        self._status.setText(f"已新建 {target.relative_to(_WORKSPACE.resolve())}")
        self._status.setStyleSheet(_style(_accent_color()))
        self._reload()

    def _new_dir(self):
        parent = self._selected_rel() or "."
        path = self._safe(parent)
        if path is None:
            return
        if path.is_file():
            path = path.parent
        name, ok = QInputDialog.getText(self, "新建目录", "目录名：", text="new_dir")
        if not ok or not name.strip():
            return
        try:
            (path / name.strip()).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._status.setText(f"新建失败：{exc}")
            self._status.setStyleSheet(_style(_warn_color()))
            return
        self._status.setText(f"已新建目录 {name.strip()}")
        self._status.setStyleSheet(_style(_accent_color()))
        self._reload()

    def _rename(self):
        rel = self._selected_rel()
        if not rel or rel == ".":
            return
        path = self._safe(rel)
        if path is None:
            return
        name, ok = QInputDialog.getText(self, "重命名", "新名称：", text=path.name)
        if not ok or not name.strip() or name.strip() == path.name:
            return
        try:
            path.rename(path.parent / name.strip())
        except OSError as exc:
            self._status.setText(f"重命名失败：{exc}")
            self._status.setStyleSheet(_style(_warn_color()))
            return
        self._status.setText(f"已重命名为 {name.strip()}")
        self._status.setStyleSheet(_style(_accent_color()))
        self._reload()

    def _delete(self):
        rel = self._selected_rel()
        if not rel or rel == ".":
            return
        path = self._safe(rel)
        if path is None:
            return
        if QMessageBox.question(self, "删除", f"确认删除 {rel}？\n（不可恢复）") != QMessageBox.Yes:
            return
        try:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
        except OSError as exc:
            self._status.setText(f"删除失败：{exc}")
            self._status.setStyleSheet(_style(_warn_color()))
            return
        self._status.setText(f"已删除 {rel}")
        self._status.setStyleSheet(_style(_accent_color()))
        self._reload()


# ════════════════════════════════════════════════════════════
#  Tab 9：通用/安全（沙箱权限 / 会话遥测 / 默认温度）
# ════════════════════════════════════════════════════════════

class GeneralTab(QWidget):
    """通用/安全 — 沙箱权限模式 + 会话遥测 + 默认温度。

    沙箱/遥测写入 extra.patch.yml（sandbox-policy / session-telemetry-otel 行），
    默认温度写入 dsh_home/runtime.json（node_dsh 经 DSH_TEMPERATURE 注入 headless）。
    """

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "通用与安全设置：控制 Agent 能读写哪些文件（沙箱权限）、会话数据是否外传（遥测）、"
            "以及每次回答的默认温度。保存后下一次 headless 任务自动生效，无需重启节点。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(_style(_sec_color()))
        layout.addWidget(hint)

        # ── 沙箱权限模式 ──
        sb_title = QLabel("沙箱权限模式（Agent 可访问的文件范围）")
        sb_title.setStyleSheet(_style(_primary_color(), 13, True))
        layout.addWidget(sb_title)
        self._sb_group = QButtonGroup(self)
        sb_row = QHBoxLayout()
        for value, label, desc in SANDBOX_MODES:
            radio = QRadioButton(label)
            radio.setToolTip(desc)
            self._sb_group.addButton(radio)
            sb_row.addWidget(radio)
        sb_row.addStretch()
        layout.addLayout(sb_row)
        sb_sec = QLabel("「全部权限」会同时把审批策略改为「从不询问」——Agent 可执行任意命令，请仅在可信环境使用。")
        sb_sec.setWordWrap(True)
        sb_sec.setStyleSheet(_style(_warn_color(), 11))
        layout.addWidget(sb_sec)

        # ── 会话遥测 ──
        tl_title = QLabel("会话遥测（会话日志是否外传）")
        tl_title.setStyleSheet(_style(_primary_color(), 13, True))
        layout.addWidget(tl_title)
        self._tl_group = QButtonGroup(self)
        tl_row = QHBoxLayout()
        for value, label, desc in TELEMETRY_MODES:
            radio = QRadioButton(label)
            radio.setToolTip(desc)
            self._tl_group.addButton(radio)
            tl_row.addWidget(radio)
        tl_row.addStretch()
        layout.addLayout(tl_row)
        tl_sec = QLabel("默认「仅本地」。完整共享会把对话内容上传到 DeepSeek 遥测端点，谨慎选择。")
        tl_sec.setWordWrap(True)
        tl_sec.setStyleSheet(_style(_warn_color(), 11))
        layout.addWidget(tl_sec)

        # ── 默认温度 ──
        tp_title = QLabel("默认温度（回答随机性）")
        tp_title.setStyleSheet(_style(_primary_color(), 13, True))
        layout.addWidget(tp_title)
        tp_row = QHBoxLayout()
        self._temp_check = QCheckBox("自定义温度")
        self._temp_spin = QDoubleSpinBox()
        self._temp_spin.setRange(0.0, 2.0)
        self._temp_spin.setSingleStep(0.05)
        self._temp_spin.setDecimals(2)
        self._temp_spin.setEnabled(False)
        self._temp_check.toggled.connect(self._temp_spin.setEnabled)
        tp_row.addWidget(self._temp_check)
        tp_row.addWidget(self._temp_spin)
        tp_row.addStretch()
        layout.addLayout(tp_row)
        tp_sec = QLabel("0 代表稳定/事实性，1 代表平衡，更高更发散。留空沿用模型默认。")
        tp_sec.setWordWrap(True)
        tp_sec.setStyleSheet(_style(_sec_color(), 11))
        layout.addWidget(tp_sec)

        layout.addStretch()

        row = QHBoxLayout()
        row.addStretch()
        save_btn = QPushButton("保存")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save)
        row.addWidget(save_btn)
        layout.addLayout(row)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._load()

    def _load(self):
        mode = read_sandbox_mode()
        for i, (value, _label, _desc) in enumerate(SANDBOX_MODES):
            self._sb_group.buttons()[i].setChecked(value == mode)
        tmode = read_telemetry_mode()
        for i, (value, _label, _desc) in enumerate(TELEMETRY_MODES):
            self._tl_group.buttons()[i].setChecked(value == tmode)
        temp = read_runtime_params().get("temperature")
        if isinstance(temp, (int, float)) and not isinstance(temp, bool):
            self._temp_check.setChecked(True)
            self._temp_spin.setValue(float(temp))
        else:
            self._temp_check.setChecked(False)

    def _save(self):
        sb_checked = self._sb_group.checkedButton()
        tl_checked = self._tl_group.checkedButton()
        if sb_checked is None or tl_checked is None:
            self._status.setText("请先选择沙箱权限与会话遥测模式")
            self._status.setStyleSheet(_style(_warn_color()))
            return
        sandbox = SANDBOX_MODES[self._sb_group.buttons().index(sb_checked)][0]
        telemetry = TELEMETRY_MODES[self._tl_group.buttons().index(tl_checked)][0]
        temperature = self._temp_spin.value() if self._temp_check.isChecked() else None
        try:
            save_sandbox_mode(sandbox)
            save_telemetry_mode(telemetry)
            save_runtime_params(temperature)
        except OSError as exc:
            self._status.setText(f"保存失败：{exc}")
            self._status.setStyleSheet(_style(_warn_color()))
            return
        parts = [f"沙箱 {sandbox}", f"遥测 {telemetry}"]
        if temperature is None:
            parts.append("温度默认")
        else:
            parts.append(f"温度 {temperature:g}")
        self._status.setText("已保存（" + " / ".join(parts) + "，下一次任务生效）")
        self._status.setStyleSheet(_style(_accent_color()))


# ════════════════════════════════════════════════════════════
#  Tab 10：Agent 预设 / 自定义 Agent
# ════════════════════════════════════════════════════════════

class PresetsTab(QWidget):
    """Agent 预设（roster）管理：默认预设选择 + 复制创建自定义 Agent + 人格 + 文件编辑 + 删除。

    数据链路：默认预设写 dsh_home/runtime.json preset 字段 → node_dsh/main.py 注入
    DSH_PRESET → headless 的 agent-presets 插件挂载。自定义预设 = dsh_home/.agent-presets
    下目录（agent.cordis.yml 必填 + preset.yml 可选元数据），由 headless 自动追加到 roster。

    人格归属：DSH 官方语义「人格属于预设」——预设组合的 `id: persona`
    （@deepseek-ai/dsh-persona）行为该 agent 提供人格（agent.cordis.yml 顶层首行）。
    原全局「目标/人格」Tab 已删除，人格编辑收敛于此（编辑对话框的人格框）。
    """

    _status_ready = Signal(str)

    def __init__(self):
        super().__init__()
        self._status_ready.connect(self._set_status)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "「Agent 预设」决定每个会话模型侧挂载的能力组合（工具/人格/Skills 等），"
            "预设 = 一个目录（agent.cordis.yml 必填 + preset.yml 可选元数据）。"
            "内置预设由安装提供（只读）；自定义 Agent = 从任一预设复制后自由编辑，"
            "实现你自己的能力组合。人格（Persona）也属于预设——编辑对话框的人格框"
            "写入 agent.cordis.yml 的 dsh-persona 行，留空则该 Agent 继承部署默认人格。"
            "默认预设作用于所有 headless 任务（存 runtime.json，node_dsh 注入 DSH_PRESET）。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(_style(_sec_color()))
        layout.addWidget(hint)

        row = QHBoxLayout()
        row.addWidget(QLabel("默认预设："))
        self._default_combo = QComboBox()
        self._default_combo.setMinimumWidth(220)
        row.addWidget(self._default_combo)
        for text, handler in (
            ("设为默认", self._apply_default),
            ("跟随内置默认", self._clear_default),
            ("刷新", self._refresh),
        ):
            btn = QPushButton(text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(handler)
            row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)

        create_row = QHBoxLayout()
        create_btn = QPushButton("复制创建自定义 Agent")
        create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        create_btn.clicked.connect(self._create)
        create_row.addWidget(create_btn)
        self._count_label = QLabel("")
        self._count_label.setStyleSheet(_style(_sec_color()))
        create_row.addWidget(self._count_label)
        create_row.addStretch()
        layout.addLayout(create_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._container = QWidget()
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll, 1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._refresh()

    # ── 列表 ──

    def _refresh(self):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        presets = list_presets()
        self._count_label.setText(f"共 {len(presets)} 个预设（内置 + 自定义）")
        current = read_preset_default()
        self._default_combo.blockSignals(True)
        self._default_combo.clear()
        self._default_combo.addItem("（跟随内置默认）", "")
        for p in presets:
            label = p["name"] or p["id"]
            self._default_combo.addItem(f"{label}（{p['id']}）", p["id"])
        idx = self._default_combo.findData(current)
        self._default_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._default_combo.blockSignals(False)
        if not presets:
            empty = QLabel("未发现任何预设。内置预设应位于 harness/apps/cli/config/agent-presets/。")
            empty.setStyleSheet(_style(_sec_color()))
            empty.setAlignment(Qt.AlignCenter)
            self._list_layout.insertWidget(0, empty)
            return
        for p in presets:
            self._list_layout.insertWidget(self._list_layout.count() - 1, self._make_card(p))

    def _make_card(self, p: dict) -> QWidget:
        card = QWidget()
        card.setStyleSheet(
            f"background: {theme_engine.get('bg_secondary')}; border-radius: 6px;"
            f"border: 1px solid {theme_engine.get('border_color')};"
        )
        lay = QHBoxLayout(card)
        lay.setContentsMargins(10, 6, 10, 6)
        info = QVBoxLayout()
        title = p["name"] or p["id"]
        id_label = QLabel(f"{title}  ·  {p['id']}")
        id_label.setStyleSheet(_style(_primary_color(), 13, True))
        info.addWidget(id_label)
        trust_color = _sec_color() if p["trust"] == "system" else _accent_color()
        trust_text = "内置（只读）" if p["trust"] == "system" else "自定义"
        desc = p["description"]
        sub = f"[{trust_text}]" + (f"  {desc}" if desc else "")
        sub_label = QLabel(sub)
        sub_label.setStyleSheet(_style(trust_color, 11))
        sub_label.setWordWrap(True)
        info.addWidget(sub_label)
        persona = read_preset_persona(p["id"])
        if persona:
            persona_label = QLabel(f"人格：{persona[:80]}{'…' if len(persona) > 80 else ''}")
            persona_label.setStyleSheet(_style(_sec_color(), 11))
            persona_label.setWordWrap(True)
            info.addWidget(persona_label)
        if p["broken"]:
            broken_label = QLabel(f"⚠ {p['broken']}")
            broken_label.setStyleSheet(_style(_warn_color(), 11))
            broken_label.setWordWrap(True)
            info.addWidget(broken_label)
        lay.addLayout(info, 1)
        if p["trust"] == "user":
            for text, handler in (
                ("复制创建", lambda _, pid=p["id"]: self._create(pid)),
                ("编辑", lambda _, pid=p["id"]: self._edit(pid)),
                ("删除", lambda _, pid=p["id"]: self._delete(pid)),
            ):
                btn = QPushButton(text)
                fit_button_width(btn, padding=28)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(handler)
                lay.addWidget(btn)
        else:
            btn = QPushButton("复制创建")
            fit_button_width(btn, padding=28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, pid=p["id"]: self._create(pid))
            lay.addWidget(btn)
        return card

    # ── 默认预设 ──

    def _apply_default(self):
        pid = self._default_combo.currentData()
        if not pid:
            save_preset_default(None)
            self._status_ready.emit("已恢复跟随内置默认（standard）")
            return
        if _find_preset(pid) is None:
            self._status_ready.emit(f"预设不存在：{pid}")
            return
        save_preset_default(pid)
        self._status_ready.emit(f"默认预设已设为 {pid}（下一次 headless 任务生效）")

    def _clear_default(self):
        self._default_combo.setCurrentIndex(0)
        self._apply_default()

    # ── 复制创建自定义 Agent ──

    def _create(self, source_id: str = ""):
        presets = list_presets()
        if not presets:
            self._status_ready.emit("没有可用作模板的预设")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("复制创建自定义 Agent")
        form = QFormLayout(dlg)
        form.setSpacing(10)
        source_combo = QComboBox()
        for p in presets:
            label = p["name"] or p["id"]
            source_combo.addItem(f"{label}（{p['id']}）", p["id"])
        src_idx = source_combo.findData(source_id)
        source_combo.setCurrentIndex(src_idx if src_idx >= 0 else 0)
        form.addRow("源预设", source_combo)
        id_edit = QLineEdit()
        id_edit.setPlaceholderText("小写字母/数字/中划线，如 my-coding-agent")
        form.addRow("新 id", id_edit)
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("（可选）显示名")
        form.addRow("显示名", name_edit)
        btn_row = QHBoxLayout()
        ok_btn = QPushButton("创建")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn = QPushButton("取消")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addStretch()
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        form.addRow(btn_row)
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        if dlg.exec() != QDialog.Accepted:
            return
        new_id = id_edit.text().strip()
        name = name_edit.text().strip()
        try:
            create_custom_preset(source_combo.currentData(), new_id, name)
        except ValueError as exc:
            self._status_ready.emit(f"创建失败：{exc}")
            return
        self._status_ready.emit(f"已创建自定义 Agent：{new_id}（可点「编辑」调整 agent.cordis.yml / preset.yml）")
        self._refresh()

    # ── 编辑自定义 Agent 文件 ──

    def _edit(self, preset_id: str):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"编辑自定义 Agent：{preset_id}")
        dlg.resize(700, 620)
        lay = QVBoxLayout(dlg)

        persona_title = QLabel("人格（Persona）")
        persona_title.setStyleSheet(_style(_primary_color(), 13, True))
        lay.addWidget(persona_title)
        persona_edit = QPlainTextEdit()
        persona_edit.setPlaceholderText(
            "该 Agent 的人格（写入 agent.cordis.yml 的 dsh-persona 行）。留空 = 移除该行，"
            "继承部署默认人格。支持 {{model}} / {{cwd}} 占位变量。"
        )
        lay.addWidget(persona_edit)

        top = QHBoxLayout()
        top.addWidget(QLabel("文件："))
        file_combo = QComboBox()
        file_combo.addItem("agent.cordis.yml（插件组合）", "agent.cordis.yml")
        file_combo.addItem("preset.yml（显示元数据）", "preset.yml")
        top.addWidget(file_combo)
        top.addStretch()
        lay.addLayout(top)
        editor = QPlainTextEdit()
        editor.setPlaceholderText(
            "agent.cordis.yml 必须是插件行列表（每行带 name），保存时校验；"
            "preset.yml 是映射（name/description/order）。注意：agent.cordis.yml 里的"
            "persona 行由上方人格框统一管理（保存时以其为准）。"
        )
        lay.addWidget(editor, 1)
        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn = QPushButton("关闭")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        lay.addLayout(btn_row)
        status_label = QLabel("")
        status_label.setWordWrap(True)
        lay.addWidget(status_label)

        def load():
            try:
                editor.setPlainText(read_preset_file(preset_id, file_combo.currentData()))
            except (ValueError, OSError) as exc:
                status_label.setText(f"读取失败：{exc}")
                status_label.setStyleSheet(_style(_warn_color()))
            if file_combo.currentData() == "agent.cordis.yml":
                persona_edit.setPlainText(read_preset_persona(preset_id))

        def save():
            try:
                save_preset_file(preset_id, file_combo.currentData(), editor.toPlainText())
            except (ValueError, OSError) as exc:
                status_label.setText(f"保存失败：{exc}")
                status_label.setStyleSheet(_style(_warn_color()))
                return
            if file_combo.currentData() == "agent.cordis.yml":
                try:
                    write_preset_persona(preset_id, persona_edit.toPlainText())
                except ValueError as exc:
                    status_label.setText(f"组合已保存，但人格写入失败：{exc}")
                    status_label.setStyleSheet(_style(_warn_color()))
                    return
            status_label.setText("已保存（下一次 headless 任务生效）")
            status_label.setStyleSheet(_style(_accent_color()))

        file_combo.currentIndexChanged.connect(load)
        save_btn.clicked.connect(save)
        cancel_btn.clicked.connect(dlg.reject)
        load()
        dlg.exec()

    # ── 删除自定义 Agent ──

    def _delete(self, preset_id: str):
        if QMessageBox.question(
            self, "删除预设", f"确认删除自定义 Agent「{preset_id}」？\n（目录将不可恢复）"
        ) != QMessageBox.Yes:
            return
        try:
            delete_custom_preset(preset_id)
        except ValueError as exc:
            self._status_ready.emit(str(exc))
            return
        self._status_ready.emit(f"已删除自定义 Agent：{preset_id}")
        self._refresh()

    def _set_status(self, text: str):
        self._status.setText(text)
        self._status.setStyleSheet(_style(_accent_color() if "失败" not in text else _warn_color()))


# ════════════════════════════════════════════════════════════
#  页面主体
# ════════════════════════════════════════════════════════════

class DshManagePage(QWidget):
    """DSH 管理大页（分区卡片）。"""

    def __init__(self):
        super().__init__()
        # 迁移：原「目标/人格」Tab 已并入预设，清理 extra.patch 残留的全局 persona 行
        _migrate_drop_global_persona()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QLabel("DSH 管理")
        header.setStyleSheet(_style(_primary_color(), 15, True))
        layout.addWidget(header)

        self._tasks_tab = TasksTab()
        self._sessions_tab = SessionsTab(on_resume=self._tasks_tab.set_session_id)

        tabs = QTabWidget()
        tabs.addTab(ModelConfigTab(), "模型配置")
        tabs.addTab(self._sessions_tab, "会话")
        tabs.addTab(self._tasks_tab, "任务")
        tabs.addTab(ToolsTab(), "工具开关")
        tabs.addTab(PluginsTab(), "插件")
        tabs.addTab(WorkspaceTab(), "工作区")
        tabs.addTab(ParamsTab(), "运行参数")
        tabs.addTab(GeneralTab(), "通用/安全")
        tabs.addTab(PresetsTab(), "Agent 预设")
        layout.addWidget(tabs, 1)
