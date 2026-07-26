"""Logseq 知识写入器 — 监听 AAA 的 logseq 输出文件，写入 Logseq pages 目录。"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from gui.core.config import AppConfig

# ─── 文件路径 ───────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_LOGSEQ_OUTPUT = str(_PROJECT_ROOT / "nodes" / "node_python_aaa_cognition" / "output_logseq.json")
_BACKFILL_FILE = str(_PROJECT_ROOT / "nodes" / "shared" / "logseq_backfill_batch.json")


class LogseqWriter(QObject):
    """Logseq 知识写入器。

    实时模式：轮询 output_logseq.json，每次新条目立即生成 .md 文件。
    回填模式：模型就绪后 AAA 生成 logseq_backfill_batch.json，更新已有 .md 补上 [[wikilink]]。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._config = AppConfig()
        self._last_mtime: float = 0.0
        self._last_hash: str = ""
        self._backfill_mtime: float = 0.0
        self._pages_dir: str = ""

        self._load_config()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.timeout.connect(self._poll_backfill)
        self._timer.start(3000)

    # ── 配置 ─────────────────────────────────────

    def _load_config(self):
        try:
            config_path = _PROJECT_ROOT / "gui_config.json"
            if config_path.exists():
                cfg = json.loads(config_path.read_text("utf-8"))
                self._pages_dir = cfg.get("logseq", {}).get("pages_dir", "")
        except Exception:
            self._pages_dir = ""

    def set_pages_dir(self, path: str):
        self._pages_dir = path
        self._save_config()

    def _save_config(self):
        try:
            config_path = _PROJECT_ROOT / "gui_config.json"
            cfg = json.loads(config_path.read_text("utf-8")) if config_path.exists() else {}
            cfg.setdefault("logseq", {})["pages_dir"] = self._pages_dir
            config_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    # ── 内部工具 ─────────────────────────────────

    @staticmethod
    def _make_filename(content: str) -> str:
        """根据内容前 40 字生成 .md 文件名，与 _write_entry 保持一致。"""
        title = content[:40].strip().replace("\n", " ")
        safe = "".join(c for c in title if c.isalnum() or c in " _-，。").strip()
        if not safe:
            safe = f"知识-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        return f"{safe}.md"

    @staticmethod
    def _build_related_lines(related: list[dict]) -> list[str]:
        """根据 related 数据生成 related:: 和 ## Related 块。"""
        if not related:
            return []
        related_texts = []
        for r in related:
            rc = r.get("content", "").strip()[:20]
            if rc:
                related_texts.append(f"[[{rc}]]")
        if not related_texts:
            return []
        lines = [f"  related:: {'、'.join(related_texts)}"]
        lines.append("")
        lines.append("## Related")
        for rt in related_texts:
            lines.append(f"- {rt}")
        return lines

    def _update_or_create_md(self, content: str, tags: str, related: list[dict]) -> None:
        """更新已存在的 .md 文件（补 related），或创建新文件。"""
        pages_dir = Path(self._pages_dir)
        if not pages_dir.exists():
            try:
                pages_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                return

        filename = self._make_filename(content)
        filepath = pages_dir / filename

        # 生成 related 行
        extra = self._build_related_lines(related)
        has_related = bool(extra)

        if filepath.exists():
            # ── 更新已有文件 ──
            text = filepath.read_text("utf-8")

            # 如果已有 related::，不重复更新（去重）
            if "related::" in text:
                return

            # 如果没有 related 但是现在有了，追加
            if has_related:
                text = text.rstrip("\n")
                for line in extra:
                    text += "\n" + line
                text += "\n"
                filepath.write_text(text, encoding="utf-8")
                print(f"[LogseqWriter] 已更新: {filepath} (补关联)")
        else:
            # ── 创建新文件 ──
            lines = [f"- {content}"]
            if tags:
                tag_list = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()]
                if tag_list:
                    lines.append(f"  tags:: {', '.join(tag_list)}")
            today = datetime.now().strftime("%Y-%m-%d %H:%M")
            lines.append(f"  source:: AI 认知 ({today})")
            lines.extend(extra)
            lines.append("")
            filepath.write_text("\n".join(lines), encoding="utf-8")
            print(f"[LogseqWriter] 已创建: {filepath}")

    # ── 实时轮询（单条） ──────────────────────────

    def _poll(self):
        if not self._pages_dir:
            return

        path = Path(_LOGSEQ_OUTPUT)
        if not path.exists() or path.stat().st_size == 0:
            return

        try:
            mtime = path.stat().st_mtime
            if mtime <= self._last_mtime:
                return

            data = json.loads(path.read_text("utf-8"))
            item = data.get("data", {})
            if not isinstance(item, dict):
                return
            if item.get("data_type") != "knowledge_logseq":
                return

            ch = hashlib.md5(json.dumps(item, ensure_ascii=False).encode()).hexdigest()
            if ch == self._last_hash:
                self._last_mtime = mtime
                return

            self._last_mtime = mtime
            self._last_hash = ch
            threading.Thread(
                target=self._write_entry, args=(item,), daemon=True
            ).start()
        except (json.JSONDecodeError, OSError, KeyError):
            pass

    def _write_entry(self, item: dict):
        content = item.get("content", "").strip()
        tags = item.get("tags", "").strip()
        related = item.get("related", [])
        if content:
            self._update_or_create_md(content, tags, related)

    # ── 回填轮询（批量补关联） ─────────────────────

    def _poll_backfill(self):
        if not self._pages_dir:
            return

        path = Path(_BACKFILL_FILE)
        if not path.exists() or path.stat().st_size == 0:
            return

        try:
            mtime = path.stat().st_mtime
            if mtime <= self._backfill_mtime:
                return
            self._backfill_mtime = mtime

            data = json.loads(path.read_text("utf-8"))
            if data.get("type") != "backfill":
                return

            entries = data.get("entries", [])
            if not entries:
                return

            print(f"[LogseqWriter] 检测到回填批处理文件 ({len(entries)} 条)，开始更新...")
            for entry in entries:
                content = entry.get("content", "").strip()
                tags = entry.get("tags", "").strip()
                related = entry.get("related", [])
                if content:
                    self._update_or_create_md(content, tags, related)

            # 处理完毕，删除回填文件
            path.unlink(missing_ok=True)
            self._backfill_mtime = 0.0
            print(f"[LogseqWriter] 回填完成，已删除批处理文件")
        except (json.JSONDecodeError, OSError, KeyError) as e:
            print(f"[LogseqWriter] 回填处理失败: {e}")
