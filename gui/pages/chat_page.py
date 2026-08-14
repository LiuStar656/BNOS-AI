"""聊天页 — 消息列表 + ChatInput（WeChat 风格发送框）"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.core.config import AppConfig
from gui.core.event_bus import event_bus
from gui.core.message_manager import MessageManager
from gui.core.messages import THEME_CHANGED
from gui.core.state import AppState
from gui.widgets.chat_bubble import ChatBubble
from gui.widgets.chat_input import ChatInput
from gui.widgets.conversation_list import ConversationList

_TYPING_INTERVAL_MS = 50  # 逐字输出间隔（毫秒）

# 对话历史持久化文件
_HISTORY_FILE = Path(__file__).resolve().parent / "conversation_history.json"

# 日常/工作模式状态文件（AAA 与 GUI 共享的事实来源）
_MODE_FILE = Path(__file__).resolve().parent.parent.parent / "nodes" / "shared" / "mode.json"

# DSH 提问交互文件（node_dsh headless provider ↔ GUI，qid 精确匹配）
_QUESTION_FILE = Path(__file__).resolve().parent.parent.parent / "nodes" / "shared" / "dsh_question_in.json"
_ANSWER_FILE = Path(__file__).resolve().parent.parent.parent / "nodes" / "shared" / "dsh_answer_out.json"


def _atomic_write_json(path: Path, data: dict) -> bool:
    """原子写共享协议文件（tmp + replace，规范 2.5）"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        return False


class _QuestionCard(QWidget):
    """DSH 提问卡片 — 问题正文 + 选项按钮（单选/多选）+ 自由输入 + 提交。

    提交后把答案原子写 dsh_answer_out.json（qid 精确匹配），并以 answered 信号
    回调 chat_page 把回答追加为用户气泡。回答后禁用交互，标注「已回答」。
    """

    answered = Signal(str)

    def __init__(self, qid: str, questions: list[dict], parent=None):
        super().__init__(parent)
        self._qid = qid
        self._questions = questions
        self._option_groups: list[list[QPushButton]] = [[] for _ in questions]  # 每问题单选按钮组（按 questions 索引对齐）
        self._option_checks: list[list[QCheckBox]] = [[] for _ in questions]   # 每问题多选按钮组（按 questions 索引对齐）
        self._input_fields: list[QLineEdit] = []
        self._submit_btn: QPushButton | None = None

        colors = AppConfig().get_all_colors()
        self.setObjectName("questionCard")
        self.setStyleSheet(f"""
            #questionCard {{
                background-color: {colors['bubble_ai_bg']};
                border: 1px solid {colors['border_color']};
                border-radius: 10px;
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        title = QLabel("DSH 需要确认")
        title.setStyleSheet(
            f"font-weight: bold; font-size: 14px; color: {colors['text_primary']};")
        outer.addWidget(title)

        for idx, q in enumerate(questions):
            q_box = QVBoxLayout()
            q_box.setSpacing(6)
            header = str(q.get("header") or "").strip()
            if header:
                h_lbl = QLabel(header)
                h_lbl.setStyleSheet(
                    f"font-weight: bold; font-size: 12px; color: {colors['text_secondary']};")
                q_box.addWidget(h_lbl)
            body = QLabel(str(q.get("question") or ""))
            body.setWordWrap(True)
            body.setStyleSheet(f"font-size: 13px; color: {colors['text_primary']};")
            q_box.addWidget(body)

            options = q.get("options") or []
            multi = bool(q.get("multiSelect"))
            if options:
                row = QHBoxLayout()
                row.setSpacing(8)
                if multi:
                    checks = []
                    for opt in options:
                        cb = QCheckBox(str(opt.get("label") or ""))
                        cb.setStyleSheet(f"font-size: 13px; color: {colors['text_primary']};")
                        cb.setToolTip(str(opt.get("description") or ""))
                        checks.append(cb)
                        row.addWidget(cb)
                    self._option_checks[idx] = checks
                else:
                    grp = QButtonGroup(self)
                    grp.setExclusive(True)
                    btns = []
                    for i, opt in enumerate(options):
                        btn = QPushButton(str(opt.get("label") or ""))
                        btn.setCheckable(True)
                        btn.setChecked(i == 0)
                        btn.setToolTip(str(opt.get("description") or ""))
                        btn.setCursor(Qt.CursorShape.PointingHandCursor)
                        btn.setStyleSheet(f"""
                            QPushButton {{
                                background-color: transparent;
                                color: {colors['text_primary']};
                                border: 1px solid {colors['border_color']};
                                border-radius: 6px;
                                padding: 3px 12px; font-size: 13px;
                            }}
                            QPushButton:hover {{
                                background-color: {colors['bg_chat']};
                            }}
                            QPushButton:checked {{
                                background-color: {colors['accent_color']};
                                color: #ffffff;
                                border-color: {colors['accent_color']};
                            }}
                        """)
                        grp.addButton(btn)
                        btns.append(btn)
                        row.addWidget(btn)
                    self._option_groups[idx] = btns
                q_box.addLayout(row)

            inp = QLineEdit()
            inp.setPlaceholderText("补充说明（可选）")
            inp.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {colors['bg_chat']};
                    color: {colors['text_primary']};
                    border: 1px solid {colors['border_color']};
                    border-radius: 6px;
                    padding: 4px 8px; font-size: 13px;
                }}
            """)
            self._input_fields.append(inp)
            q_box.addWidget(inp)
            outer.addLayout(q_box)

        self._submit_btn = QPushButton("提交回答")
        self._submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._submit_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {colors['accent_color']};
                color: #ffffff;
                border: none; border-radius: 6px;
                padding: 5px 18px; font-size: 13px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {colors['accent_hover']}; }}
        """)
        self._submit_btn.clicked.connect(self._on_submit)
        outer.addWidget(self._submit_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _on_submit(self):
        answers = []
        text_parts = []
        for idx, q in enumerate(self._questions):
            selected: list[str] = []
            if q.get("options"):
                if q.get("multiSelect"):
                    checks = self._option_checks[idx]
                    selected = [cb.text() for cb in checks if cb.isChecked()]
                else:
                    btns = self._option_groups[idx]
                    selected = [b.text() for b in btns if b.isChecked()]
            custom = self._input_fields[idx].text().strip()
            answers.append({
                "id": str(q.get("id") or ""),
                "selected": selected,
                "custom": custom or None,
            })
            if selected:
                text_parts.append("、".join(selected))
            if custom:
                text_parts.append(custom)
        if not _atomic_write_json(_ANSWER_FILE, {
            "qid": self._qid,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "answers": answers,
        }):
            return
        answer_text = "、".join(text_parts) if text_parts else "（已选择）"
        self.answered.emit(answer_text)
        # 提交后锁定交互
        for group in self._option_groups:
            for b in group:
                b.setEnabled(False)
        for checks in self._option_checks:
            for cb in checks:
                cb.setEnabled(False)
        for inp in self._input_fields:
            inp.setEnabled(False)
        if self._submit_btn:
            self._submit_btn.setText("已回答 ✓")
            self._submit_btn.setEnabled(False)


class ChatPage(QWidget):
    """聊天页 — 消息列表 + ChatInput 输入栏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = AppState()
        self._config = AppConfig()
        self._msg_mgr: MessageManager | None = None
        self._current_ai_bubble: ChatBubble | None = None  # 当前正在 append 的 AI 气泡
        self._waiting_bubble: QWidget | None = None  # 等待指示气泡（AI/DSH 处理中）
        self._waiting_label: QLabel | None = None    # 等待气泡的状态文字
        self._conversation_messages: dict[str, list[tuple[str, str]]] = {}  # conv_id -> [(role, text)]
        self._prev_conv_id: str = ""  # 切换前记录旧对话 id
        self._pending_reply_conv_id: str = ""  # 当前发送消息所属对话 id（回复路由用）
        self._processed_qids: set[str] = set()  # 已渲染的 DSH 提问 qid（判新）

        # 打字机效果状态
        self._typing_timer: QTimer | None = None
        self._typing_text: str = ""
        self._typing_index: int = 0

        # 从历史文件恢复对话状态
        self._load_history()

        self._init_ui()
        # 记录初始对话 id，供切换时保存使用
        self._prev_conv_id = self._state.current_conversation_id
        self._connect_signals()
        # 加载当前对话的气泡
        self._load_conversation_messages(self._state.current_conversation_id)

        # 阶段4：自查订阅主题变更消息（替代 MainWindow 直接调用）
        self._subscribe_messages()

    # ─── 消息订阅（阶段4） ──────────────────────

    def _subscribe_messages(self):
        """订阅关心的 UI 消息（幂等，防重复实例化重复订阅）"""
        if getattr(self, "_events_subscribed", False):
            return
        self._events_subscribed = True
        event_bus.subscribe(THEME_CHANGED, self._on_theme_changed_msg)

    def _on_theme_changed_msg(self, _data=None):
        if hasattr(self, "refresh_bubble_themes"):
            self.refresh_bubble_themes()
        if hasattr(self, "refresh_input_bar"):
            self.refresh_input_bar()

    def set_message_manager(self, msg_mgr: MessageManager):
        """设置 MessageManager 实例（由 MainWindow 传入）"""
        self._msg_mgr = msg_mgr
        if self._msg_mgr:
            self._msg_mgr.reply_received.connect(self._on_reply)
            self._msg_mgr.error_occurred.connect(self._on_error)

    def _init_ui(self):
        # 外层水平布局：对话列表 + 聊天区（带右侧留白）
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ─── 对话列表（左侧 240px）─────────
        self._conv_list = ConversationList()
        self._conv_list.conversation_selected.connect(self._on_conversation_changed)
        outer.addWidget(self._conv_list)

        # 中间内容容器（聊天面板）
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)

        colors = self._config.get_all_colors()

        # 页面背景色（QPalette 方式，比 QSS 类选择器更可靠）
        p = self.palette()
        p.setColor(QPalette.Window, QColor(colors['bg_chat']))
        self.setPalette(p)
        self.setAutoFillBackground(True)

        # ─── 消息列表滚动区域 ──────────────────────────
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setObjectName("chat_scroll")
        self._scroll_area.setStyleSheet(f"""
            QScrollArea#chat_scroll {{ background-color: {colors['bg_chat']}; border: none; }}
        """)

        # 消息列表容器（气泡从下往上堆叠，类似微信）
        self._msg_container = QWidget()
        self._msg_container.setObjectName("msg_container")
        self._msg_container.setStyleSheet(f"""
            #msg_container {{ background-color: {colors['bg_chat']}; }}
        """)
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(0, 0, 0, 0)
        self._msg_layout.setSpacing(8)
        self._msg_layout.addStretch(1)  # 弹簧在最底部

        # ─── 顶部模式栏（P2：日常/工作切换）────────
        mode_bar = QWidget()
        mode_bar_layout = QHBoxLayout(mode_bar)
        mode_bar_layout.setContentsMargins(12, 6, 12, 2)
        mode_bar_layout.setSpacing(8)
        self._mode_btn = QPushButton()
        self._mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mode_btn.clicked.connect(self._on_mode_toggle)
        mode_bar_layout.addWidget(self._mode_btn)
        mode_bar_layout.addStretch()
        inner_layout.addWidget(mode_bar)

        self._scroll_area.setWidget(self._msg_container)
        inner_layout.addWidget(self._scroll_area, 1)

        # ─── ChatInput（WeChat 风格发送框）───────────
        self._chat_input = ChatInput()
        self._chat_input.send_requested.connect(self._send_message)
        inner_layout.addWidget(self._chat_input)

        outer.addWidget(inner)

        # 右侧留白（5%）
        right_spacer = QWidget()
        right_spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        outer.addWidget(right_spacer)

        # 比例：对话列表固定 240px, 聊天区按比例
        outer.setStretch(0, 0)   # ConversationList 固定宽度
        outer.setStretch(1, 90)  # 聊天区
        outer.setStretch(2, 5)   # 右侧留白

        # 初始化模式按钮状态 + 定时同步（AAA 关键词自动切换后 GUI 同步显示）
        self._update_mode_btn(self._read_mode())
        self._mode_sync_timer = QTimer(self)
        self._mode_sync_timer.setInterval(1000)
        self._mode_sync_timer.timeout.connect(self._sync_mode_btn)
        self._mode_sync_timer.start()

        # DSH 提问轮询（node_dsh provider 写 dsh_question_in.json → GUI 渲染提问卡片）
        self._question_poll_timer = QTimer(self)
        self._question_poll_timer.setInterval(1000)
        self._question_poll_timer.timeout.connect(self._poll_question)
        self._question_poll_timer.start()

    def _connect_signals(self):
        self._state.on_change("send_state", self._on_send_state_changed)
        self._conv_list.conversation_deleted.connect(self._on_conversation_deleted)

    # ─── 日常/工作模式切换（P2）──────────────────

    def _read_mode(self) -> str:
        """读取当前模式（nodes/shared/mode.json），默认 daily"""
        try:
            if _MODE_FILE.is_file():
                data = json.loads(_MODE_FILE.read_text(encoding="utf-8"))
                mode = str(data.get("mode", "")).strip()
                if mode in ("daily", "work"):
                    return mode
        except Exception:
            pass
        return "daily"

    def _write_mode(self, mode: str) -> bool:
        """原子写模式状态（临时文件 + replace）"""
        try:
            _MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = _MODE_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"mode": mode}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(_MODE_FILE)
            return True
        except OSError:
            return False

    def _mode_btn_style(self, mode: str) -> str:
        colors = self._config.get_all_colors()
        if mode == "work":
            bg, fg = colors.get("accent_color", "#4f8cff"), "#ffffff"
        else:
            bg, fg = colors.get("bg_primary", "#f2f3f5"), colors.get("text_primary", "#1f2329")
        return f"""
            QPushButton {{
                background-color: {bg}; color: {fg};
                border: none; border-radius: 6px;
                padding: 4px 14px; font-size: 13px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {bg}; }}
        """

    def _update_mode_btn(self, mode: str):
        self._current_mode = mode
        self._mode_btn.setText("工作模式" if mode == "work" else "日常模式")
        self._mode_btn.setToolTip(
            "工作模式：输入直通 DSH 执行（不走 AI 对话判断）；日常模式：正常对话。"
            "点击切换，也可在对话中说「进入工作模式/退出工作模式」。")
        self._mode_btn.setStyleSheet(self._mode_btn_style(mode))

    def _sync_mode_btn(self):
        """定时同步按钮状态（关键词自动切换后 GUI 保持一致）"""
        mode = self._read_mode()
        if mode != getattr(self, "_current_mode", ""):
            self._update_mode_btn(mode)

    def _on_mode_toggle(self):
        nxt = "work" if self._read_mode() == "daily" else "daily"
        if self._write_mode(nxt):
            self._update_mode_btn(nxt)

    # ─── DSH 提问回 GUI（node_dsh provider ↔ 本页）────────

    def _poll_question(self):
        """轮询 dsh_question_in.json：新 qid → 渲染提问卡片（判新用已处理 qid 集）"""
        try:
            if not _QUESTION_FILE.is_file():
                return
            data = json.loads(_QUESTION_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        qid = str(data.get("qid") or "").strip()
        questions = data.get("questions")
        if not qid or qid in self._processed_qids or not isinstance(questions, list) or not questions:
            return
        self._processed_qids.add(qid)
        self._append_question_card(qid, questions)

    def _append_question_card(self, qid: str, questions: list[dict]):
        """把 DSH 提问卡片插入消息流（AI 侧左对齐，微信风）"""
        card = _QuestionCard(qid, questions)
        card.answered.connect(self._on_question_answered)
        count = self._msg_layout.count()
        self._msg_layout.insertWidget(count - 1, card)
        self._msg_layout.setAlignment(card, Qt.AlignmentFlag.AlignLeft)
        self._msg_container.updateGeometry()
        self._scroll_to_bottom()

    def _on_question_answered(self, text: str):
        """用户已提交 DSH 提问回答 → 回答入会话（用户气泡）+ 持久化"""
        self._append_bubble(f"（回答 DSH 提问）{text}", "user")
        if self._state.current_conversation_id:
            self._save_current_messages(self._state.current_conversation_id)

    # ─── 对话切换 ────────────────────────────────

    def _on_conversation_changed(self, conv_id: str):
        """切换对话 — 保存当前消息（用旧 id），加载目标对话消息"""
        self._cancel_typing()  # 取消打字动画
        self._hide_waiting()  # 移除等待指示（回复将路由到目标对话）
        # 用 _prev_conv_id 保存当前消息（state.current 已被覆盖）
        if self._prev_conv_id:
            self._save_current_messages(self._prev_conv_id)
        # 重置发送状态锁，使新对话可以立即发送（旧对话的回复不再绑定当前 GUI）
        self._state.send_state = "idle"
        if self._msg_mgr:
            self._msg_mgr.cancel_ongoing()
            self._msg_mgr.send_switch_conversation(conv_id)
        # 清除显示
        self.clear_messages()
        # 记录新 id 供下次切换使用
        self._prev_conv_id = conv_id
        # 加载目标对话的消息
        self._load_conversation_messages(conv_id)
        self._current_ai_bubble = None

    def _on_conversation_deleted(self, conv_id: str):
        """对话被删除 → 清理消息缓存"""
        self._conversation_messages.pop(conv_id, None)
        self._save_history()

    def _save_current_messages(self, conv_id: str):
        """将当前气泡保存到内存字典 + 持久化文件"""
        if not conv_id:
            return
        messages = []
        for i in range(self._msg_layout.count()):
            item = self._msg_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), ChatBubble):
                messages.append((item.widget().role, item.widget()._text))
        if messages:
            self._conversation_messages[conv_id] = messages
        self._save_history()

    def _load_conversation_messages(self, conv_id: str):
        """从内存字典加载指定对话的消息"""
        messages = self._conversation_messages.get(conv_id, [])
        for role, text in messages:
            self._append_bubble(text, role)
        self._scroll_to_bottom()

    # ─── 持久化 ────────────────────────────────

    def _save_history(self):
        """将对话消息 + 对话列表元数据写入 JSON 文件"""
        try:
            data: dict = {
                "current_conv_id": self._state.current_conversation_id,
                "convs": {},
                "archived_convs": {},
            }
            # 活跃对话
            for conv in self._state.conversations:
                cid = conv["id"]
                data["convs"][cid] = {
                    "name": conv.get("name", "新对话"),
                    "last_message": conv.get("last_message", ""),
                    "timestamp": conv.get("timestamp", 0),
                    "messages": self._conversation_messages.get(cid, []),
                }
            # 归档对话
            for conv in self._state.archived_conversations:
                cid = conv["id"]
                data["archived_convs"][cid] = {
                    "name": conv.get("name", "新对话"),
                    "last_message": conv.get("last_message", ""),
                    "timestamp": conv.get("timestamp", 0),
                    "messages": self._conversation_messages.get(cid, []),
                }
            with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[ChatPage] 保存对话历史失败: {e}")

    def _load_history(self):
        """从 JSON 文件恢复对话消息 + 对话列表 + 归档"""
        if not _HISTORY_FILE.exists():
            return
        try:
            with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[ChatPage] 加载对话历史失败: {e}")
            return

        # 恢复活跃对话
        raw_convs = data.get("convs", {})
        restored = []
        for cid, info in raw_convs.items():
            restored.append({
                "id": cid,
                "name": info.get("name", "新对话"),
                "last_message": info.get("last_message", ""),
                "timestamp": info.get("timestamp", 0),
            })
            msgs = info.get("messages", [])
            if msgs:
                self._conversation_messages[cid] = [(r, t) for r, t in msgs]

        if restored:
            self._state.conversations = restored

        # 恢复归档对话
        raw_archived = data.get("archived_convs", {})
        archived_restored = []
        for cid, info in raw_archived.items():
            archived_restored.append({
                "id": cid,
                "name": info.get("name", "新对话"),
                "last_message": info.get("last_message", ""),
                "timestamp": info.get("timestamp", 0),
            })
            msgs = info.get("messages", [])
            if msgs:
                self._conversation_messages[cid] = [(r, t) for r, t in msgs]

        if archived_restored:
            self._state.archived_conversations = archived_restored

        # 恢复当前对话 ID
        cur = data.get("current_conv_id", "")
        all_convs = restored + archived_restored
        if cur and any(c["id"] == cur for c in all_convs):
            self._state.current_conversation_id = cur
        elif restored:
            self._state.current_conversation_id = restored[0]["id"]

    # ─── 发送 ──────────────────────────────────

    def _send_message(self, text: str, attachments: list):
        if not self._msg_mgr:
            return

        self._cancel_typing()  # 取消正在进行的打字动画
        self._current_ai_bubble = None  # 发送新消息时重置当前 AI 气泡
        self._append_bubble(text, "user")

        # 自动生成标题：首条消息时取前 20 字作为对话名
        conv_id = self._state.current_conversation_id
        conv = self._state.get_conversation(conv_id)
        if conv and conv.get("name", "") in ("新对话", ""):
            title = text[:20].strip()
            if len(text) > 20:
                title += "…"
            if title:
                conv["name"] = title

        # 保存用户消息到内存字典
        self._save_current_messages(conv_id)

        # 记录回复目标对话，用于异步回复路由
        self._pending_reply_conv_id = conv_id

        # 如果有附件，在气泡下方显示附件信息
        for att in attachments:
            att_text = f"[{'图片' if att['type'] == 'image' else '文件'}] {att['name']}"
            self._append_bubble(att_text, "user")

        # 更新对话预览
        self._state.update_conversation_preview(
            self._state.current_conversation_id, text
        )

        ok = self._msg_mgr.send_text(text, attachments)
        if not ok:
            pass
        # 发送成功 → 显示等待指示（AI 处理中）；收到正式回复时移除
        self._show_waiting("AI 思考中…")

    def _on_send_state_changed(self, state: str):
        if state == "sending":
            self._chat_input.set_enabled(False)
        else:
            self._chat_input.set_enabled(True)
            self._chat_input.set_focus()

    # ─── 接收回复（逐字打字机效果） ─────────────

    def append_reply(self, text: str):
        """MainWindow 调用此方法添加 AI 回复"""
        text = self._strip_mood_tag(text)
        self._start_typing(text)

    def _on_reply(self, text: str, pending: bool = False):
        """收到 AI 回复 → 去掉情绪标签 → 路由到正确对话。

        pending=True（工作模式 DSH 回执）：显示回执文本后保持等待指示，
        直到最终结果到达（pending=False）才移除。
        """
        text = self._strip_mood_tag(text)
        if not text:
            return

        # 如果用户已切换到其他对话，将回复直接保存到目标对话缓存
        target = self._pending_reply_conv_id
        self._pending_reply_conv_id = ""  # 消费完毕，清空
        if target and target != self._state.current_conversation_id:
            msgs = self._conversation_messages.get(target, [])
            msgs.append(("ai", text))
            self._conversation_messages[target] = msgs
            self._save_history()
            return

        if not pending:
            self._hide_waiting()
        self._start_typing(text)
        if pending:
            self._show_waiting("DSH 正在执行中…")

    def _start_typing(self, text: str):
        """开始逐字输出"""
        self._cancel_typing()
        # 创建空气泡
        self._current_ai_bubble = self._append_bubble("", "ai")
        # 准备打字
        self._typing_text = text
        self._typing_index = 0
        self._typing_timer = QTimer(self)
        self._typing_timer.setInterval(_TYPING_INTERVAL_MS)
        self._typing_timer.timeout.connect(self._type_next_char)
        self._typing_timer.start()

    def _type_next_char(self):
        """打字机定时器回调：输出下一个字符"""
        if self._typing_index >= len(self._typing_text) or not self._current_ai_bubble:
            # 打字完成 → 保存 AI 回复到内存字典
            if self._state.current_conversation_id:
                self._save_current_messages(self._state.current_conversation_id)
            self._cancel_typing()
            return

        char = self._typing_text[self._typing_index]
        self._typing_index += 1
        self._current_ai_bubble.append_text(char)
        self._scroll_to_bottom()

    def _cancel_typing(self):
        """取消打字动画"""
        if self._typing_timer:
            self._typing_timer.stop()
            self._typing_timer = None
        self._typing_text = ""
        self._typing_index = 0

    def _on_error(self, msg: str):
        self._hide_waiting()
        self._append_bubble(f"[错误] {msg}", "ai")

    # ─── 等待指示气泡 ──────────────────────────

    def _show_waiting(self, text: str):
        """显示等待指示气泡（转圈动画 + 状态文字）；已存在则只更新文字"""
        if self._waiting_bubble is not None:
            if self._waiting_label is not None:
                self._waiting_label.setText(text)
            self._scroll_to_bottom()
            return
        colors = AppConfig().get_all_colors()
        bubble = QWidget()
        bubble.setObjectName("waitingBubble")
        bubble.setStyleSheet(f"""
            #waitingBubble {{
                background-color: {colors['bubble_ai_bg']};
                border: 1px solid {colors['border_color']};
                border-radius: 10px;
            }}
        """)
        lay = QHBoxLayout(bubble)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)
        bar = QProgressBar(bubble)
        bar.setRange(0, 0)  # 不确定模式：自带动画转圈
        bar.setFixedSize(16, 16)
        bar.setTextVisible(False)
        bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: transparent;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {colors['accent']};
                border-radius: 3px;
            }}
        """)
        self._waiting_label = QLabel(text)
        self._waiting_label.setStyleSheet(
            f"color: {colors['text_secondary']}; font-size: 12px;")
        lay.addWidget(bar)
        lay.addWidget(self._waiting_label)
        count = self._msg_layout.count()
        self._msg_layout.insertWidget(count - 1, bubble)
        self._msg_layout.setAlignment(bubble, Qt.AlignmentFlag.AlignLeft)
        self._waiting_bubble = bubble
        self._scroll_to_bottom()

    def _hide_waiting(self):
        """移除等待指示气泡"""
        if self._waiting_bubble is not None:
            self._msg_layout.removeWidget(self._waiting_bubble)
            self._waiting_bubble.deleteLater()
            self._waiting_bubble = None
            self._waiting_label = None

    @staticmethod
    def _strip_mood_tag(text: str) -> str:
        """去除 AAA 注入的情绪标签 <xxx>（支持中英文），保留后续文本"""
        import re
        # \w 不匹配中文，改用 [^>]+ 匹配尖括号内任意非 > 字符
        return re.sub(r'^<[^>]+>', '', text).strip()

    # ─── 气泡管理 ──────────────────────────────

    def _append_bubble(self, text: str, role: str):
        bubble = ChatBubble(text, role)
        # 插入到 stretch 之前（最新消息在最下面）
        count = self._msg_layout.count()
        self._msg_layout.insertWidget(count - 1, bubble)
        # 设置对齐：用户右对齐，AI左对齐
        alignment = Qt.AlignmentFlag.AlignRight if role == "user" else Qt.AlignmentFlag.AlignLeft
        self._msg_layout.setAlignment(bubble, alignment)

        # 强制刷新布局
        self._msg_container.updateGeometry()
        self._scroll_area.updateGeometry()
        self.updateGeometry()

        # 立即滚动到底部
        self._scroll_to_bottom()
        return bubble

    def _scroll_to_bottom(self):
        """事件队列处理完成后滚动到底部（确保布局已生效）"""
        QTimer.singleShot(0, lambda: self._scroll_area.verticalScrollBar().setValue(
            self._scroll_area.verticalScrollBar().maximum()
        ))

    def refresh_bubble_themes(self):
        """主题变更后刷新所有已有气泡的颜色"""
        for i in range(self._msg_layout.count()):
            item = self._msg_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), ChatBubble):
                item.widget()._apply_theme()

    def refresh_input_bar(self):
        """主题变更后刷新输入栏样式及对话列表"""
        colors = self._config.get_all_colors()
        # 刷新页面背景（QPalette）
        p = self.palette()
        p.setColor(QPalette.Window, QColor(colors['bg_chat']))
        self.setPalette(p)
        self.setAutoFillBackground(True)
        # 刷新消息容器背景
        msg_container = self.findChild(QWidget, "msg_container")
        if msg_container:
            msg_container.setStyleSheet(f"""
                #msg_container {{ background-color: {colors['bg_chat']}; }}
            """)
        # 刷新 ChatInput 样式
        if self._chat_input:
            self._chat_input._apply_styles()
        # 刷新滚动区域背景
        self._scroll_area.setStyleSheet(f"""
            QScrollArea#chat_scroll {{ background-color: {colors['bg_chat']}; border: none; }}
        """)
        # 刷新对话列表主题
        if self._conv_list:
            self._conv_list.refresh_theme()

    def clear_messages(self):
        """清除所有消息气泡"""
        while self._msg_layout.count() > 1:
            item = self._msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def resizeEvent(self, event):
        """窗口尺寸变化时确保滚动到最新消息"""
        super().resizeEvent(event)
        self._scroll_to_bottom()
