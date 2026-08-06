# [PLAN] AI 定位信息功能开发方案

> 日期：2026-08-07 | 版本：v1.1 | 状态：[PLAN]
> 设计文档：`[PLAN]-AI定位信息功能设计方案.md`、`[PLAN]-AI世界感知记忆系统设计方案.md`
> 优先级：Top 1（性价比 11.43，工作量 0.35 天）
> 架构归属：AAA 认知节点（`nodes/node_python_aaa_cognition/`），与 `memos.py`、`diary.py` 并列

---

## 目录

- [一、需求定位](#一需求定位)
- [二、开发架构总览](#二开发架构总览)
- [三、模块实现方案](#三模块实现方案)
  - [3.1 定位模块（location.py）](#31-定位模块locationpy)
  - [3.2 数据持久化逻辑](#32-数据持久化逻辑)
  - [3.3 Prompt 集成](#33-prompt-集成)
  - [3.4 GUI 可视化模块](#34-gui-可视化模块)
- [四、数据库设计](#四数据库设计)
- [五、API 接口清单](#五api-接口清单)
- [六、与现有架构的对接点](#六与现有架构的对接点)
- [七、开发步骤与时间线](#七开发步骤与时间线)
- [八、验收标准](#八验收标准)
- [九、测试方案](#九测试方案)
- [十、风险与降级策略](#十风险与降级策略)

---

## 一、需求定位

### 1.1 功能定义

为 BNOS AI 提供**当前地理位置感知能力**，使 AI 能够"知道自己在哪里"，并基于此提供本地化服务。定位模块归属 AAA 认知节点，作为 AI 世界感知能力的一部分。

### 1.2 核心能力矩阵

| 能力层级 | 功能 | 说明 | 优先级 |
|:--------:|------|------|:------:|
| **L1 基础** | IP 定位 | 通过公网 IP 获取城市级位置 | P0 |
| **L1 基础** | 位置存储 | 将定位结果持久化到数据库 | P0 |
| **L1 基础** | Prompt 注入 | 将位置信息注入 LLM 提示词 | P0 |
| **L2 增强** | 去重更新 | 位置不变时仅更新时间戳 | P1 |
| **L2 增强** | 地图可视化 | 在 GUI 中显示 AI 当前位置地图 | P1 |
| **L2 增强** | 轨迹查询 | 查询历史位置变化记录 | P1 |
| **L3 扩展** | 逆地理编码 | 将经纬度转为可读地址 | P2 |
| **L3 扩展** | 天气联动 | 自动获取当前位置天气 | P2 |

### 1.3 用户价值

- AI 回答"我在哪"时能说出城市名
- 天气/本地推荐等场景无需用户提供位置
- GUI 设置页可直观看到 AI 感知的位置

---

## 二、开发架构总览

### 2.1 系统架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                     BNOS AI 定位功能架构                              │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │  AAA 认知节点（node_python_aaa_cognition/）                     │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │ │
│  │  │  memos   │ │  diary   │ │  prompt   │ │  location │        │ │
│  │  │  .py     │ │  .py     │ │  .py      │ │  .py ★   │        │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └────┬─────┘        │ │
│  │                                               │                │ │
│  │                              ┌────────────────┴──────────────┐ │ │
│  │                              ▼                               ▼ │ │
│  │                     ┌──────────────┐               ┌──────────────┐ │ │
│  │                     │ LocationMgr  │               │build_location│ │ │
│  │                     │ 多源降级获取  │               │  _section() │ │ │
│  │                     └──────┬───────┘               └──────┬───────┘ │ │
│  │                            │                             │       │ │
│  │                            ▼                             ▼       │ │
│  │              ┌─────────────────────┐          ┌─────────────────────┐ │ │
│  │              │  nodes/shared/       │          │ 注入到 AAA Prompt   │ │ │
│  │              │  chatbot.db          │          │ (main.py 消费)     │ │ │
│  │              │  long_term_memory    │          └─────────────────────┘ │ │
│  │              │  entity='current_    │                                   │ │
│  │              │  location'           │                                   │ │
│  │              └─────────────────────┘                                   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                              │                                                │
│                              ▼                                                │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │  GUI 可视化层（gui/）                                                   │ │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐    │ │
│  │  │LocationMapWidget │  │  SettingsPanel   │  │  AppConfig      │    │ │
│  │  │ 静态地图图片     │  │  地理感知设置区   │  │  定位配置读写    │    │ │
│  │  └──────────────────┘  └──────────────────┘  └──────────────────┘    │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 模块组织说明

定位模块归属 AAA 认知节点，与其内部其他模块并列：

| 模块 | 文件路径 | 职责 |
|------|---------|------|
| **location.py ★** | `nodes/node_python_aaa_cognition/location.py` | **新增** - 定位获取 + 去重存储 + Prompt 段构建 |
| memos.py | `nodes/node_python_aaa_cognition/memos.py` | 语义记忆检索 |
| diary.py | `nodes/node_python_aaa_cognition/diary.py` | 日记功能 |
| prompt.py | `nodes/node_python_aaa_cognition/prompt.py` | Prompt 模板拼接（修改：增加位置段调用） |
| db.py | `nodes/node_python_aaa_cognition/db.py` | 数据库操作 |
| main.py | `nodes/node_python_aaa_cognition/main.py` | 节点主逻辑 |
| LocationMapWidget | `gui/widgets/location_map_widget.py` | GUI 地图显示组件（新增） |
| settings_panel.py | `gui/pages/settings_panel.py` | 设置面板（修改：集成地理感知区） |

### 2.3 技术选型

| 维度 | 选型 | 理由 |
|------|------|------|
| 定位源 | ip-api.com（主）+ ipapi.co + ip.sb（备） | 免费、无需 Key、城市级精度 |
| 地图显示 | 高德静态地图 API + OSM 兜底 | 有 Key 用高德，无 Key 用 OSM |
| 数据存储 | 复用 `long_term_memory` 表 | 零表结构变更，通过 entity 区分 |
| 网络请求 | `urllib.request` | Python 标准库，零新依赖 |
| GUI 框架 | 现有 PySide6 | 与项目一致 |

---

## 三、模块实现方案

### 3.1 定位模块（location.py）

#### 文件位置
```
nodes/node_python_aaa_cognition/location.py
```

> 与 `memos.py`、`diary.py`、`prompt.py` 并列，作为 AAA 节点的内部模块。

#### 模块结构总览

```python
# nodes/node_python_aaa_cognition/location.py
# 与 memos.py、diary.py 并列的 AAA 内部模块

import time
import json
import math
import sqlite3
import threading
import logging
import urllib.request
from dataclasses import dataclass
from typing import Optional, List, Dict


# ════════════════════════════════════════════════════════════════
#  GPSLocation 数据类
# ════════════════════════════════════════════════════════════════

@dataclass
class GPSLocation:
    latitude: float
    longitude: float
    accuracy: float          # 精度（米）
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    source: str = "free"
    timestamp: float = 0

    def to_dict(self) -> dict:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "accuracy": self.accuracy,
            "city": self.city,
            "region": self.region,
            "country": self.country,
            "source": self.source,
            "timestamp": self.timestamp or time.time()
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @property
    def is_fresh(self) -> bool:
        """位置信息是否在有效期内（5 分钟）"""
        return (time.time() - self.timestamp) < 300

    @property
    def accuracy_level(self) -> str:
        """精度等级描述"""
        if self.accuracy <= 100:
            return "精确位置"
        elif self.accuracy <= 1000:
            return "街区级别"
        return "城市级别"


# ════════════════════════════════════════════════════════════════
#  LocationResult 返回结构
# ════════════════════════════════════════════════════════════════

@dataclass
class LocationResult:
    success: bool
    location: Optional[GPSLocation] = None
    from_cache: bool = False
    stale: bool = False
    error: Optional[str] = None
```

#### LocationManager 类

```python
class LocationManager:
    """
    定位管理器（AAA 节点内部模块）

    特性：
    - 多源自动降级（3 个免费源轮换）
    - 5 分钟缓存 + 手动刷新
    - 去重存储（500m 内移动只更新时间戳）
    - 线程安全（RLock 保护）
    - 零新依赖（仅 Python 标准库）
    """

    # 配置常量
    DEFAULT_UPDATE_INTERVAL = 300   # 5 分钟自动更新
    MOVE_THRESHOLD = 500            # 500 米视为位置变化
    REQUEST_TIMEOUT = 5             # 网络请求超时

    # 免费定位源（按优先级排序）
    FREE_SOURCES = [
        {"name": "ip-api.com", "url": "http://ip-api.com/json/",  "parser": "_parse_ip_api"},
        {"name": "ipapi.co",   "url": "https://ipapi.co/json/",   "parser": "_parse_ipapi"},
        {"name": "ip.sb",      "url": "https://api.ip.sb/geoip",  "parser": "_parse_ip_sb"},
    ]

    def __init__(self, db_path: str, config: dict = None):
        self._db_path = db_path
        self._config = config or {}
        self._enabled = self._config.get("location_enabled", True)
        self._update_interval = self._config.get("location_update_interval", 300)
        self._identity_key = self._config.get("identity_key", "user_001")

        # 运行时状态
        self._current: Optional[GPSLocation] = None
        self._last_fetch_time: float = 0
        self._source_index: int = 0
        self._source_cooldown: dict = {}

        # 线程安全
        self._lock = threading.RLock()

        # 启动时加载缓存
        self._load_cached_location()

    # ── 公共接口 ──────────────────────────────────────────────

    def get_location(self, force_refresh: bool = False) -> LocationResult:
        """获取当前位置（多源自动降级）"""
        with self._lock:
            if not self._enabled:
                return LocationResult(success=False, error="定位功能已禁用")

            # 缓存有效性检查
            now = time.time()
            if not force_refresh and self._current:
                if (now - self._last_fetch_time) < self._update_interval:
                    return LocationResult(
                        success=True,
                        location=self._current,
                        from_cache=True
                    )

            # 尝试多源获取
            for _ in range(len(self.FREE_SOURCES)):
                source = self.FREE_SOURCES[self._source_index]
                location = self._fetch_from_source(source)
                self._source_index = (self._source_index + 1) % len(self.FREE_SOURCES)

                if location:
                    self._handle_location_update(location)
                    return LocationResult(success=True, location=location)

            # 全部失败 → 返回缓存
            if self._current:
                return LocationResult(
                    success=True,
                    location=self._current,
                    from_cache=True,
                    stale=True
                )
            return LocationResult(success=False, error="所有定位源均失败")

    def set_enabled(self, enabled: bool):
        """启用/禁用定位"""
        with self._lock:
            self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    def get_cached_location(self) -> Optional[GPSLocation]:
        """获取缓存位置（不触发网络请求）"""
        return self._current

    def get_location_history(self, limit: int = 20) -> list:
        """查询历史位置记录"""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT content, status, created_at
                    FROM long_term_memory
                    WHERE entity = 'current_location'
                      AND channel = 'location'
                      AND identity_key = ?
                    ORDER BY created_at DESC LIMIT ?
                """, (self._identity_key, limit))

                history = []
                for row in cursor.fetchall():
                    data = json.loads(row["content"])
                    history.append({
                        "lat": data["latitude"],
                        "lng": data["longitude"],
                        "city": data.get("city"),
                        "status": row["status"],
                        "time": row["created_at"]
                    })
                return history
        except Exception as e:
            logging.error(f"[Location] 查询历史失败: {e}")
            return []

    def clear_location_history(self) -> int:
        """清除历史记录，返回清除条数"""
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute("""
                    DELETE FROM long_term_memory
                    WHERE entity = 'current_location'
                      AND channel = 'location'
                      AND identity_key = ?
                """, (self._identity_key,))
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            logging.error(f"[Location] 清除历史失败: {e}")
            return 0

    # ── 内部实现 ──────────────────────────────────────────────

    def _fetch_from_source(self, source: dict) -> Optional[GPSLocation]:
        """从单个免费源获取定位"""
        last_attempt = self._source_cooldown.get(source["name"], 0)
        if (time.time() - last_attempt) < 1.0:
            return None

        self._source_cooldown[source["name"]] = time.time()

        try:
            req = urllib.request.Request(
                source["url"],
                headers={"User-Agent": "BNOS-AI/1.0 (+location-module)"}
            )
            response = urllib.request.urlopen(req, timeout=self.REQUEST_TIMEOUT)
            data = json.loads(response.read().decode("utf-8"))

            parser = getattr(self, source["parser"])
            return parser(data, source["name"])

        except Exception as e:
            logging.warning(f"[Location] {source['name']} 获取失败: {e}")
            return None

    def _parse_ip_api(self, data: dict, source_name: str) -> Optional[GPSLocation]:
        """解析 ip-api.com 响应"""
        if data.get("status") != "success":
            return None
        return GPSLocation(
            latitude=data["lat"],
            longitude=data["lon"],
            accuracy=5000,
            city=data.get("city"),
            region=data.get("regionName"),
            country=data.get("country"),
            source=f"free_{source_name}",
            timestamp=time.time()
        )

    def _parse_ipapi(self, data: dict, source_name: str) -> Optional[GPSLocation]:
        """解析 ipapi.co 响应"""
        if not data.get("latitude"):
            return None
        return GPSLocation(
            latitude=data["latitude"],
            longitude=data["longitude"],
            accuracy=10000,
            city=data.get("city"),
            region=data.get("region"),
            country=data.get("country_name"),
            source=f"free_{source_name}",
            timestamp=time.time()
        )

    def _parse_ip_sb(self, data: dict, source_name: str) -> Optional[GPSLocation]:
        """解析 ip.sb 响应"""
        if data.get("code") != 0:
            return None
        info = data.get("data", {})
        if not info.get("latitude"):
            return None
        return GPSLocation(
            latitude=info["latitude"],
            longitude=info["longitude"],
            accuracy=5000,
            city=info.get("city"),
            region=info.get("region"),
            country=info.get("country_name"),
            source=f"free_{source_name}",
            timestamp=time.time()
        )

    @staticmethod
    def _haversine_distance(lat1, lng1, lat2, lng2) -> float:
        """Haversine 公式计算两点距离（米）"""
        R = 6371000
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (math.sin(dlat/2)**2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlng/2)**2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _is_location_changed(self, old: GPSLocation, new: GPSLocation) -> bool:
        """判断位置是否发生变化"""
        if new.city != old.city or new.country != old.country:
            return True
        distance = self._haversine_distance(
            old.latitude, old.longitude,
            new.latitude, new.longitude
        )
        return distance > self.MOVE_THRESHOLD

    def _handle_location_update(self, new_location: GPSLocation):
        """处理位置更新（去重 + 持久化）"""
        old = self._current
        self._current = new_location
        self._last_fetch_time = time.time()

        if old and not self._is_location_changed(old, new_location):
            self._touch_timestamp()
        else:
            self._write_new_record(new_location)
```

### 3.2 数据持久化逻辑

#### 复用 AAA 共享的 `chatbot.db` → `long_term_memory` 表

定位数据通过 `entity` + `channel` 特殊标记区分，与 AAA 其他记忆共存：

| 字段 | 定位数据值 | 说明 |
|------|-----------|------|
| `entity` | `'current_location'` | 固定实体名 |
| `channel` | `'location'` | 专用 channel |
| `identity_key` | 现有用户 key | 多用户隔离 |
| `content` | JSON 字符串 | 完整位置信息 |
| `status` | `'active'` / `'superseded'` | 最新记录为 active |

#### content JSON 结构

```json
{
  "latitude": 26.6470,
  "longitude": 106.6302,
  "accuracy": 5000,
  "city": "Guiyang",
  "region": "Guizhou",
  "country": "China",
  "source": "free_ip-api.com",
  "timestamp": 1754524800,
  "meta": {
    "ip": "xxx.xxx.xxx.xxx",
    "timezone": "Asia/Shanghai"
  }
}
```

#### 存储操作方法

```python
# （在 LocationManager 内部）

def _load_cached_location(self):
    """从数据库加载最新的位置缓存"""
    try:
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT content, created_at FROM long_term_memory
                WHERE entity = 'current_location'
                  AND channel = 'location'
                  AND status = 'active'
                  AND identity_key = ?
                ORDER BY created_at DESC LIMIT 1
            """, (self._identity_key,))
            row = cursor.fetchone()
            if row:
                data = json.loads(row["content"])
                self._current = GPSLocation(
                    latitude=data["latitude"],
                    longitude=data["longitude"],
                    accuracy=data.get("accuracy", 5000),
                    city=data.get("city"),
                    region=data.get("region"),
                    country=data.get("country"),
                    source=data.get("source", "cache"),
                    timestamp=row["created_at"]
                )
                self._last_fetch_time = row["created_at"]
    except Exception as e:
        logging.error(f"[Location] 加载缓存失败: {e}")

def _touch_timestamp(self):
    """位置未变化 → 仅更新时间戳"""
    try:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                UPDATE long_term_memory
                SET content = json_set(content, '$.timestamp', ?)
                WHERE entity = 'current_location'
                  AND channel = 'location'
                  AND status = 'active'
                  AND identity_key = ?
            """, (time.time(), self._identity_key))
            conn.commit()
    except Exception as e:
        logging.error(f"[Location] 更新时间戳失败: {e}")

def _write_new_record(self, location: GPSLocation):
    """写入新的位置记录（同时标记旧记录为 superseded）"""
    try:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                UPDATE long_term_memory
                SET status = 'superseded'
                WHERE entity = 'current_location'
                  AND channel = 'location'
                  AND status = 'active'
                  AND identity_key = ?
            """, (self._identity_key,))

            conn.execute("""
                INSERT INTO long_term_memory
                (identity_key, entity, channel, content, status, created_at)
                VALUES (?, 'current_location', 'location', ?, 'active', ?)
            """, (
                self._identity_key,
                location.to_json(),
                time.time()
            ))
            conn.commit()
    except Exception as e:
        logging.error(f"[Location] 写入新记录失败: {e}")
```

### 3.3 Prompt 集成

#### 在 location.py 中提供 Prompt 段构建函数

```python
# （在 location.py 模块中，作为独立函数导出）

def build_location_section(db_path: str, identity_key: str) -> str:
    """
    构建位置信息 Prompt 段落
    由 AAA 的 prompt.py 或 main.py 调用，将位置信息注入系统提示词。

    Returns:
        位置信息文本，或空字符串（无定位数据时）
    """
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT content, created_at
                FROM long_term_memory
                WHERE entity = 'current_location'
                  AND channel = 'location'
                  AND status = 'active'
                  AND identity_key = ?
                ORDER BY created_at DESC LIMIT 1
            """, (identity_key,))
            row = cursor.fetchone()

            if not row:
                return ""

            data = json.loads(row["content"])
            age_minutes = int((time.time() - row["created_at"]) / 60)

            accuracy = data.get("accuracy", 5000)
            accuracy_text = _describe_accuracy(accuracy)
            freshness_text = _describe_freshness(age_minutes)
            source_text = _describe_source(data.get("source", "unknown"))

            city = data.get("city", "未知")
            region = data.get("region", "")
            country = data.get("country", "")

            return f"""
### 当前位置信息（系统提供）
- 城市: {city}{(', ' + region) if region else ''}{(', ' + country) if country else ''}
- 经纬度: {data['longitude']:.4f}°E, {data['latitude']:.4f}°N
- 精度: {accuracy_text}（{accuracy} 米）
- 时效: {freshness_text}
- 来源: {source_text}

**位置信息使用规则**:
1. 你可以基于此位置提供天气查询、本地推荐、交通信息等服务
2. 如果用户询问"我在哪里"，可以回答城市名和大致区域，不要暴露精确坐标
3. 如果精度为"城市级别"，不要假装知道具体街道或门牌号
4. 如果位置信息超过 30 分钟未更新，主动提示用户位置可能已过时
5. 永远不要在对用户的回答中提及经纬度数值
"""

    except Exception as e:
        logging.error(f"[Prompt] 加载位置信息失败: {e}")
        return ""


def _describe_accuracy(accuracy_meters: int) -> str:
    if accuracy_meters <= 100:
        return "精确位置"
    elif accuracy_meters <= 1000:
        return "街区级别"
    return "城市级别"


def _describe_freshness(age_minutes: int) -> str:
    if age_minutes < 5:
        return "5 分钟内更新"
    elif age_minutes < 30:
        return f"{age_minutes} 分钟前更新"
    elif age_minutes < 120:
        return f"{age_minutes // 60} 小时前更新"
    return f"{age_minutes // 60} 小时前更新（可能已过时）"


def _describe_source(source: str) -> str:
    mapping = {
        "free_ip-api.com": "ip-api.com 免费定位",
        "free_ipapi.co": "ipapi.co 免费定位",
        "free_ip.sb": "ip.sb 免费定位",
        "cache": "本地缓存",
    }
    return mapping.get(source, source)
```

#### 在 AAA 的 prompt.py 中集成调用

在 `nodes/node_python_aaa_cognition/prompt.py` 中导入 location 模块并调用：

```python
# nodes/node_python_aaa_cognition/prompt.py（修改）

# 新增导入：
# import location  # AAA 内部模块，同级 import

def _prepare_ctx(ctx):
    """填充条件字段 — 新增位置信息注入"""
    # ... 已有逻辑 ...

    # 新增：注入位置信息到上下文
    if not ctx.get("location_section"):
        db_path = ctx.get("db_path", "")
        identity_key = ctx.get("identity_key", "user_001")
        ctx["location_section"] = location.build_location_section(db_path, identity_key)

    # ... 其他逻辑 ...
```

然后在 `_CONTEXT_HEADER` 模板中添加 `{location_section}` 占位：

```python
_CONTEXT_HEADER = """
### 输入上下文
当前对话用户：{identity_key}
...
{reflection_section}
{location_section}   ← 新增
"""
```

### 3.4 GUI 可视化模块

#### 组件：LocationMapWidget

```
gui/widgets/location_map_widget.py
```

```python
# gui/widgets/location_map_widget.py

import urllib.request
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel

from gui.core.config import AppConfig


class LocationMapWidget(QLabel):
    """
    AI 地理位置可视化组件

    显示内容：
    1. 静态地图图片（带红色位置标记）
    2. 当前位置文字描述
    3. 无网络时显示降级文字
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._amap_key = AppConfig().get("amap_key", "")
        self._last_location = None
        self._setup_ui()

    def _setup_ui(self):
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(480, 360)
        self.setStyleSheet("""
            QLabel {
                background: #f5f6fa;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
            }
        """)
        self._show_placeholder("📍 点击获取当前位置")

    def update_location(self, location_dict: dict):
        """更新位置并刷新地图显示"""
        lat = location_dict["latitude"]
        lng = location_dict["longitude"]
        self._last_location = location_dict

        # 获取地图图片
        pixmap = self._fetch_map_image(lat, lng)
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.setPixmap(scaled)
        else:
            # 地图加载失败 → 显示文字信息
            self._show_location_fallback(location_dict)

    def _fetch_map_image(self, lat: float, lng: float) -> QPixmap:
        """获取静态地图图片（高德 → OSM 兜底）"""
        if self._amap_key:
            pixmap = self._fetch_amap(lat, lng)
            if pixmap and not pixmap.isNull():
                return pixmap
        return self._fetch_osm(lat, lng)

    def _fetch_amap(self, lat: float, lng: float) -> QPixmap:
        """高德静态地图 API"""
        try:
            url = (
                f"https://restapi.amap.com/v3/staticmap"
                f"?location={lng},{lat}"
                f"&zoom=14&size=480*360"
                f"&markers=mid,0xFF6B35,A:{lng},{lat}"
                f"&key={self._amap_key}"
            )
            response = urllib.request.urlopen(url, timeout=10)
            pixmap = QPixmap()
            pixmap.loadFromData(response.read())
            return pixmap
        except Exception:
            return QPixmap()

    def _fetch_osm(self, lat: float, lng: float) -> QPixmap:
        """OpenStreetMap 静态地图（免费兜底）"""
        try:
            url = (
                f"https://staticmap.openstreetmap.de/staticmap.php"
                f"?center={lat},{lng}&zoom=14&size=480x360"
                f"&markers={lat},{lng},red"
            )
            response = urllib.request.urlopen(url, timeout=15)
            pixmap = QPixmap()
            pixmap.loadFromData(response.read())
            return pixmap
        except Exception:
            return QPixmap()

    def _show_placeholder(self, text: str):
        self.setText(text)
        self.setPixmap(QPixmap())

    def _show_location_fallback(self, location_dict: dict):
        city = location_dict.get("city", "未知城市")
        accuracy = location_dict.get("accuracy", "?")
        self.setText(f"📍 {city}\n精度: {accuracy}米\n地图加载失败")
        self.setStyleSheet("""
            QLabel {
                background: #f5f6fa;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                color: #666;
                font-size: 14px;
            }
        """)
```

#### 集成到设置面板

在 `gui/pages/settings_panel.py` 中扩展：

```python
# gui/pages/settings_panel.py（修改）

class SettingsPanel(QWidget):
    def _init_ui(self):
        # ... 现有初始化 ...

        # 新增：AI 地理感知区域
        self._add_geo_section()

    def _add_geo_section(self):
        """添加 AI 地理感知设置区域"""
        from gui.widgets.location_map_widget import LocationMapWidget

        geo_group = QGroupBox("🗺️ AI 地理感知")
        geo_layout = QVBoxLayout(geo_group)

        # 地图显示区
        self.location_map = LocationMapWidget()
        geo_layout.addWidget(self.location_map, stretch=1)

        # 位置信息栏
        self.location_info_label = QLabel("📍 位置：加载中...")
        self.location_info_label.setStyleSheet(
            "font-weight: bold; padding: 8px; font-size: 14px;"
        )
        geo_layout.addWidget(self.location_info_label)

        # 控制按钮
        btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 刷新位置")
        self.refresh_btn.clicked.connect(self._refresh_location)
        btn_row.addWidget(self.refresh_btn)

        self.auto_check = QCheckBox("自动更新（5 分钟）")
        self.auto_check.setChecked(True)
        btn_row.addWidget(self.auto_check)
        geo_layout.addLayout(btn_row)

        # 隐私开关
        privacy_row = QHBoxLayout()
        self.enable_check = QCheckBox("启用位置信息")
        self.enable_check.setChecked(True)
        privacy_row.addWidget(self.enable_check)

        self.clear_history_btn = QPushButton("清除历史")
        self.clear_history_btn.clicked.connect(self._clear_location_history)
        privacy_row.addWidget(self.clear_history_btn)
        geo_layout.addLayout(privacy_row)

        self._main_layout.addWidget(geo_group)

    def _refresh_location(self):
        """手动刷新位置"""
        import sys
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..", "..",
            "nodes", "node_python_aaa_cognition"
        ))
        from location import LocationManager
        # ... 获取路径配置，初始化 LocationManager 并刷新 ...

    def _clear_location_history(self):
        """清除位置历史记录"""
        # 调用 LocationManager.clear_location_history()
        ...
```

---

## 四、数据库设计

### 4.1 表结构

复用 AAA 共享的 `nodes/shared/chatbot.db` → `long_term_memory` 表，**无需新建表**。定位数据通过 `entity` + `channel` 唯一标识。

```sql
-- 现有表结构（无需修改）
CREATE TABLE long_term_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity_key TEXT NOT NULL,
    entity TEXT NOT NULL,
    channel TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at REAL NOT NULL
);

-- 建议添加的索引（提升查询性能）
CREATE INDEX IF NOT EXISTS idx_location_query
ON long_term_memory (identity_key, entity, channel, status);
```

### 4.2 数据操作

| 操作 | SQL 条件 | 说明 |
|------|---------|------|
| 查询最新位置 | `entity='current_location' AND status='active'` | 读操作 |
| 新增位置 | `INSERT INTO long_term_memory` | 位置变化时写入 |
| 标记旧记录 | `UPDATE ... SET status='superseded'` | 写入新记录前执行 |
| 更新时间戳 | `UPDATE ... SET content=json_set(...)` | 位置未变时 touch |
| 查询历史轨迹 | `ORDER BY created_at DESC LIMIT N` | 读取历史 |

---

## 五、API 接口清单

### 5.1 LocationManager 公共 API

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `get_location(force_refresh=False)` | force_refresh: bool | `LocationResult` | 获取当前位置 |
| `get_cached_location()` | - | `Optional[GPSLocation]` | 获取缓存（不触发网络） |
| `set_enabled(enabled)` | enabled: bool | None | 启用/禁用定位 |
| `is_enabled()` | - | bool | 查询定位状态 |
| `get_location_history(limit=20)` | limit: int | `List[dict]` | 查询历史记录 |
| `clear_location_history()` | - | int | 清除历史，返回条数 |

### 5.2 location.py 独立函数

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `build_location_section(db_path, identity_key)` | 数据库路径, 用户 key | str | 构建 Prompt 位置段 |

### 5.3 配置项（gui_config.json）

```json
{
    "location": {
        "enabled": true,
        "update_interval": 300,
        "move_threshold": 500,
        "amap_key": "",
        "show_in_gui": true,
        "privacy": {
            "show_city": true,
            "show_coordinates": false,
            "save_history": true
        }
    }
}
```

---

## 六、与现有架构的对接点

### 6.1 模块依赖关系

```
┌───────────────────────────────────────────────────────────────────┐
│  AAA 认知节点 (nodes/node_python_aaa_cognition/)                  │
│                                                                   │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐              │
│  │ memos   │  │ diary   │  │ prompt  │  │ location │ ← ★ 新增    │
│  │ .py     │  │ .py     │  │ .py     │  │ .py      │              │
│  └─────────┘  └─────────┘  └────┬────┘  └────┬────┘              │
│                                  │            │                   │
│                    import location│            │                   │
│                    build_location│            │                   │
│                    _section()   │            │                   │
│                                  ▼            ▼                   │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │                     main.py（节点主逻辑）                    │  │
│  │  process() → 调用 prompt.build() → 消费含位置的 Prompt       │  │
│  └───────────────────────────┬─────────────────────────────────┘  │
│                              │                                    │
│                              ▼                                    │
│              ┌─────────────────────────────┐                      │
│              │  nodes/shared/chatbot.db    │                      │
│              │  long_term_memory 表        │                      │
│              │  entity='current_location'  │                      │
│              └─────────────────────────────┘                      │
└───────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌───────────────────────────────────────────────────────────────────┐
│  GUI 层 (gui/)                                                    │
│                                                                   │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │LocationMapWidget │  │ settings_panel   │  │  AppConfig    │  │
│  │ (widgets/)       │  │ (pages/)        │  │  (core/)      │  │
│  └──────────────────┘  └──────────────────┘  └────────────────┘  │
└───────────────────────────────────────────────────────────────────┘
```

### 6.2 对接点详细说明

| 对接点 | 文件路径 | 修改类型 | 工作量 |
|--------|---------|---------|:------:|
| **定位模块** | `nodes/node_python_aaa_cognition/location.py` | **新建** | 4h |
| Prompt 集成 | `nodes/node_python_aaa_cognition/prompt.py` | 修改：import + 注入 location_section | 0.5h |
| 地图组件 | `gui/widgets/location_map_widget.py` | **新建** | 2h |
| 设置页集成 | `gui/pages/settings_panel.py` | 修改：新增地理感知区 | 2h |
| 配置扩展 | `gui/core/config.py` | 修改：location 配置读写 | 0.5h |
| 定时刷新 | `gui/main.py` | 修改：QTimer 定时 | 0.5h |

---

## 七、开发步骤与时间线

### Day 1：核心模块（4h）

| 序号 | 任务 | 产出 | 验收标准 |
|:----:|------|------|---------|
| 1 | 创建 `nodes/node_python_aaa_cognition/location.py` | LocationManager 类 + GPSLocation 类 | 单元测试通过 |
| 2 | 实现 3 个免费定位源解析 | `_parse_ip_api/ipapi/ip_sb` | mock 测试通过 |
| 3 | 实现去重存储逻辑 | `_handle_location_update()` | 移动/静止场景测试通过 |
| 4 | 实现 `build_location_section()` | Prompt 段构建函数 | 返回正确文本 |

### Day 2：集成与 GUI（4h）

| 序号 | 任务 | 产出 | 验收标准 |
|:----:|------|------|---------|
| 5 | 修改 `prompt.py` 集成位置段 | import + 模板注入 | Prompt 含位置信息 |
| 6 | 创建 `LocationMapWidget` | 地图显示组件 | 显示带标记地图 |
| 7 | 修改 `settings_panel.py` | 地理感知设置区 | UI 正确显示 |
| 8 | 添加定时刷新 + 配置项 | QTimer + config | 5 分钟自动刷新 |

### 合计：约 1 个工作日（8h）

---

## 八、验收标准

### 8.1 功能验收

- [ ] **定位获取**：启动后首次调用能获取 IP 定位
- [ ] **多源降级**：主源失败时自动切换备源
- [ ] **去重存储**：位置不变时仅更新时间戳
- [ ] **Prompt 注入**：AAA 节点 Prompt 包含当前位置
- [ ] **LLM 感知**：AI 能回答基于位置的问题
- [ ] **GUI 显示**：设置页显示带标记的静态地图
- [ ] **手动刷新**：刷新按钮立即更新位置
- [ ] **隐私开关**：禁用后 Prompt/GUI 都不显示位置

### 8.2 非功能验收

- [ ] **零新依赖**：仅使用 Python 标准库 + 现有 PySide6
- [ ] **零体积增长**：不引入新的第三方包
- [ ] **响应速度**：定位请求超时 ≤ 5 秒
- [ ] **容错性**：所有源失败不影响主对话流程
- [ ] **线程安全**：多线程环境下数据一致

### 8.3 边界测试

- [ ] 网络断开 → 返回上次缓存
- [ ] 所有源异常 → 返回空，不崩溃
- [ ] 用户禁用 → Prompt 不含位置
- [ ] 位置过时 → Prompt 标记"可能已过时"

---

## 九、测试方案

### 9.1 单元测试

```python
# tests/test_location_manager.py

class TestLocationManager:
    # 定位源解析
    def test_parse_ip_api_success(self): ...
    def test_parse_ipapi_success(self): ...
    def test_parse_ip_sb_success(self): ...
    def test_parse_invalid_response(self): ...

    # 多源降级
    def test_fallback_when_primary_fails(self): ...
    def test_all_sources_fail(self): ...

    # 去重逻辑
    def test_location_unchanged_updates_timestamp(self): ...
    def test_location_changed_creates_new_record(self): ...
    def test_500m_within_threshold(self): ...
    def test_500m_exceeds_threshold(self): ...

    # 缓存
    def test_cache_returns_fresh_data(self): ...
    def test_cache_expires_after_5min(self): ...
    def test_force_refresh_ignores_cache(self): ...

    # 开关
    def test_disabled_returns_error(self): ...
    def test_enable_disable_cycle(self): ...

    # Prompt 段构建
    def test_build_location_section_with_data(self): ...
    def test_build_location_section_empty(self): ...
    def test_accuracy_descriptions(self): ...
    def test_freshness_descriptions(self): ...
```

### 9.2 集成测试

```python
# tests/test_location_integration.py

class TestLocationIntegration:
    def test_full_pipeline(self):
        """定位 → 存储 → Prompt → LLM 感知"""
        from nodes.node_python_aaa_cognition.location import (
            LocationManager, build_location_section
        )
        mgr = LocationManager(db_path, config)
        result = mgr.get_location(force_refresh=True)
        assert result.success

        section = build_location_section(db_path, identity_key)
        assert section  # 非空

    def test_prompt_contains_location(self):
        """验证 AAA Prompt 含位置信息"""
        # 通过 AAA 完整流程测试
        ...

    def test_gui_shows_location(self):
        """验证 GUI 组件"""
        from gui.widgets.location_map_widget import LocationMapWidget
        widget = LocationMapWidget()
        widget.update_location({"latitude": 26.6, "longitude": 106.6, ...})
        assert widget.pixmap() is not None
```

---

## 十、风险与降级策略

| 风险 | 触发条件 | 缓解措施 |
|------|---------|---------|
| IP 精度不足 | VPN/代理 | Prompt 中标注精度，禁止编造精确地址 |
| 服务不可用 | 所有免费源宕机 | 返回缓存，标记 stale |
| 限流被封 | 短时间大量请求 | 多源轮换 + ≥1s 间隔保护 |
| 隐私问题 | 用户不希望暴露 | 一键开关，关闭即清除 |
| 高德 Key 失效 | Key 过期 | 自动降级 OpenStreetMap |
| 数据库损坏 | 硬件故障 | 不影响主流程，仅丢历史 |

### 降级路径

```
正常：ip-api.com → 成功 → 存储 → Prompt → GUI
降级1：主源失败 → 备源 → 成功 → ...
降级2：全部源失败 → 读取缓存 → stale 标记
降级3：无网络 → 读取缓存 → 下次重试
降级4：用户禁用 → 返回错误 → 不注入 Prompt/GUI
```

---

## 附录：免费 API 速查

| 服务 | URL | 精度 | 额度 | 特点 |
|------|-----|:----:|:----:|------|
| ip-api.com | `http://ip-api.com/json/` | 5km | 45次/小时 | 快、稳定、支持中文 |
| ipapi.co | `https://ipapi.co/json/` | 10km | 50000次/天 | 额度大 |
| ip.sb | `https://api.ip.sb/geoip` | 5km | 无限次 | 无限制、隐私友好 |
| OpenStreetMap | `https://staticmap.openstreetmap.de/` | - | 1次/秒 | 免费地图 |

---

*文档版本：v1.1 | 修正架构归属：定位模块归 AAA 认知节点（`nodes/node_python_aaa_cognition/location.py`），与 `memos.py`、`diary.py` 并列，而非 `bnos_runtime/`（节点编排层）*
*关联设计文档：`[PLAN]-AI定位信息功能设计方案.md`、`[PLAN]-AI世界感知记忆系统设计方案.md`*