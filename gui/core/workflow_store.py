"""Workflow 流程库 + 双引擎评分（P1-1）— 流程 schema 化，多巴胺/用进废退评价回流。

双引擎设计（用户原创）：
- 多巴胺 = 显性反馈：流程级 bandit。用户外部评价（👍/👎）更新 Q 值（RPE 校准），
  选择流程用 UCB 公式（Q + 探索项）。需要归因（明确评价对象 = 某个流程）。
- 用进废退 = 隐性反馈：内部统计。按调用频次分位数修剪：调用多的前 p% 权重不变，
  调用少的后 q% 降权（不归零）。无需归因，持续累积。
- 最终分 = dopamine × use_score（外部评价优先仲裁的乘法模型）。

流程库存于 nodes/shared/workflows.json（共享文件，AAA 经工具桥消费，GUI 展示/执行）。
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from gui.core.event_bus import event_bus
from gui.core.messages import AI_EVENT

# 流程库文件（共享：GUI 读写 + 展示，AAA 经工具桥消费）
_SHARED_DIR = Path(__file__).resolve().parent.parent.parent / "nodes" / "shared"
_WORKFLOWS_FILE = _SHARED_DIR / "workflows.json"

# 双引擎参数
_DOPAMINE_ALPHA = 0.2          # Q 值学习率
_DOPAMINE_INIT = 0.5           # 初始 Q
_UCB_EXPLORE = 2.0             # 探索系数
_USE_PRUNING_EVERY = 5         # 每 N 次调用触发一次用进废退修剪
_USE_KEEP_TOP = 0.6            # 前 60% 权重不变
_USE_DECAY = 0.8               # 后 40% 降权系数（不归零）


@dataclass
class Workflow:
    """一个流程 = 有序工具步骤 + 双引擎分数"""

    id: str
    name: str
    description: str
    steps: list[dict] = field(default_factory=list)   # [{"tool": ..., "args": {...}}, ...]
    dopamine: float = _DOPAMINE_INIT
    use_score: float = 1.0
    calls: int = 0
    positive: int = 0
    negative: int = 0

    @property
    def final_score(self) -> float:
        """最终分 = 多巴胺 × 用进废退（外部评价优先仲裁）"""
        return round(self.dopamine * self.use_score, 3)


# 默认预置流程（首次无库时创建）
_DEFAULT_WORKFLOWS = [
    {
        "id": "skin_change",
        "name": "皮肤变更",
        "description": "用户请求 UI 皮肤/主题外观变更（如“换成紫色”“换个风格”）",
        "steps": [
            {"tool": "ui.create_skin_proposal",
             "args": {"name": "{{name}}", "tokens": "{{tokens}}",
                      "description": "由流程 skin_change 生成的皮肤包提案"}},
        ],
    },
    {
        "id": "navigate_page",
        "name": "页面导航",
        "description": "用户请求跳转到某个页面（如“打开设置”“去地图页”）",
        "steps": [
            {"tool": "ui.navigate_page", "args": {"page_id": "{{page_id}}"}},
        ],
    },
    {
        "id": "theme_switch",
        "name": "主题切换",
        "description": "用户请求切换主题预设（如“换成深色”）",
        "steps": [
            {"tool": "ui.apply_preset", "args": {"preset_id": "{{preset_id}}"}},
        ],
    },
]


class WorkflowStore:
    """流程库（单例）：持久化 + 双引擎算法 + 执行器"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._flows: dict[str, Workflow] = {}
        self._initialized = True
        _SHARED_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    # ─── 持久化 ──────────────────────────────────

    def _load(self):
        if not _WORKFLOWS_FILE.is_file():
            self._seed_defaults()
            return
        try:
            data = json.loads(_WORKFLOWS_FILE.read_text(encoding="utf-8"))
            for item in data:
                wf = Workflow(**{k: item.get(k) for k in Workflow.__dataclass_fields__})
                self._flows[wf.id] = wf
        except (json.JSONDecodeError, OSError, TypeError):
            self._seed_defaults()

    def _save(self):
        try:
            _WORKFLOWS_FILE.write_text(
                json.dumps([asdict(w) for w in self._flows.values()],
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _seed_defaults(self):
        self._flows = {d["id"]: Workflow(**d) for d in _DEFAULT_WORKFLOWS}
        self._save()

    # ─── 查询 ────────────────────────────────────

    def list(self) -> list[Workflow]:
        return list(self._flows.values())

    def get(self, flow_id: str) -> Workflow | None:
        return self._flows.get(flow_id)

    def summary(self) -> list[dict]:
        """JSON 化摘要（工具/展示用）"""
        return [
            {
                "id": w.id, "name": w.name, "description": w.description,
                "dopamine": round(w.dopamine, 3), "use_score": round(w.use_score, 3),
                "final_score": w.final_score, "calls": w.calls,
                "positive": w.positive, "negative": w.negative,
            }
            for w in self.list()
        ]

    # ─── 多巴胺：选择（UCB bandit） ──────────────

    def choose(self, query: str | None = None) -> Workflow | None:
        """按多巴胺 UCB 选择流程（query 可选：限定匹配描述的流程集）

        UCB = Q + sqrt(2·ln(N_total) / (n_flow + 1))——探索次数少的流程获得加成。
        """
        candidates = self.list()
        if query:
            candidates = [w for w in candidates
                          if query and query.lower() in w.description.lower()]
        if not candidates:
            return None
        n_total = sum(w.calls for w in self.list()) + 1
        best, best_ucb = None, -1.0
        for w in candidates:
            ucb = w.dopamine + _UCB_EXPLORE * math.sqrt(
                (2 * math.log(n_total)) / (w.calls + 1))
            if ucb > best_ucb:
                best, best_ucb = w, ucb
        return best

    # ─── 执行 ────────────────────────────────────

    def run(self, flow_id: str, overrides: dict | None = None) -> dict:
        """执行流程：依次调用步骤工具（{{占位符}} 由 overrides 填充）"""
        from gui.core.tool_registry import tool_registry

        wf = self.get(flow_id)
        if wf is None:
            return {"ok": False, "message": f"流程不存在: {flow_id}"}
        overrides = overrides or {}
        results = []
        for step in wf.steps:
            tool_name = step.get("tool", "")
            args = dict(step.get("args", {}))
            # 占位符填充 {{key}} → overrides[key]
            for k, v in list(args.items()):
                if isinstance(v, str) and v.startswith("{{") and v.endswith("}}"):
                    key = v[2:-2]
                    args[k] = overrides.get(key)
            outcome = tool_registry.execute(tool_name, args)
            results.append({"tool": tool_name, **outcome})
            if not outcome.get("ok"):
                self.record_use(flow_id)
                return {
                    "ok": False, "message": f"流程 {wf.name} 第 {len(results)} 步失败",
                    "data": {"flow_id": flow_id, "steps": results},
                }
        self.record_use(flow_id)
        return {
            "ok": True, "message": f"流程 {wf.name} 执行完成（{len(results)} 步）",
            "data": {"flow_id": flow_id, "steps": results},
        }

    # ─── 用进废退：隐性反馈 ──────────────────────

    def record_use(self, flow_id: str) -> None:
        """记录一次流程调用（用进废退计数，累计到阈值触发修剪）"""
        wf = self.get(flow_id)
        if wf is None:
            return
        wf.calls += 1
        total = sum(w.calls for w in self.list())
        if total > 0 and total % _USE_PRUNING_EVERY == 0:
            self.prune()
        self._save()

    def prune(self) -> None:
        """用进废退分位数修剪：按调用次数排序，后 q% 降权（不归零）"""
        flows = sorted(self.list(), key=lambda w: w.calls, reverse=True)
        keep_n = max(1, int(len(flows) * _USE_KEEP_TOP))
        for w in flows[keep_n:]:
            w.use_score = round(w.use_score * _USE_DECAY, 4)
        event_bus.publish(AI_EVENT, {
            "type": "workflow",
            "text": f"用进废退修剪：{len(flows) - keep_n} 个低频流程权重已降权",
        })

    # ─── 多巴胺：外部反馈（RPE 校准） ────────────

    def rate(self, flow_id: str, positive: bool) -> bool:
        """用户外部评价：更新流程 Q 值（多巴胺显性反馈，需归因到具体流程）

        positive: Q += α·(1−Q)；negative: Q += α·(0−Q)
        """
        wf = self.get(flow_id)
        if wf is None:
            return False
        target = 1.0 if positive else 0.0
        wf.dopamine = round(
            wf.dopamine + _DOPAMINE_ALPHA * (target - wf.dopamine), 4)
        if positive:
            wf.positive += 1
        else:
            wf.negative += 1
        self._save()
        event_bus.publish(AI_EVENT, {
            "type": "workflow",
            "text": f"用户评价流程「{wf.name}」：{'正面' if positive else '负面'}（多巴胺 {wf.dopamine:.2f}）",
        })
        return True


# 模块级单例
workflow_store = WorkflowStore()
