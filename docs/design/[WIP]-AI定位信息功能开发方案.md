# \[PLAN] AI 定位信息功能开发方案

> 日期：2026-08-08 | 版本：v1.3 | 状态：\[PLAN]
> 设计文档：`[PLAN]-AI定位信息功能设计方案.md`、`[PLAN]-AI世界感知记忆系统设计方案.md`
> 优先级：Top 1（性价比 11.43，工作量 0.35 天）
> 架构归属：AAA 认知节点（`nodes/node_python_aaa_cognition/`），与 `memos.py`、`diary.py` 并列

***

## 目录

- [一、需求定位](#一需求定位)
  - [1.3 动态精度说明](#13-动态精度说明)
  - [1.4 Qt 定位平台兼容性说明](#14-qt-定位平台兼容性说明关键)
  - [1.5 用户价值](#15-用户价值)
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
- [附录：定位源速查](#附录定位源速查)

***

## 一、需求定位

### 1.1 功能定义

为 BNOS AI 提供**当前地理位置感知能力**，使 AI 能够"知道自己在哪里"，并基于此提供本地化服务。定位模块归属 AAA 认知节点，作为 AI 世界感知能力的一部分。

### 1.2 核心能力矩阵

|    能力层级   | 功能        | 说明                  | 优先级 |
| :-------: | --------- | ------------------- | :-: |
| **L0 核心** | Qt 系统定位  | 跨平台 GPS/Wi-Fi/基站融合（5~50m）  |  P0 |
| **L0 核心** | IP 定位降级   | 多源轮换 IP 定位（5~10km）     |  P0 |
| **L0 核心** | 位置存储      | 将定位结果持久化到数据库        |  P0 |
| **L0 核心** | Prompt 注入 | 将位置信息注入 LLM 提示词     |  P0 |
| **L1 基础** | 去重更新      | 位置不变时仅更新时间戳         |  P1 |
| **L1 基础** | 地图可视化     | 在 GUI 中显示 AI 当前位置地图 |  P1 |
| **L1 基础** | 轨迹查询      | 查询历史位置变化记录          |  P1 |
| **L2 增强** | 逆地理编码     | 将经纬度转为可读地址          |  P2 |
| **L2 增强** | 天气联动      | 自动获取当前位置天气          |  P2 |

### 1.3 动态精度说明

本方案采用**三级自动降级**策略，根据设备能力动态选择最高精度：

| 精度等级 | 精度范围 | 来源 | 典型场景 |
|:--------:|:--------:|:----:|:--------:|
| 精确位置 | 5~50m | Qt 系统定位 (GPS/Wi-Fi) | 手机、笔记本室外 |
| 街区级别 | 50~500m | Qt 系统定位 (Wi-Fi/基站融合) | 笔记本室内、Win10+ 桌面 |
| 城市级别 | 5~10km | IP 定位降级 | 台式机、无 Wi-Fi、VPN |

降级规则：
1. 优先尝试 Qt `QGeoPositionInfoSource`（跨平台系统定位）
2. 若 Qt 定位失败/不可用，降级到多源 IP 定位
3. 所有 IP 源均失败，返回本地缓存并标记 `stale`

### 1.4 Qt 定位平台兼容性说明（关键）

Qt Positioning 模块在各平台的实际行为差异较大，需针对性说明：

| 平台 | Qt 定位可用性 | 实际精度 | 备注 |
|:----:|:----------:|:--------:|:----:|
| **Windows 10/11** (桌面) | ✅ 可用（需 WinRT 桥接） | 50~500m (Wi-Fi/基站) | 需系统「位置服务」开启；无 GPS 硬件时依赖 Wi-Fi 指纹 |
| **Windows 7/8** (桌面) | ❌ 不可用 | — | 仅支持串口 NMEA GPS，实际无可用后端 |
| **Linux** (桌面) | ⚠️ 依赖 GeoClue 服务 | 500m~城市级 | 需安装 `geoclue-2.0` 包并启用 |
| **macOS** | ✅ 可用 | 5~500m | 通过 Core Location 框架，权限弹窗 |
| **Android** | ✅ 原生支持 | 5~50m | GPS/Wi-Fi/基站全支持 |
| **iOS** | ✅ 原生支持 | 5~50m | 同上 |

**关键事实：**
- PySide6 的 `QGeoPositionInfoSource.createDefaultSource()` 在 Windows 10+ 桌面版**通常可创建成功**，但实际精度取决于硬件
- 绝大多数 Windows 桌面/台式机**没有 GPS 硬件**，Qt 通过 WinRT 调用 `Windows.Devices.Geolocation`，依赖 Wi-Fi 接入点指纹 + 基站 ID 融合定位，精度 50~500m
- 若用户关闭 Windows 「位置服务」，`createDefaultSource()` 可能返回 `nullptr`，或 `startUpdates()` 后无信号
- **无任何硬件定位能力的纯台式机**（无 Wi-Fi、有线网络）：Qt 定位必然失败 → 自动降级 IP
- IP 定位在所有场景下均作为可靠兜底，保证功能可用

**本方案的真实可达精度分布：**

| 设备类型 | 一级定位源 | 实际可达精度 |
|:--------:|:--------:|:----------:|
| 手机 (Android/iOS) | Qt GPS/Wi-Fi | **5~50m** (精确) |
| 笔记本 (有 Wi-Fi, Win10+) | Qt Wi-Fi 指纹 | **50~300m** (街区级) |
| 笔记本 (Linux, 有 GeoClue) | Qt GeoClue Wi-Fi | **100~500m** (街区级) |
| 笔记本 (macOS) | Qt Core Location | **5~200m** (精确~街区) |
| 台式机 (有 Wi-Fi, Win10+) | Qt Wi-Fi 指纹 | **100~500m** (街区级) |
| 台式机 (无 Wi-Fi, 有线) | ❌ Qt 失败 → IP | **5~10km** (城市级) |
| 所有设备 (VPN/代理) | Qt 可能异常 → IP | **5~10km** (城市级) |

> **结论**：Qt 定位在移动设备上可达高精度（5~50m），在桌面设备上通常为街区级（50~500m），IP 定位作为可靠兜底保证城市级精度（5~10km）。三级降级覆盖所有使用场景，无需用户配置。

### 1.5 用户价值

- AI 回答"我在哪"时能说出城市名
- 天气/本地推荐等场景无需用户提供位置
- GUI 设置页可直观看到 AI 感知的位置

***

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

| 模块                 | 文件路径                                          | 职责                                |
| ------------------ | --------------------------------------------- | --------------------------------- |
| **location.py ★**  | `nodes/node_python_aaa_cognition/location.py` | **新增** - AAA 节点定位（读库+IP降级+Prompt构建） |
| **location_provider.py ★** | `gui/core/location_provider.py` | **新增** - GUI 层 Qt 系统定位提供者 |
| memos.py           | `nodes/node_python_aaa_cognition/memos.py`    | 语义记忆检索                            |
| diary.py           | `nodes/node_python_aaa_cognition/diary.py`    | 日记功能                              |
| prompt.py          | `nodes/node_python_aaa_cognition/prompt.py`   | Prompt 模板拼接（修改：增加位置段调用）           |
| db.py              | `nodes/node_python_aaa_cognition/db.py`       | 数据库操作                             |
| main.py            | `nodes/node_python_aaa_cognition/main.py`     | 节点主逻辑                             |
| LocationMapWidget  | `gui/widgets/location_map_widget.py`          | GUI 地图显示组件（新增）                    |
| settings\_panel.py | `gui/pages/settings_panel.py`                 | 设置面板（修改：集成地理感知区）                  |

### 2.3 技术选型

| 维度     | 选型                                 | 理由                    |
| ------ | ---------------------------------- | --------------------- |
| 一级定位源 | **Qt QGeoPositionInfoSource** | 跨平台（Win/Mac/Linux）、PySide6 自带、GPS/Wi-Fi/基站融合、5~50m 精度 |
| 二级定位源 | ip-api.com（主）+ ipapi.co + ip.sb（备） | 免费、无需 Key、城市级精度、作为降级方案 |
| 地图显示   | 高德静态地图 API + OSM 兜底                | 有 Key 用高德，无 Key 用 OSM |
| 数据存储   | 复用 `long_term_memory` 表            | 零表结构变更，通过 entity 区分   |
| 网络请求   | `urllib.request`                   | Python 标准库，零新依赖       |
| GUI 框架 | 现有 PySide6                         | 与项目一致，Qt 地理定位 API 原生集成 |

#### Qt 定位 vs IP 定位对比

| 对比项 | Qt 系统定位 | IP 定位 |
|--------|------------|---------|
| 精度 | 5~50m | 5~10km |
| 跨平台 | ✅ 全平台 | ✅ 全平台 |
| 额外依赖 | 无（PySide6 自带） | 无 |
| 用户感知 | 首次可能请求权限 | 完全无感 |
| 稳定性 | 依赖硬件+系统服务 | 依赖网络 |
| 适用场景 | 有 GPS/Wi-Fi 的移动/桌面设备 | 台式机、无 Wi-Fi 环境 |

***

## 三、模块实现方案

### 3.1 定位模块（location.py）

#### 定位架构说明

由于 BNOS AI 的架构分为 **GUI 层**（Qt 事件循环）和 **AAA 节点层**（无 Qt 的 Python 子进程），定位策略分两层：

```
┌─────────────────────────────────────────────────────────────────┐
│ GUI 层（PySide6 主进程，有 Qt 事件循环）                           │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  QtGeoPositionProvider                                   │   │
│  │  QGeoPositionInfoSource                                  │   │
│  │  (GPS / Wi-Fi / 基站 融合, 5~50m)                         │   │
│  └───────────────────────────┬─────────────────────────────┘   │
│                              │ 写入                              │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  nodes/shared/chatbot.db                                 │   │
│  │  long_term_memory (entity='current_location')            │   │
│  │  ← 高精度位置 (Qt 写入)                                   │   │
│  │  → AAA 节点读取                                           │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ AAA 节点层（独立 Python 进程，无 Qt 事件循环）                      │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  LocationManager                                         │   │
│  │  1. 读取数据库中最新位置（可能是 Qt 写入的高精度）             │   │
│  │  2. 若位置过时(>5min)，尝试 IP 定位刷新                    │   │
│  │  3. 所有 IP 源失败 → 返回缓存                              │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

#### 文件位置

```
nodes/node_python_aaa_cognition/location.py          # AAA 节点定位逻辑（IP 降级 + 数据库读取）
gui/core/location_provider.py                        # GUI 层 Qt 定位提供者（新增）
```

> AAA 节点的 `location.py` 与 `memos.py`、`diary.py`、`prompt.py` 并列。
> GUI 层的 `location_provider.py` 在主 GUI 启动时初始化，持续获取高精度定位并写入共享数据库。

#### 模块结构总览（AAA 节点 location.py）

```python
# nodes/node_python_aaa_cognition/location.py

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
    accuracy: float          # 精度（米），实际动态值
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    source: str = "ip"       # "qt_gps" / "qt_wifi" / "ip" / "cache"
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
        """精度等级描述（基于实际精度值动态判断）"""
        if self.accuracy <= 100:
            return "精确位置"
        elif self.accuracy <= 1000:
            return "街区级别"
        return "城市级别"

    @property
    def source_description(self) -> str:
        """定位来源描述"""
        mapping = {
            "qt_gps": "GPS 卫星定位",
            "qt_wifi": "Wi-Fi 网络定位",
            "qt_cell": "基站定位",
            "qt_unknown": "系统定位",
            "ip": "IP 网络定位",
            "cache": "本地缓存",
        }
        return mapping.get(self.source, self.source)


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


# ════════════════════════════════════════════════════════════════
#  LocationManager（AAA 节点内部）
# ════════════════════════════════════════════════════════════════

class LocationManager:
    """
    AAA 节点定位管理器

    特性：
    - 优先读取 GUI 层 Qt 定位写入的高精度位置
    - 位置过时(>5min)时自动尝试 IP 定位刷新
    - 多源 IP 降级（3 个免费源轮换）
    - 5 分钟缓存 + 手动刷新
    - 去重存储（500m 内移动只更新时间戳）
    - 线程安全（RLock 保护）
    """

    # 配置常量
    DEFAULT_UPDATE_INTERVAL = 300   # 5 分钟自动更新
    MOVE_THRESHOLD = 500            # 500 米视为位置变化
    REQUEST_TIMEOUT = 5             # 网络请求超时
    STALE_THRESHOLD = 600           # 10 分钟视为过时

    # 免费 IP 定位源（按优先级排序）
    IP_SOURCES = [
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
        """获取当前位置（读缓存 → IP 降级 → 缓存兜底）"""
        with self._lock:
            if not self._enabled:
                return LocationResult(success=False, error="定位功能已禁用")

            # 1. 检查数据库中是否有 GUI 层写入的高精度位置
            db_location = self._read_latest_from_db()
            if db_location and not force_refresh:
                if (time.time() - db_location.timestamp) < self._update_interval:
                    self._current = db_location
                    self._last_fetch_time = db_location.timestamp
                    return LocationResult(success=True, location=db_location)

            # 2. 尝试 IP 定位刷新
            for _ in range(len(self.IP_SOURCES)):
                source = self.IP_SOURCES[self._source_index]
                location = self._fetch_from_source(source)
                self._source_index = (self._source_index + 1) % len(self.IP_SOURCES)

                if location:
                    self._handle_location_update(location)
                    return LocationResult(success=True, location=location)

            # 3. IP 全部失败 → 返回缓存
            if self._current:
                stale = (time.time() - self._current.timestamp) > self.STALE_THRESHOLD
                return LocationResult(
                    success=True,
                    location=self._current,
                    from_cache=True,
                    stale=stale
                )
            return LocationResult(success=False, error="所有定位源均失败")

    def set_enabled(self, enabled: bool):
        with self._lock:
            self._enabled = enabled

    def is_enabled(self) -> bool:
        return self._enabled

    def get_cached_location(self) -> Optional[GPSLocation]:
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
                        "source": data.get("source"),
                        "accuracy": data.get("accuracy"),
                        "status": row["status"],
                        "time": row["created_at"]
                    })
                return history
        except Exception as e:
            logging.error(f"[Location] 查询历史失败: {e}")
            return []

    def clear_location_history(self) -> int:
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

    def _read_latest_from_db(self) -> Optional[GPSLocation]:
        """从数据库读取最新位置（由 GUI 层 Qt 定位写入）"""
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
                    return GPSLocation(
                        latitude=data["latitude"],
                        longitude=data["longitude"],
                        accuracy=data.get("accuracy", 5000),
                        city=data.get("city"),
                        region=data.get("region"),
                        country=data.get("country"),
                        source=data.get("source", "cache"),
                        timestamp=row["created_at"]
                    )
        except Exception as e:
            logging.error(f"[Location] 读取数据库位置失败: {e}")
        return None

    def _fetch_from_source(self, source: dict) -> Optional[GPSLocation]:
        """从单个 IP 源获取定位"""
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
        if data.get("status") != "success":
            return None
        return GPSLocation(
            latitude=data["lat"],
            longitude=data["lon"],
            accuracy=5000,
            city=data.get("city"),
            region=data.get("regionName"),
            country=data.get("country"),
            source="ip",
            timestamp=time.time()
        )

    def _parse_ipapi(self, data: dict, source_name: str) -> Optional[GPSLocation]:
        if not data.get("latitude"):
            return None
        return GPSLocation(
            latitude=data["latitude"],
            longitude=data["longitude"],
            accuracy=10000,
            city=data.get("city"),
            region=data.get("region"),
            country=data.get("country_name"),
            source="ip",
            timestamp=time.time()
        )

    def _parse_ip_sb(self, data: dict, source_name: str) -> Optional[GPSLocation]:
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
            source="ip",
            timestamp=time.time()
        )

    @staticmethod
    def _haversine_distance(lat1, lng1, lat2, lng2) -> float:
        R = 6371000
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (math.sin(dlat/2)**2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlng/2)**2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _is_location_changed(self, old: GPSLocation, new: GPSLocation) -> bool:
        if new.city != old.city or new.country != old.country:
            return True
        distance = self._haversine_distance(
            old.latitude, old.longitude,
            new.latitude, new.longitude
        )
        return distance > self.MOVE_THRESHOLD

    def _handle_location_update(self, new_location: GPSLocation):
        old = self._current
        self._current = new_location
        self._last_fetch_time = time.time()

        if old and not self._is_location_changed(old, new_location):
            self._touch_timestamp()
        else:
            self._write_new_record(new_location)
```

#### GUI 层 Qt 定位提供者

```python
# gui/core/location_provider.py

import time
import json
import logging
import sqlite3
from typing import Optional

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtPositioning import QGeoPositionInfoSource, QGeoCoordinate

logger = logging.getLogger(__name__)


class QtLocationProvider(QObject):
    """
    GUI 层 Qt 定位提供者

    使用 Qt QGeoPositionInfoSource 获取系统级定位（GPS/Wi-Fi/基站融合），
    并将高精度位置写入共享数据库，供 AAA 节点消费。

    特性：
    - 跨平台（Windows/macOS/Linux）
    - 自动适配系统定位能力
    - 5 分钟定时刷新
    - 写数据库供 AAA 节点读取
    """

    location_updated = Signal(dict)   # 位置更新信号

    def __init__(self, db_path: str, identity_key: str = "user_001", parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self._identity_key = identity_key
        self._source: Optional[QGeoPositionInfoSource] = None
        self._last_location = None
        self._last_write_time: float = 0

        self._init_source()

    def _init_source(self):
        """初始化 Qt 定位源"""
        try:
            # 创建默认定位源（自动适配平台）
            self._source = QGeoPositionInfoSource.createDefaultSource(self)

            if self._source:
                self._source.positionUpdated.connect(self._on_position_updated)
                self._source.positionError.connect(self._on_position_error)

                # 设置更新间隔（5 分钟）
                self._source.setUpdateInterval(300000)  # ms
                self._source.setRequestTimeout(10000)   # ms

                logger.info("[QtLocation] 定位源初始化成功，支持: %s",
                          self._source.supportedPositioningMethods())
            else:
                logger.warning("[QtLocation] 无法创建默认定位源")
        except Exception as e:
            logger.error(f"[QtLocation] 初始化失败: {e}")
            self._source = None

    def start(self):
        """启动持续定位"""
        if self._source:
            self._source.startUpdates()
            # 立即获取一次当前位置
            self._request_once()
            logger.info("[QtLocation] 定位持续更新已启动")

    def stop(self):
        """停止定位"""
        if self._source:
            self._source.stopUpdates()
            logger.info("[QtLocation] 定位已停止")

    def _request_once(self):
        """请求一次当前位置"""
        if self._source:
            self._source.requestUpdate(5000)

    def _on_position_updated(self, info):
        """接收 Qt 位置更新"""
        if not info.isValid():
            return

        coord = info.coordinate()
        accuracy = info.hasAttribute(QGeoCoordinate.HorizontalAccuracy)
        accuracy_val = info.attribute(QGeoCoordinate.HorizontalAccuracy) if accuracy else 5000

        # 判断来源
        source_type = "qt_unknown"
        if accuracy_val <= 50:
            source_type = "qt_gps"
        elif accuracy_val <= 200:
            source_type = "qt_wifi"
        else:
            source_type = "qt_cell"

        location_data = {
            "latitude": coord.latitude(),
            "longitude": coord.longitude(),
            "accuracy": accuracy_val,
            "source": source_type,
            "timestamp": time.time(),
        }

        # 逆地理编码获取城市（可选，暂不实现避免额外依赖）
        # 直接用经纬度，城市信息从 IP 降级时补充

        self._write_to_db(location_data)
        self._last_location = location_data
        self._last_write_time = time.time()

        self.location_updated.emit(location_data)
        logger.info(f"[QtLocation] 位置更新: {accuracy_val:.0f}m ({source_type})")

    def _on_position_error(self, error, message):
        """定位错误回调"""
        logger.warning(f"[QtLocation] 定位错误 {error}: {message}")

    def _write_to_db(self, location_data: dict):
        """将高精度位置写入共享数据库"""
        try:
            data_copy = {
                **location_data,
                "city": None,   # Qt 定位不直接给城市名
                "region": None,
                "country": None,
            }
            content = json.dumps(data_copy, ensure_ascii=False)

            with sqlite3.connect(self._db_path) as conn:
                # 标记旧记录为 superseded
                conn.execute("""
                    UPDATE long_term_memory
                    SET status = 'superseded'
                    WHERE entity = 'current_location'
                      AND channel = 'location'
                      AND status = 'active'
                      AND identity_key = ?
                """, (self._identity_key,))

                # 插入新记录
                conn.execute("""
                    INSERT INTO long_term_memory
                    (identity_key, entity, channel, content, status, created_at)
                    VALUES (?, 'current_location', 'location', ?, 'active', ?)
                """, (self._identity_key, content, time.time()))
                conn.commit()

        except Exception as e:
            logger.error(f"[QtLocation] 写入数据库失败: {e}")

    def get_last_location(self) -> Optional[dict]:
        return self._last_location
```

#### 启动集成（在 gui/main.py 中）

```python
# gui/main.py（修改）

def main():
    # ... 现有初始化 ...

    # 启动 GUI 层 Qt 定位
    from gui.core.location_provider import QtLocationProvider
    db_path = get_shared_db_path()  # 获取共享数据库路径
    identity_key = config.get("identity_key", "user_001")

    location_provider = QtLocationProvider(db_path, identity_key)
    location_provider.location_updated.connect(_on_gui_location_updated)
    location_provider.start()  # 启动持续定位
```

### 3.2 数据持久化逻辑

#### 复用 AAA 共享的 `chatbot.db` → `long_term_memory` 表

定位数据通过 `entity` + `channel` 特殊标记区分，与 AAA 其他记忆共存：

| 字段             | 定位数据值                       | 说明           |
| -------------- | --------------------------- | ------------ |
| `entity`       | `'current_location'`        | 固定实体名        |
| `channel`      | `'location'`                | 专用 channel   |
| `identity_key` | 现有用户 key                    | 多用户隔离        |
| `content`      | JSON 字符串                    | 完整位置信息       |
| `status`       | `'active'` / `'superseded'` | 最新记录为 active |

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

            city = data.get("city") or "未知"
            region = data.get("region") or ""
            country = data.get("country") or ""
            has_coords = "latitude" in data and "longitude" in data

            # 城市信息可能为 None（Qt 定位不直接给城市名）
            location_line = city
            if region:
                location_line += f", {region}"
            if country:
                location_line += f", {country}"
            if not data.get("city") and has_coords:
                location_line = f"坐标 {data['longitude']:.4f}°E, {data['latitude']:.4f}°N (无城市名)"

            coord_line = ""
            if accuracy <= 1000 and has_coords:
                coord_line = f"- 精确坐标: {data['longitude']:.4f}°E, {data['latitude']:.4f}°N"

            return f"""
### 当前位置信息（系统提供）
- 位置: {location_line}
{coord_line}
- 精度: {accuracy_text}（{accuracy:.0f} 米）
- 时效: {freshness_text}
- 来源: {source_text}

**位置信息使用规则**:
1. 你可以基于此位置提供天气查询、本地推荐、交通信息等服务
2. 如果用户询问"我在哪里"，根据精度等级回答：
   - 精确位置（≤100m）：可以说"你在 XX 市 XX 区附近"
   - 街区级别（≤1000m）：可以说"你在 XX 市 XX 区一带"
   - 城市级别（>1000m）：只说"你在 XX 市"
3. 永远不要在对用户的回答中提及经纬度数值
4. 如果位置信息超过 30 分钟未更新，主动提示用户位置可能已过时
"""

    except Exception as e:
        logging.error(f"[Prompt] 加载位置信息失败: {e}")
        return ""


def _describe_accuracy(accuracy_meters: float) -> str:
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
        "qt_gps": "GPS 卫星定位",
        "qt_wifi": "Wi-Fi 网络定位",
        "qt_cell": "基站定位",
        "qt_unknown": "系统定位",
        "ip": "IP 网络定位",
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

***

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

| 操作     | SQL 条件                                          | 说明          |
| ------ | ----------------------------------------------- | ----------- |
| 查询最新位置 | `entity='current_location' AND status='active'` | 读操作         |
| 新增位置   | `INSERT INTO long_term_memory`                  | 位置变化时写入     |
| 标记旧记录  | `UPDATE ... SET status='superseded'`            | 写入新记录前执行    |
| 更新时间戳  | `UPDATE ... SET content=json_set(...)`          | 位置未变时 touch |
| 查询历史轨迹 | `ORDER BY created_at DESC LIMIT N`              | 读取历史        |

***

## 五、API 接口清单

### 5.1 LocationManager 公共 API

| 方法                                  | 参数                   | 返回值                     | 说明          |
| ----------------------------------- | -------------------- | ----------------------- | ----------- |
| `get_location(force_refresh=False)` | force\_refresh: bool | `LocationResult`        | 获取当前位置      |
| `get_cached_location()`             | -                    | `Optional[GPSLocation]` | 获取缓存（不触发网络） |
| `set_enabled(enabled)`              | enabled: bool        | None                    | 启用/禁用定位     |
| `is_enabled()`                      | -                    | bool                    | 查询定位状态      |
| `get_location_history(limit=20)`    | limit: int           | `List[dict]`            | 查询历史记录      |
| `clear_location_history()`          | -                    | int                     | 清除历史，返回条数   |

### 5.2 location.py 独立函数

| 函数                                              | 参数            | 返回值 | 说明            |
| ----------------------------------------------- | ------------- | --- | ------------- |
| `build_location_section(db_path, identity_key)` | 数据库路径, 用户 key | str | 构建 Prompt 位置段 |

### 5.3 配置项（gui\_config.json）

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

***

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

| 对接点       | 文件路径                                          | 修改类型                             |  工作量 |
| --------- | --------------------------------------------- | -------------------------------- | :--: |
| **GUI 层 Qt 定位** | `gui/core/location_provider.py` | **新建**                           |  3h  |
| **定位模块**  | `nodes/node_python_aaa_cognition/location.py` | **新建**                           |  3h  |
| Prompt 集成 | `nodes/node_python_aaa_cognition/prompt.py`   | 修改：import + 注入 location_section | 0.5h |
| GUI 启动集成 | `gui/main.py` | 修改：启动时初始化 QtLocationProvider | 0.5h |
| 地图组件      | `gui/widgets/location_map_widget.py`          | **新建**                           |  2h  |
| 设置页集成     | `gui/pages/settings_panel.py`                 | 修改：新增地理感知区                       |  2h  |
| 配置扩展      | `gui/core/config.py`                          | 修改：location 配置读写                 | 0.5h |

***

## 七、开发步骤与时间线

### Day 1：GUI 层 Qt 定位（3h）

| 序号 | 任务 | 产出 | 验收标准 |
|:----:|------|------|----------|
| 1 | 创建 `gui/core/location_provider.py` | `QtLocationProvider` 类 | 初始化不崩溃，信号可连接 |
| 2 | 实现 `_on_position_updated` + DB 写入 | 高精度定位 → 数据库 | 写入记录含 accuracy/source |
| 3 | 修改 `gui/main.py` 启动集成 | 启动时自动初始化定位 | GUI 启动后开始获取位置 |

### Day 2：AAA 节点定位 + Prompt（4h）

| 序号 | 任务 | 产出 | 验收标准 |
|:----:|------|------|----------|
| 4 | 创建 `nodes/node_python_aaa_cognition/location.py` | `LocationManager` 类 + `GPSLocation` 类 | 单元测试通过 |
| 5 | 实现数据库读取 + IP 降级 | `get_location()` 三级降级 | 读库→IP→缓存 |
| 6 | 实现 `build_location_section()` | Prompt 段构建函数 | 返回正确文本 |
| 7 | 修改 `prompt.py` 集成位置段 | import + 模板注入 | Prompt 含动态精度信息 |

### Day 3：GUI 集成 + 测试（4h）

| 序号 | 任务 | 产出 | 验收标准 |
|:----:|------|------|----------|
| 8 | 创建 `LocationMapWidget` | 地图显示组件 | 显示带标记地图 |
| 9 | 修改 `settings_panel.py` | 地理感知设置区 | UI 正确显示 |
| 10 | 添加配置项 | config 读写 | 启停开关生效 |
| 11 | 全流程测试 | 集成测试 | Qt→DB→AAA→Prompt→LLM |

### 合计：约 1.5 个工作日（11h）

***

## 八、验收标准

### 8.1 功能验收

- [ ] **Qt 定位**：GUI 启动后 QtLocationProvider 正常获取系统定位
- [ ] **数据库写入**：Qt 定位结果正确写入 shared/chatbot.db
- [ ] **AAA 读取**：AAA 节点能读取 GUI 写入的高精度位置
- [ ] **IP 降级**：Qt 定位不可用时自动降级 IP 定位
- [ ] **多源降级**：主 IP 源失败时自动切换备源
- [ ] **去重存储**：位置不变时仅更新时间戳
- [ ] **Prompt 注入**：AAA 节点 Prompt 包含当前位置及动态精度
- [ ] **LLM 感知**：AI 能根据精度等级给出适当回答
- [ ] **GUI 显示**：设置页显示带标记的静态地图
- [ ] **手动刷新**：刷新按钮立即更新位置
- [ ] **隐私开关**：禁用后 Prompt/GUI 都不显示位置

### 8.2 精度验收

- [ ] **有 GPS 设备**：精度 ≤ 50m，source = "qt_gps"
- [ ] **有 Wi-Fi 无 GPS**：精度 ≤ 500m，source = "qt_wifi"
- [ ] **无 Wi-Fi/GPS**：精度 5~10km，source = "ip"
- [ ] **精度等级动态显示**：Prompt 中 accuracy_level 与实际一致

### 8.3 非功能验收

- [ ] **零新第三方依赖**：仅使用 Python 标准库 + 现有 PySide6
- [ ] **零体积增长**：不引入新的第三方 pip 包
- [ ] **响应速度**：IP 定位请求超时 ≤ 5 秒
- [ ] **容错性**：Qt 定位失败不影响主对话流程
- [ ] **线程安全**：多线程环境下数据一致
- [ ] **跨平台**：Windows/macOS/Linux 均可运行（Qt 部分）

### 8.4 边界测试

- [ ] Qt 定位初始化失败 → 日志警告，继续 IP 降级
- [ ] Qt 定位返回无城市名 → Prompt 显示坐标替代
- [ ] 网络断开 → 返回上次缓存
- [ ] 所有 IP 源异常 → 返回空，不崩溃
- [ ] 用户禁用 → Prompt 不含位置
- [ ] 位置过时 → Prompt 标记"可能已过时"

### 8.5 验收方法与结论判定

> 本小节将 8.1-8.4 的验收项映射到具体可执行的验证方法，并给出结论判定标准。

#### A. 验收项 → 验证方法映射

| 验收项（来自 8.1-8.4） | 验证方法 | 预期证据 | 类型 |
|------|---------|---------|:----:|
| Qt 定位正常获取 | 启动 GUI，查看日志 `[QtLocation] 定位持续更新已启动`；30s 内出现 `[QtLocation] 位置更新: Xm (qt_xxx)` | 日志含位置更新记录 | 核心 |
| 数据库写入 | `sqlite3 chatbot.db "SELECT content,created_at,status FROM long_term_memory WHERE entity='current_location' ORDER BY created_at DESC LIMIT 1"` | 返回 JSON 含 latitude/longitude/accuracy/source | 核心 |
| AAA 读取高精度位置 | 查看 AAA 节点日志或调试输出 `LocationManager._read_latest_from_db()` 返回非 None | 日志显示读取成功 | 核心 |
| IP 降级生效 | 在无 Qt 定位环境（或禁用 Qt）下启动，查看 AAA 日志 `[Location] xxx 获取成功` | source 字段为 "ip" | 核心 |
| 多源降级切换 | mock 主 IP 源失败，观察日志切换到备源 | 日志显示 `ip-api.com 获取失败` 后 `ipapi.co` 成功 | 非核心 |
| 去重存储 | 同一位置连续两次 `get_location()`，查 DB | 第二次仅 `json_set` 更新 timestamp，无新 INSERT | 非核心 |
| Prompt 注入位置 | 查看完整 Prompt 含 `### 当前位置信息（系统提供）` 段 | Prompt 文本含位置段 | 核心 |
| 动态精度显示 | 对比 Prompt 中 `精度:` 行与 DB 中 accuracy 值 | 等级描述（精确/街区/城市）与数值一致 | 核心 |
| LLM 感知位置 | 对话问"我在哪里"，AI 按精度等级回答 | AI 回答城市名（城市级）或区域（街区级） | 核心 |
| GUI 显示地图 | 设置页地理感知区显示带红色标记的静态地图 | 图片正常加载，非占位符 | 核心 |
| 手动刷新 | 点击"刷新位置"按钮 | 位置信息栏更新，地图刷新 | 核心 |
| 隐私开关 | 取消勾选"启用位置信息" → 对话问位置 | Prompt 不含位置段，AI 回答"不知道" | 核心 |
| 30s 超时降级 | Qt startUpdates 后 30s 无信号 | 日志显示超时降级到 IP | 非核心 |
| 无城市名容错 | Qt 定位无城市 → 查 Prompt | 显示"坐标 xxx°E, xxx°N (无城市名)" | 非核心 |
| 网络断开兜底 | 断网后 `get_location()` | 返回缓存，`from_cache=True`，`stale` 按时间判定 | 核心 |
| 位置过时标记 | 缓存 >10min 时查 Prompt | 含"位置可能已过时" | 非核心 |

#### B. 验收结论判定标准

| 验收等级 | 判定标准 |
|------|---------|
| **通过** | 上表所有"核心"项（共 10 项）全部通过 |
| **附条件通过** | 核心项全通过，非核心项 ≤2 项不通过且有补救计划 |
| **不通过** | 任一核心项不通过 |

#### C. 验收记录模板

```
功能名称：AI 定位信息功能（v1.3）
验收日期：____-____-____
验收人员：__________
验收环境：☐ Win10+ 桌面  ☐ 笔记本  ☐ 台式机（无Wi-Fi）  ☐ 其他：____
Qt 定位：☐ 可用（精度 ____m）  ☐ 不可用（走 IP 降级）

核心项：
  ☐ Qt定位获取  ☐ DB写入  ☐ AAA读取  ☐ IP降级  ☐ Prompt注入
  ☐ 动态精度    ☐ LLM感知  ☐ GUI地图  ☐ 手动刷新  ☐ 隐私开关
  ☐ 网络断开兜底
非核心项：
  ☐ 多源切换  ☐ 去重存储  ☐ 30s超时降级  ☐ 无城市名容错  ☐ 位置过时标记

验收结论：☐ 通过  ☐ 附条件通过  ☐ 不通过
问题记录：
_______________________________________________
```

### 8.6 补充验收（v1.4 经验补强：跨层一致性/版本兼容/数据边界/LLM 容错）

> 本节源自定位功能实际运行中暴露的 4 类验收盲区：跨层值不一致、依赖版本变更、
> 数据表职责混用、LLM 输出语义垃圾。所有 PLAN 验收均应补全以下 4 个维度。

#### A. 端到端链路一致性验收（新增）

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| L1 | 全链路值一致性 | 1) GUI Qt 定位更新后，查 DB active 记录；2) AAA `_read_latest_from_db()` 返回值；3) 查看完整 Prompt 中位置段 | 三处坐标/精度/城市完全一致 | DB 记录 == AAA 返回值 == Prompt 显示值 | 核心 |
| L2 | Qt/IP 优先级正确 | 1) Qt 定位刚写入（<5min）；2) 触发 AAA IP 定位 | 坐标保持 Qt 值（source=qt_*），不被 IP 覆盖 | 最终 active 记录 source 以 qt_ 开头 | 核心 |
| L3 | 精度差异不误导城市 | 1) Qt 坐标在习水县（28.33N,106.19E）；2) IP 城市为贵阳市 | 城市名按坐标逆地理编码为习水县，而非 IP 的贵阳市 | Prompt 城市字段不含 IP 错误城市名 | 核心 |

#### B. 版本兼容与方言验收（新增）

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| L4 | PySide6 枚举兼容 | 在 6.11.1（及一个旧版本）下启动 GUI Qt 定位 | 不抛 `QGeoCoordinate has no attribute` 类错误 | 双版本均可获取精度值 | 核心 |
| L5 | SQLite 方言检查 | 执行含 `UPDATE ... ORDER BY` 的语句 | 抛语法错误（SQLite 不支持） | 代码中 UPDATE 一律先 SELECT 定位再按 id 更新 | 核心 |

#### C. 数据表职责边界验收（新增）

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| L6 | 定位数据独立表 | 定位更新后查库 | 记录写入 `location_history`，`long_term_memory` 不新增定位记录 | long_term_memory 无 entity='current_location' 新记录 | 核心 |
| L7 | 知识面板不展示定位表 | 打开知识面板 | location_history 不出现记忆卡片/筛选按钮 | _IGNORED_TABLES 含 location_history | 核心 |
| L8 | 记忆图谱不含定位 | 触发图谱重建 | 图谱节点/边不含定位数据 | 图谱数据源不含 location_history | 非核心 |

#### D. LLM 语义容错验收（新增）

| 编号 | 验收项 | 操作步骤 | 预期结果 | 通过标准 | 类型 |
|:----:|------|---------|---------|---------|:----:|
| L9 | 定位噪音不归档 | LLM 输出 `【环境记忆】当前定位精度为街区级别，时效在5分钟内。` | 该内容被过滤，不写入 long_term_memory | long_term_memory 无"定位精度/时效"类新记录 | 核心 |
| L10 | 占位值不写入 | LLM 输出 `【环境记忆】无` / 空 | 跳过写入 | 无 content='无' 的新记录 | 非核心 |

***

## 九、测试方案

### 9.1 单元测试

```python
# tests/test_location_manager.py

class TestLocationManager:
    # GPSLocation 数据类
    def test_accuracy_level_exact(self): ...      # ≤100m → "精确位置"
    def test_accuracy_level_block(self): ...      # ≤1000m → "街区级别"
    def test_accuracy_level_city(self): ...        # >1000m → "城市级别"
    def test_source_description(self): ...        # qt_gps/qt_wifi/ip/cache 映射

    # IP 定位源解析
    def test_parse_ip_api_success(self): ...
    def test_parse_ipapi_success(self): ...
    def test_parse_ip_sb_success(self): ...
    def test_parse_invalid_response(self): ...

    # 多源降级
    def test_fallback_when_primary_fails(self): ...
    def test_all_sources_fail(self): ...

    # 数据库读取
    def test_read_latest_from_db(self): ...
    def test_read_empty_db(self): ...

    # 去重逻辑
    def test_location_unchanged_updates_timestamp(self): ...
    def test_location_changed_creates_new_record(self): ...

    # 缓存
    def test_cache_returns_fresh_data(self): ...
    def test_force_refresh_ignores_cache(self): ...

    # 开关
    def test_disabled_returns_error(self): ...

    # Prompt 段构建
    def test_build_location_section_with_data(self): ...
    def test_build_location_section_empty(self): ...
    def test_build_without_city_name(self): ...  # Qt 定位无城市名场景
    def test_accuracy_descriptions(self): ...


# tests/test_qt_location_provider.py

class TestQtLocationProvider:
    def test_init_creates_source(self): ...
    def test_init_fails_gracefully(self): ...  # 无定位环境
    def test_start_and_stop(self): ...
    def test_position_update_writes_db(self): ...
    def test_position_error_logs(self): ...
    def test_accuracy_classification(self): ...  # GPS/Wi-Fi/Cell
```

### 9.2 集成测试

```python
# tests/test_location_integration.py

class TestLocationIntegration:
    def test_full_pipeline_qt_to_aaa(self):
        """Qt 定位 → DB → AAA 读取 → Prompt → LLM 感知"""
        # 1. 模拟 Qt 写入高精度位置
        # 2. AAA 节点读取数据库
        # 3. 验证 accuracy_level 正确
        ...

    def test_ip_fallback_when_qt_unavailable(self):
        """Qt 不可用时降级 IP"""
        # mock Qt 失败
        # 验证自动 IP 降级
        ...

    def test_prompt_contains_dynamic_accuracy(self):
        """验证 Prompt 含动态精度等级"""
        ...

    def test_gui_shows_location(self):
        """验证 GUI 组件"""
        ...
```

***

## 十、风险与降级策略

| 风险 | 触发条件 | 缓解措施 |
|------|---------|---------|
| Qt 定位源为 nullptr | Win7/8、Linux 无 GeoClue、权限被拒、位置服务关闭 | 日志警告，自动降级 IP 定位（主路径不受影响） |
| Qt 定位无信号 | startUpdates() 后 positionUpdated 未触发 | 30s 超时后降级 IP；期间不阻塞主流程 |
| Qt 定位精度异常 | 返回 accuracy > 5000m（系统实际也不知道位置） | 精度值异常时强制降级 IP 定位 |
| Qt 定位无城市名 | GPS/Wi-Fi 定位只给坐标无地理编码 | 显示坐标替代；IP 降级时补充城市名 |
| IP 精度不足 | VPN/代理/海外节点 | Prompt 中标注精度等级为"城市级别"，AI 仅回答城市名，不编造精确地址 |
| 服务不可用 | 所有 IP 源宕机 | 返回最近缓存，标记 `stale`；Prompt 提示"位置可能已过时" |
| 限流被封 | 短时间大量请求 | 多源轮换（3 个源轮换间隔 ≥1s） |
| 隐私问题 | 用户不希望暴露位置 | 一键开关，关闭即清除历史 |
| 高德 Key 失效 | Key 过期或额度用尽 | 自动降级 OpenStreetMap 静态地图 |
| 数据库损坏 | 硬件故障或并发写冲突 | 不影响主流程，仅丢历史；prompt 不含位置段 |
| 冷启动慢 | Qt 首次获取 GPS 位置需 10~30s | 启动时立即请求，先用 IP 定位填充，后续 Qt 结果到达后平滑升级 |
| 权限弹窗 | 首次使用 Qt 定位时系统弹窗请求权限 | 在 GUI 设置页引导用户开启；用户拒绝则自动走 IP 路径 |

### Qt 定位失败的检测与降级流程

```
┌───────────────────────────────────────────────────────────┐
│  QtLocationProvider._init_source()                         │
│                                                             │
│  1. source = QGeoPositionInfoSource.createDefaultSource()  │
│     ├─ source == nullptr → 标记 qt_available = False      │
│     │   └─ 记录日志："Qt 定位源不可用，将使用 IP 降级"       │
│     └─ source != nullptr → 继续检查                         │
│                                                             │
│  2. source.supportedPositioningMethods()                   │
│     ├─ 返回 NoPositioningMethods → 标记 qt_available=False │
│     └─ 有可用方法 → 设置 qt_available = True                │
│                                                             │
│  3. 连接信号：positionUpdated / positionError              │
│                                                             │
│  4. start() 启动后 30s 内无 positionUpdated 触发            │
│     └─ 超时降级：Qt 路径标记为不稳定，AAA 节点直接走 IP    │
└───────────────────────────────────────────────────────────┘
```

### 降级路径

```
正常路径（Qt 可用）：
  GUI 启动 → QtLocationProvider.start()
    → Qt 系统定位 (5~50m 或 50~500m)
    → 写入共享数据库 (source="qt_gps" / "qt_wifi" / "qt_cell")
    → AAA 节点读取高精度位置 → Prompt 动态精度描述

降级路径 1（Qt 不可用，最常见的降级）：
  createDefaultSource() 返回 nullptr 或无可用方法
    → GUI 层日志警告，不写入数据库
    → AAA 节点 get_location() 走 IP 定位路径
    → 3 源轮换获取 (source="ip", accuracy=5000~10000m)
    → Prompt 显示"城市级别"精度

降级路径 2（Qt 超时）：
  Qt startUpdates() 后 30s 无信号
    → 标记 Qt 路径为不稳定
    → 继续使用上次 Qt 位置（若在有效期内）
    → 过期则走 IP 降级

降级路径 3（IP 也失败）：
  所有 IP 源均请求失败
    → 返回数据库最后一次缓存位置 (from_cache=True, stale=False)
    → 若缓存已过期 (>10min)，标记 stale=True
    → Prompt 提示"位置可能已过时"

降级路径 4（完全不可用）：
  Qt 不可用 + 所有 IP 失败 + 无缓存
    → 返回空 (LocationResult.success=False)
    → Prompt 不含位置段，AI 不回答位置相关问题

降级路径 5（用户主动禁用）：
  用户在设置页关闭"启用位置信息"
    → QtLocationProvider.stop()
    → LocationManager.set_enabled(False)
    → Prompt 不含位置段，GUI 不显示
    → LLM 不感知位置，AI 不回答位置相关问题
```

### 降级体验保障

| 降级场景 | 用户体验 | AI 表现 |
|:--------:|:--------:|:--------:|
| Qt 精确定位 → Qt 街区级 | 无感知 | 精度描述自动调整 |
| Qt → IP 城市级 | 无感知 | AI 仅回答城市名，不说具体位置 |
| IP → 缓存（新鲜） | 无感知 | AI 正常回答，时效描述显示"X 分钟前更新" |
| IP → 缓存（过时） | 可能注意到回答重复 | AI 主动提示"位置信息可能已过时" |
| 完全不可用 | 无位置显示 | AI 诚实回答"我不知道你在哪里" |
| 用户禁用 | 设置页标记关闭 | AI 不感知位置 |

***

## 附录：定位源速查

### A. Qt 系统定位（一级定位源）

| 项目 | 说明 |
|------|------|
| API | `PySide6.QtPositioning.QGeoPositionInfoSource` |
| 创建方式 | `createDefaultSource(self)` 自动适配平台 |
| 精度范围 | 5~50m (GPS) / 50~500m (Wi-Fi 指纹) |
| 依赖 | PySide6 自带，零额外安装 |
| 跨平台 | Windows 10+ / macOS / Linux (GeoClue) / Android / iOS |
| 用户配置 | 首次可能请求系统位置权限 |
| 可用性检测 | `source == nullptr` 或 `supportedPositioningMethods() == NoPositioningMethods` |
| 超时检测 | `startUpdates()` 后 30s 无 `positionUpdated` 信号 |

**关键 API 方法：**

```python
from PySide6.QtPositioning import QGeoPositionInfoSource, QGeoCoordinate

# 创建默认源（自动适配平台）
source = QGeoPositionInfoSource.createDefaultSource(self)

# 检查可用性
if source:
    methods = source.supportedPositioningMethods()
    # methods 是 PositioningMethods 枚举值
    # SatellitePositioningMethods (GPS/GNSS)
    # NonSatellitePositioningMethods (Wi-Fi/基站)
    # AllPositioningMethods
    # NoPositioningMethods (不可用)
    
    # 配置更新参数
    source.setUpdateInterval(300000)  # 5 分钟
    source.setRequestTimeout(10000)   # 10 秒
    
    # 信号连接
    source.positionUpdated.connect(on_position)
    source.positionError.connect(on_error)
    
    # 启动
    source.startUpdates()
    source.requestUpdate(5000)  # 立即请求一次
else:
    # Qt 定位不可用，走 IP 降级
    pass
```

### B. IP 定位源（二级降级）

| 服务 | URL | 精度 | 额度 | 特点 | 解析字段 |
|------|-----|------|------|------|---------|
| ip-api.com | `http://ip-api.com/json/` | 5km | 45次/小时 | 快、稳定、支持中文 | lat, lon, city, regionName, country |
| ipapi.co | `https://ipapi.co/json/` | 10km | 50000次/天 | 额度大 | latitude, longitude, city, region, country_name |
| ip.sb | `https://api.ip.sb/geoip` | 5km | 无限次 | 无限制、隐私友好 | data.latitude, data.longitude, data.city |

**IP 源轮换策略：**
1. 按优先级顺序依次尝试（ip-api → ipapi → ip.sb）
2. 单次请求间隔 ≥ 1 秒（避免触发限流）
3. 某源失败后切换到下一源，下次请求从失败源的下一个开始（环形轮换）
4. 成功获取后重置轮换索引

### C. 地图服务

| 服务 | URL | 额度 | 说明 |
|------|-----|------|------|
| 高德静态地图 | `https://restapi.amap.com/v3/staticmap` | 需 Key | 主用，中文地图，支持精确标记 |
| OpenStreetMap | `https://staticmap.openstreetmap.de/staticmap.php` | 约 1次/秒 | 免费兜底，无 Key 需求 |

### D. 三级降级精度对比

| 等级 | 精度 | 来源 | 典型设备 | Prompt 描述 |
|:----:|:----:|:----:|:--------:|:----------:|
| L1 精确 | 5~50m | Qt GPS | 手机户外 | "你在 XX 市 XX 区 XX 路附近" |
| L2 街区 | 50~500m | Qt Wi-Fi 指纹 | 笔记本/桌面 (Win10+) | "你在 XX 市 XX 区一带" |
| L3 城市 | 5~10km | IP 定位 | 台式机/VPN | "你在 XX 市" |

### 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.3 | 2026-08-08 | 完善 Qt 定位平台兼容性说明、详细降级流程、风险矩阵 |
| v1.2 | 2026-08-07 | 新增 Qt QGeoPositionInfoSource 作为一级定位源，实现跨平台动态精度降级 |
| v1.1 | 2026-08-07 | 修正架构归属：定位模块归 AAA 认知节点 |

***

*文档版本：v1.3 | 完善 Qt 定位平台兼容性说明，详细降级流程与风险矩阵，纯 Qt + IP API 方案*
*关联设计文档：`[PLAN]-AI定位信息功能设计方案.md`、`[PLAN]-AI世界感知记忆系统设计方案.md`*
