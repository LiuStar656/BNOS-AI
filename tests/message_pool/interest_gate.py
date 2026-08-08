# -*- coding: utf-8 -*-
"""兴趣门控（消息池 v7.0）：平台共享多语模型，编码一次、比对多次。

职责（对齐 [PLAN]-兴趣门控回复机制.md）：
    - 维护每个 Agent 的兴趣锚点（最近一次广播发言）与其向量缓存
    - 对一批消息做兴趣判定：sim(消息, 锚点) ≥ 阈值 → 过门（interest）；
      @ 点名 / reply_to 直接过门（direct）
    - 判定结果（检测文本 + 兴趣值 + 是否过门 + 原因）写入各 Agent 数据库
      interest_judgment 表（用户明确要求：检测文本和兴趣值入库）

设计要点：
    - 编码一次、比对多次：批内每条消息只编码一次（文本→向量缓存），
      同一批向量与全部 Agent 锚点做 numpy 点积
    - 模型懒加载 + 下载失败回退 + 可注入 encoder（验收测试用确定性伪编码器，
      不加载模型）
    - 无模型/无锚点时退化：全部过门（reason=no_model / no_anchor），
      平台行为退回 v6.6，保证门控异常不阻塞实验
"""
import os
import sqlite3

import numpy as np

# 阈值来自 v3 数据标定（[PLAN]-兴趣门控回复机制.md §三）：
# 真实接话 p25=0.499 / 基线 p90=0.701 → 中点 0.600
DEFAULT_THRESHOLD = 0.60
DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
FALLBACK_MODEL = "all-MiniLM-L6-v2"


class InterestGate:
    """平台进程内共享的兴趣门控器。"""

    def __init__(self, threshold=DEFAULT_THRESHOLD, model_name=DEFAULT_MODEL,
                 encoder=None):
        self.threshold = float(threshold)
        self._model_name = model_name
        self._encoder = encoder  # callable(list[str]) -> np.ndarray（归一化）
        self._model = None
        self._anchors: dict[str, dict] = {}  # agent_id -> {"text", "vec"}
        self._cache: dict[str, np.ndarray] = {}  # text -> vec（编码一次）
        self.encode_calls = 0  # 实际模型编码调用次数（验收/统计用）

    # ── 模型（懒加载 + 回退 + 可注入） ──────────────────────
    def _get_model(self):
        if self._model is None and self._encoder is None:
            try:
                # 离线加载本地缓存：避免 HF 联网检查（直连 huggingface.co
                # 超时 WinError 10060，卡住整个实验）；模型已用 hf-mirror.com
                # 镜像下载到 ~/.cache/huggingface/hub/
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
                os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
                from sentence_transformers import SentenceTransformer
                try:
                    self._model = SentenceTransformer(self._model_name)
                except Exception:
                    # 目标模型下载/加载失败 → 回退本地缓存英文模型（中文精度降级）
                    self._model = SentenceTransformer(FALLBACK_MODEL)
            except Exception:
                self._model = None  # sentence-transformers 不可用 → 退化模式
        return self._model

    def _has_encoder(self) -> bool:
        return self._encoder is not None or self._get_model() is not None

    def encode(self, texts: list[str]) -> np.ndarray:
        """编码文本列表（归一化向量）。同文本只编码一次（缓存）。

        Returns:
            (len(texts), dim) float64 数组，行已归一化。
        """
        fresh = [t for t in texts if t not in self._cache]
        if fresh:
            if self._encoder is not None:
                vecs = np.asarray(self._encoder(fresh), dtype="float64")
            else:
                model = self._get_model()
                if model is None:
                    raise RuntimeError("interest_gate 无可用编码器")
                vecs = np.asarray(
                    model.encode(fresh, normalize_embeddings=True),
                    dtype="float64")
            for t, v in zip(fresh, vecs):
                self._cache[t] = v
            self.encode_calls += 1
        return np.array([self._cache[t] for t in texts], dtype="float64")

    # ── 兴趣锚点 ─────────────────────────────────────────────
    def set_anchor(self, agent_id: str, text: str):
        """更新某 Agent 的兴趣锚点为最近一次广播发言（空文本忽略）。"""
        text = (text or "").strip()
        if not text:
            return
        self._anchors[agent_id] = {"text": text}

    def get_anchor(self, agent_id: str) -> str:
        return (self._anchors.get(agent_id) or {}).get("text", "")

    def _anchor_vec(self, agent_id: str):
        a = self._anchors.get(agent_id)
        if not a:
            return None
        if "vec" not in a:
            if not self._has_encoder():
                return None
            a["vec"] = self.encode([a["text"]])[0]
        return a["vec"]

    # ── 门控判定 ─────────────────────────────────────────────
    def judge(self, agent_id: str, msgs, direct_hits=None) -> dict:
        """（v7.2 前语义，保留兼容）对单个 agent 判定本批兴趣，返回单条判定。"""
        res = self.judge_sequence(agent_id, msgs, direct_hits=direct_hits)
        if res["target"] is not None:
            return res["target"]
        if res["records"]:
            return res["records"][0]
        return {"seq": 0, "detected_text": "", "anchor_text": res["anchor_text"],
                "interest_value": 0.0, "passed": True, "reason": "no_anchor"}

    def judge_sequence(self, agent_id: str, msgs, direct_hits=None) -> dict:
        """v7.2 接话切入判定：按时间从旧到新逐条发言判定，第一个过门的 = 接话切入点。

        Args:
            agent_id: 判定的 Agent
            msgs: 本批消息（Message 对象或 dict，须含 seq/user_id/content/reply_to）
            direct_hits: 批内直接命中消息（reply_to==agent 或被 @ 点名），
                可为空列表；命中则直接过门（reason=direct），切入点 = 命中消息

        Returns:
            {"records": [判定记录...],   # 每个候选发言者各一条（含 target_speaker）
             "target": 判定记录 | None,   # 过门的切入点（窗口上界 = target["seq"]）
             "anchor_text": anchor_text}
        """
        norm = []
        for m in msgs:
            if hasattr(m, "text"):
                norm.append({"seq": getattr(m, "seq", 0),
                             "user_id": m.user_id,
                             "content": m.text,
                             "reply_to": getattr(m, "reply_to", "")})
            else:
                norm.append({"seq": m.get("seq", 0),
                             "user_id": m.get("user_id", ""),
                             "content": m.get("content", ""),
                             "reply_to": m.get("reply_to", "")})
        anchor_text = self.get_anchor(agent_id)
        if not norm:
            return {"records": [], "target": None, "anchor_text": anchor_text}

        # 直接命中 → reason=direct，切入点 = 命中消息（兴趣值仍算，供采集）
        if direct_hits:
            hit = direct_hits[0]
            seq = hit.seq if hasattr(hit, "seq") else hit.get("seq", 0)
            text = hit.text if hasattr(hit, "text") else hit.get("content", "")
            val = 0.0
            a_v = self._anchor_vec(agent_id)
            if a_v is not None and text.strip():
                try:
                    val = float(self.encode([text])[0] @ a_v)
                except Exception:
                    val = 0.0
            rec = {"seq": seq, "detected_text": text,
                   "anchor_text": anchor_text,
                   "interest_value": round(val, 4),
                   "passed": True, "reason": "direct",
                   "target_speaker": hit.user_id if hasattr(hit, "user_id")
                   else hit.get("user_id", "")}
            return {"records": [rec], "target": rec, "anchor_text": anchor_text}

        # 无编码能力 / 无锚点 → 退化：全过门（保证实验不因门控异常中断）
        if not self._has_encoder() or self._anchor_vec(agent_id) is None:
            reason = "no_model" if not self._has_encoder() else "no_anchor"
            first = norm[0]
            rec = {"seq": first["seq"], "detected_text": first["content"],
                   "anchor_text": anchor_text, "interest_value": 0.0,
                   "passed": True, "reason": reason,
                   "target_speaker": first["user_id"]}
            return {"records": [rec], "target": rec, "anchor_text": anchor_text}

        a_v = self._anchor_vec(agent_id)
        # 候选序列 = 批内全部消息按时间从旧到新逐条判定（不去重：每条发言都是
        # 独立判定对象——3 对最早的第一条判定过没过门，次早的第二条，1 回复
        # 形成的第三条……逐个过门，第一个过门的 = 接话切入点）
        cands = sorted(norm, key=lambda x: x["seq"])
        # 对每个候选计算兴趣（编码一次：全部候选文本）
        texts = [c["content"] for c in cands]
        vecs = self.encode(texts)
        sims = vecs @ a_v
        records, target = [], None
        for c, sim in zip(cands, sims):
            val = float(sim)
            passed = val >= self.threshold
            rec = {"seq": c["seq"], "detected_text": c["content"],
                   "anchor_text": anchor_text,
                   "interest_value": round(val, 4),
                   "passed": bool(passed),
                   "reason": "interest" if passed else "none",
                   "target_speaker": c["user_id"] or "匿名"}
            records.append(rec)
            if passed and target is None:  # 从旧到新第一个过门 = 接话切入点
                target = rec
        return {"records": records, "target": target, "anchor_text": anchor_text}

    # ── 判定落库（用户要求：检测文本 + 兴趣值写入数据库） ──────
    _TABLE_SQL = """CREATE TABLE IF NOT EXISTS interest_judgment(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        identity_key TEXT NOT NULL DEFAULT 'gui:default',
        round_no INTEGER,
        message_seq INTEGER,
        detected_text TEXT,
        anchor_text TEXT,
        interest_value REAL,
        passed INTEGER,
        reason TEXT,
        created_at TEXT NOT NULL DEFAULT(datetime('now','localtime')))"""

    def write_judgment(self, db_path: str, identity_key: str, round_no,
                       judgment: dict):
        """把一次向量判定写入 Agent 数据库 interest_judgment 表。

        平台进程直接写（判定发生在 LLM 决策之前，与 AAA 子进程写库时序
        串行）；busy_timeout=3s 兜底并发锁。
        """
        try:
            conn = sqlite3.connect(db_path, timeout=3.0)
            try:
                conn.execute(self._TABLE_SQL)
                conn.execute(
                    "INSERT INTO interest_judgment(identity_key, round_no, "
                    "message_seq, detected_text, anchor_text, interest_value, "
                    "passed, reason) VALUES(?,?,?,?,?,?,?,?)",
                    (identity_key, round_no, judgment.get("seq"),
                     judgment.get("detected_text", ""),
                     judgment.get("anchor_text", ""),
                     judgment.get("interest_value", 0.0),
                     1 if judgment.get("passed") else 0,
                     judgment.get("reason", "")))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass  # 判定落库失败不阻塞实验（数据尽力而为）
