import os
import sys
import json
import time
import hashlib
import subprocess
import shutil
import signal
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from concurrent.futures import ThreadPoolExecutor as _TimeoutPool
from datetime import datetime


def _is_frozen_exe() -> bool:
    """检测是否为 Nuitka/PyInstaller 打包的 exe"""
    if getattr(sys, 'frozen', False):
        return True
    try:
        __import__('__compiled__')
        return True
    except ImportError:
        pass
    if sys.argv[0].lower().endswith('.exe'):
        return True
    return False


def _repair_pyvenv_cfg(venv_path):
    """重建缺失的 pyvenv.cfg"""
    cfg_content = f"""home = {os.path.dirname(sys.executable)}
implementation = CPython
version_info = {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}
include-system-site-packages = false
base-prefix = {sys.prefix}
base-exec-prefix = {sys.prefix}
base-executable = {sys.executable}
"""
    cfg_path = os.path.join(venv_path, "pyvenv.cfg")
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(cfg_content)


# exe 模式下用 cwd（Popen 已设 cwd=node_path），开发模式用 __file__
if _is_frozen_exe():
    NODE_DIR = os.getcwd()
else:
    NODE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(NODE_DIR, "node_config.json")
LOG_DIR = os.path.join(NODE_DIR, "logs")

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)


def log(msg, level="INFO"):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] [{level}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        pass
    with open(os.path.join(LOG_DIR, "listener.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ==================== 自愈逻辑 ====================

def check_and_repair_environment():
    """检测并修复虚拟环境"""
    if _is_frozen_exe():
        log("exe 模式，跳过 venv 检测", "INFO")
        return True

    venv_path = os.path.join(NODE_DIR, "venv")
    if os.name == "nt":
        python_exe = os.path.join(venv_path, "Scripts", "python.exe")
    else:
        python_exe = os.path.join(venv_path, "bin", "python")

    # 检测 pyvenv.cfg 缺失
    pyvenv_cfg = os.path.join(venv_path, "pyvenv.cfg")
    if os.path.exists(python_exe) and not os.path.exists(pyvenv_cfg):
        log("pyvenv.cfg 缺失，尝试修复...", "WARNING")
        try:
            _repair_pyvenv_cfg(venv_path)
            if os.path.exists(pyvenv_cfg):
                log("pyvenv.cfg 已重建")
                return True
        except Exception as e:
            log(f"重建失败: {e}", "ERROR")

    if not os.path.exists(python_exe):
        log("venv 异常，尝试自动修复...", "WARNING")
        if os.path.exists(venv_path):
            shutil.rmtree(venv_path, ignore_errors=True)
        software_root = os.path.dirname(NODE_DIR)
        create_node_script = os.path.join(software_root, "..", "python_create_node.py")
        if os.path.exists(create_node_script):
            try:
                subprocess.run(
                    [sys.executable, create_node_script, "--repair-only", NODE_DIR],
                    capture_output=True, text=True, timeout=120,
                )
                log("venv 重建成功")
                return True
            except Exception as e:
                log(f"重建失败: {e}", "ERROR")
                return False
        else:
            log("找不到 python_create_node.py，尝试直接创建 venv...", "WARNING")
            try:
                subprocess.run(
                    [sys.executable, "-m", "venv", venv_path],
                    capture_output=True, text=True, timeout=60,
                )
                log("venv 创建成功")
            except Exception as e:
                log(f"venv 创建失败: {e}", "ERROR")
                return False
    return True


if not check_and_repair_environment():
    log("环境修复失败", "ERROR")
    sys.exit(1)

# ==================== 配置加载 ====================

try:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
except Exception as e:
    log(f"配置加载失败: {e}", "ERROR")
    sys.exit(1)

UPPER_FILE = os.path.abspath(os.path.join(NODE_DIR, cfg["listen_upper_file"])) if cfg.get("listen_upper_file") else ""
OUTPUT_FILE = os.path.abspath(os.path.join(NODE_DIR, cfg["output_file"])) if cfg.get("output_file") else ""

# ==================== 多端口输出路由 ====================
OUTPUT_PORTS = {}
for port in cfg.get("output_ports", []):
    if isinstance(port, dict) and port.get("name"):
        fpath = port.get("output_file", "")
        if fpath:
            OUTPUT_PORTS[port["name"]] = os.path.abspath(os.path.join(NODE_DIR, fpath))
# ==================== 多端口输出路由结束 ====================

# ==================== GUI 通信路径 ====================
GUI_INPUT_FILE = os.path.abspath(os.path.join(NODE_DIR, "../shared/gui_input.json"))
GUI_REPLY_FILE = os.path.abspath(os.path.join(NODE_DIR, "../shared/gui_reply.json"))
GUI_CMD_FILE = os.path.abspath(os.path.join(NODE_DIR, "../shared/gui_cmd.json"))
GUI_CMD_RESULT_FILE = os.path.abspath(os.path.join(NODE_DIR, "../shared/gui_cmd_result.json"))
# ==================== GUI 通信路径结束 ====================

NODE_NAME = cfg["node_name"]
MY_FILTER = cfg.get("filter", {})
PROCESS_FLAG = f"_processed_{NODE_NAME}"

import atexit

PID_FILE = os.path.join(NODE_DIR, f"{NODE_NAME}.pid")


def cleanup():
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
        log("PID 文件已清理")
    log("程序已退出")


atexit.register(cleanup)


# ==================== 多源解析 ====================

def find_project_root():
    """从 NODE_DIR 向上查找项目根目录（包含 pipeline.json）"""
    d = NODE_DIR
    for _ in range(5):
        if os.path.isfile(os.path.join(d, "pipeline.json")):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.dirname(NODE_DIR))


def resolve_input_sources():
    """自动解析输入源文件列表。

    优先级：
    1. listen_upper_file（如果设置了）
    2. port_mappings 中的字符串值（输入端口直接映射到文件路径）
    3. pipeline.json edges 中指向本节点的上游节点 output.json
    """
    sources = []

    # 1. listen_upper_file
    if UPPER_FILE:
        sources.append(UPPER_FILE)

    # 2. port_mappings 字符串值（输入端口 → 文件路径）
    for port_name, mapping in cfg.get("port_mappings", {}).items():
        if isinstance(mapping, str):
            path = mapping if os.path.isabs(mapping) else os.path.abspath(os.path.join(NODE_DIR, mapping))
            sources.append(path)

    # 3. pipeline.json edges
    project_root = find_project_root()
    pipeline_path = os.path.join(project_root, "pipeline.json")
    nodes_dir = os.path.join(project_root, "nodes")

    if os.path.exists(pipeline_path):
        try:
            with open(pipeline_path, "r", encoding="utf-8") as f:
                pipeline = json.load(f)
            for edge in pipeline.get("edges", []):
                if edge["to"] == NODE_NAME:
                    src_node = edge["from"]
                    src_node_dir = os.path.join(nodes_dir, src_node)
                    src_cfg_path = os.path.join(src_node_dir, "node_config.json")
                    if os.path.exists(src_cfg_path):
                        with open(src_cfg_path, "r", encoding="utf-8") as f2:
                            src_cfg = json.load(f2)
                        # 根据 source_port 匹配 output_ports
                        src_port = edge.get("source_port", "default")
                        src_output_file = src_cfg.get("output_file", "./output.json")
                        for port in src_cfg.get("output_ports", []):
                            if isinstance(port, dict) and port.get("name") == src_port and port.get("output_file"):
                                src_output_file = port["output_file"]
                                break
                        src_path = os.path.abspath(os.path.join(src_node_dir, src_output_file))
                        if src_path not in sources:
                            sources.append(src_path)
                            log(f"  上游节点 [{src_node}] → {src_path}")
        except Exception as e:
            log(f"解析 pipeline.json 输入源失败: {e}", "WARNING")

    # 大小写规范化去重（Windows 上 E:\ 和 e:\ 是同一路径）
    seen = set()
    deduped = []
    for p in sources:
        key = os.path.normcase(p)
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped


def unwrap_data(data):
    """如果数据是包装格式 {'code': 0, 'data': {...}}，提取内层 data"""
    if isinstance(data, dict) and "code" in data and "data" in data:
        inner = data["data"]
        if isinstance(inner, dict):
            return inner
    return data


def is_my_data(data):
    """注意力过滤（或关系匹配）"""
    if not MY_FILTER:
        return True
    for _port_name, criteria in MY_FILTER.items():
        if all(data.get(k) == v for k, v in criteria.items()):
            return True
    return False


# ==================== 解析输入源 ====================

INPUT_SOURCES = resolve_input_sources()

# 将 GUI 输入路径硬编码加入输入源（不依赖 port_mappings 配置）
if GUI_INPUT_FILE not in INPUT_SOURCES:
    INPUT_SOURCES.append(GUI_INPUT_FILE)
# GUI 管理命令通道（独立文件，不与聊天消息竞态）
INPUT_SOURCES.append(GUI_CMD_FILE)

if not INPUT_SOURCES:
    log("没有配置任何输入源，将保持待机状态等待数据...", "INFO")
else:
    log(f"输入源 ({len(INPUT_SOURCES)} 个):")
    for s in INPUT_SOURCES:
        log(f"  - {s}")

log("=" * 50)
log(f"节点启动: {NODE_NAME}")
log(f"过滤: {MY_FILTER}")
with open(PID_FILE, "w") as f:
    f.write(str(os.getpid()))
log(f"PID 文件已生成: {PID_FILE}")

# ==================== 并发处理 ====================
WRITE_LOCK = threading.Lock()


def _ensure_venv_importable():
    """将节点 venv 的 site-packages 加入 sys.path，使直接 import main 可用。"""
    import sys
    if _is_frozen_exe():
        return True
    venv_path = os.path.join(NODE_DIR, "venv")
    if not os.path.exists(venv_path):
        log("venv 不存在，回退到子进程模式", "WARNING")
        return False
    if os.name == "nt":
        sp = os.path.join(venv_path, "Lib", "site-packages")
    else:
        sp = os.path.join(venv_path, "lib", f"python{sys.version_info.major}.{sys.version_info.minor}", "site-packages")
    if os.path.exists(sp):
        if sp not in sys.path:
            sys.path.insert(0, sp)
        return True
    log("venv site-packages 不存在，回退到子进程模式", "WARNING")
    return False


_AAA_MAIN = None

def _preload_memos_index():
    """启动时异步预加载 MemOS 模型和索引（不阻塞主循环）。"""
    thr = threading.Thread(target=_do_load_memos, daemon=True)
    thr.start()
    log("MemOS 预加载已在后台线程启动")


def _do_load_memos():
    """在后台线程中加载模型、索引，并生成 Logseq 回填数据。"""
    try:
        from config import load_config
        from pathlib import Path
        cfg = load_config()
        db_path = Path(cfg.get("db_path", "../shared/chatbot.db")).resolve()
        if db_path.exists():
            if not _ensure_venv_importable():
                log("venv 不可用，跳过 MemOS 预加载", "WARNING")
                return
            import memos as _memos
            _memos.preload()  # 加载 SentenceTransformer
            _memos.load_index(str(db_path))  # 加载已有的索引
            log("MemOS 模型和索引已预加载完成")
            # 导出 knowledge_graph.json，供 GUI 知识库面板使用
            threading.Thread(target=_memos.rebuild_knowledge_index,
                             args=(str(db_path),), daemon=True).start()
            # 模型就绪 → 生成 Logseq 回填批处理文件
            _generate_logseq_backfill(str(db_path))
        else:
            log(f"数据库不存在，跳过 MemOS 预加载: {db_path}")
    except Exception as e:
        log(f"MemOS 预加载失败: {e}", "WARNING")


def _generate_logseq_backfill(db_path: str):
    """模型就绪后，读取所有 long_term_memory 条目，计算关联，生成回填文件。

    GUI LogseqWriter 检测到该文件后，会更新已写入的 .md 文件，补上 [[wikilink]]。
    """
    import memos as _memos
    import sqlite3

    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT id, content FROM long_term_memory "
            "WHERE content IS NOT NULL AND content != '' ORDER BY id"
        ).fetchall()
        conn.close()
    except Exception as e:
        log(f"Logseq 回填: 读取 long_term_memory 失败: {e}", "WARNING")
        return

    if not rows:
        log("Logseq 回填: long_term_memory 为空，跳过")
        return

    entries_out = []
    for eid, content in rows:
        raw = _memos.retrieve_raw(content, top_k=5)
        related = []
        for r in raw:
            rid = r.get("entry_id", 0)
            if rid == eid:
                continue  # 排除自身
            try:
                inner_conn = sqlite3.connect(db_path)
                tbl = r.get("table", "long_term_memory")
                row2 = inner_conn.execute(
                    f"SELECT content FROM [{tbl}] WHERE id=?", (rid,)
                ).fetchone()
                inner_conn.close()
                if row2:
                    related.append({
                        "content": str(row2[0])[:100],
                        "score": round(r["score"], 4),
                    })
            except Exception:
                pass
        entries_out.append({
            "content": content,
            "tags": "",
            "related": related,
        })

    # 写入 nodes/shared/ 供 GUI 读取
    shared_dir = os.path.join(os.path.dirname(NODE_DIR), "shared")
    os.makedirs(shared_dir, exist_ok=True)
    batch_path = os.path.join(shared_dir, "logseq_backfill_batch.json")
    try:
        with open(batch_path, "w", encoding="utf-8") as f:
            json.dump({"type": "backfill", "entries": entries_out}, f,
                      ensure_ascii=False, indent=2)
        log(f"Logseq 回填批处理文件已生成 ({len(entries_out)} 条)")
    except Exception as e:
        log(f"Logseq 回填文件写入失败: {e}", "WARNING")

def _get_aaa_main():
    """惰性加载 main 模块（首次调用时导入 MyNode，模型常驻内存）。"""
    global _AAA_MAIN
    if _AAA_MAIN is not None:
        return _AAA_MAIN
    if not _ensure_venv_importable():
        return None
    import main as _m
    _AAA_MAIN = _m
    log("已加载 AAA main 模块（SentenceTransformer 已驻留内存）")
    return _AAA_MAIN


MAX_WORKERS = min(len(INPUT_SOURCES) or 1, 4)
_trackers = {p: 0.0 for p in INPUT_SOURCES}
_content_hashes = {}

RUNNING = True


def signal_handler(signum, frame):
    global RUNNING
    log("收到退出信号", "WARNING")
    RUNNING = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# 启动时预加载 MemOS 模型和索引（异步，不阻塞主循环）
_preload_memos_index()

log("=" * 50)


def _write_output(data, out_path):
    """线程安全地写入输出文件"""
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with WRITE_LOCK:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(data)
    log(f"写入 {out_path}")


def _process_one(src_path, raw_data):
    """在线程中处理单条数据"""
    try:
        input_data = unwrap_data(raw_data)
        log(f"处理: {src_path}")

        if _is_frozen_exe():
            import importlib
            _node_main = importlib.import_module("_bnos_main")
            _node_main.NODE_DIR = NODE_DIR
            result = _node_main.process(input_data)
            output = json.dumps({
                "code": 0,
                "type": cfg.get("output_type", "default"),
                "data": result
            }, ensure_ascii=False)
        else:
            # 直接 import 调用 — 模型常驻内存，避免子进程开销
            aaa_main = _get_aaa_main()
            if aaa_main is None:
                # venv 不可用，回退到子进程模式
                py_path = os.path.join(NODE_DIR, "venv", "Scripts", "python.exe") if os.name == "nt" else os.path.join(NODE_DIR, "venv", "bin", "python")
                if not os.path.exists(py_path):
                    py_path = sys.executable
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                res = subprocess.run(
                    [py_path, os.path.join(NODE_DIR, "main.py"), json.dumps(input_data)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    env=env, timeout=180,
                )
                output = res.stdout.strip()
                if res.stderr:
                    log(f"stderr: {res.stderr[:200]}", "WARNING")
            else:
                with _TimeoutPool(max_workers=1) as pool:
                    future = pool.submit(aaa_main._node.process, input_data)
                    try:
                        result = future.result(timeout=180)
                    except Exception:
                        log(f"处理超时 [{src_path}]: 超过 180 秒未返回", "ERROR")
                        return
                # 格式化输出（与 main.py __main__ 块逻辑一致）
                if isinstance(result, list):
                    output_obj = {"code": 0, "data": result}
                else:
                    port = result.pop("_port") if "_port" in result else cfg.get("output_type", "default")
                    output_obj = {"code": 0, "type": port, "data": result}
                output = json.dumps(output_obj, ensure_ascii=False)

        if not output:
            log("空返回")
            return

        # 解析返回结果
        try:
            output_obj = json.loads(output)
        except json.JSONDecodeError:
            log(f"输出非 JSON 格式，跳过: {output[:100]}", "WARNING")
            return

        # ── 1) 按端口路由 ──
        result_data = output_obj.get("data", {})

        if isinstance(result_data, list):
            # 列表输出：按每个 item 的 _port 分别路由到对应文件
            for item in result_data:
                if not isinstance(item, dict):
                    continue
                port_name = item.pop("_port", "default")
                out_path = OUTPUT_PORTS.get(port_name, OUTPUT_FILE)
                item_output = json.dumps({"code": 0, "data": item}, ensure_ascii=False)
                _write_output(item_output, out_path)

                # reply 额外写入 gui_reply.json
                if item.get("data_type") == "reply":
                    gui_reply_dir = os.path.dirname(GUI_REPLY_FILE)
                    if gui_reply_dir:
                        os.makedirs(gui_reply_dir, exist_ok=True)
                    with WRITE_LOCK:
                        with open(GUI_REPLY_FILE, "w", encoding="utf-8") as f:
                            json.dump(item, f, indent=2, ensure_ascii=False)
                    log("reply 已写入 gui_reply.json")

                # db_result 写入 gui_cmd_result.json
                if item.get("data_type") == "db_result":
                    cmd_result_dir = os.path.dirname(GUI_CMD_RESULT_FILE)
                    if cmd_result_dir:
                        os.makedirs(cmd_result_dir, exist_ok=True)
                    with WRITE_LOCK:
                        with open(GUI_CMD_RESULT_FILE, "w", encoding="utf-8") as f:
                            json.dump(item, f, indent=2, ensure_ascii=False)
                    log("db_result 已写入 gui_cmd_result.json")
        else:
            # 单个对象输出
            port_name = output_obj.get("type", "default")
            out_path = OUTPUT_PORTS.get(port_name, OUTPUT_FILE)
            _write_output(output, out_path)

            data_type = result_data.get("data_type", "") if isinstance(result_data, dict) else ""
            if data_type == "reply":
                gui_reply_dir = os.path.dirname(GUI_REPLY_FILE)
                if gui_reply_dir:
                    os.makedirs(gui_reply_dir, exist_ok=True)
                with WRITE_LOCK:
                    with open(GUI_REPLY_FILE, "w", encoding="utf-8") as f:
                        json.dump(result_data, f, indent=2, ensure_ascii=False)
                log("reply 已写入 gui_reply.json")
            if data_type == "db_result":
                cmd_result_dir = os.path.dirname(GUI_CMD_RESULT_FILE)
                if cmd_result_dir:
                    os.makedirs(cmd_result_dir, exist_ok=True)
                with WRITE_LOCK:
                    with open(GUI_CMD_RESULT_FILE, "w", encoding="utf-8") as f:
                        json.dump(result_data, f, indent=2, ensure_ascii=False)
                log("db_result 已写入 gui_cmd_result.json")

        # 标记上游数据已处理
        raw_data[PROCESS_FLAG] = True
        with WRITE_LOCK:
            with open(src_path, "w", encoding="utf-8") as f:
                json.dump(raw_data, f, indent=2, ensure_ascii=False)

    except (subprocess.TimeoutExpired, TimeoutError):
        log(f"处理超时 [{src_path}]: 超过 180 秒未返回", "ERROR")
    except Exception as e:
        log(f"处理异常 [{src_path}]: {e}", "ERROR")


# ── 主循环：快速检查 → 提交到线程池 ──
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    while RUNNING:
        try:
            for src_path in INPUT_SOURCES:
                if not os.path.isfile(src_path):
                    continue

                try:
                    current_mtime = os.path.getmtime(src_path)
                except OSError:
                    continue

                if current_mtime <= _trackers.get(src_path, 0.0):
                    continue

                try:
                    with open(src_path, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    _trackers[src_path] = current_mtime
                    continue

                content_str = json.dumps(raw_data, ensure_ascii=False)
                content_hash = hashlib.md5(content_str.encode()).hexdigest()
                if content_hash == _content_hashes.get(src_path):
                    _trackers[src_path] = current_mtime
                    continue

                _trackers[src_path] = current_mtime
                _content_hashes[src_path] = content_hash

                if isinstance(raw_data, dict) and raw_data.get(PROCESS_FLAG):
                    continue
                if not is_my_data(unwrap_data(raw_data)):
                    continue

                log(f"新数据: {src_path}")
                executor.submit(_process_one, src_path, raw_data)

        except json.JSONDecodeError:
            log("数据包格式错误", "ERROR")
        except Exception as e:
            log(f"循环异常: {e}", "ERROR")

        time.sleep(0.1)
