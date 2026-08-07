"""
AI 定位信息模块 (v1.3)

AAA 认知节点内部模块，与 memos.py / diary.py 并列。
为 AI 提供当前地理位置感知能力。

特性：
- 优先读取 GUI 层 Qt 定位写入的高精度位置（GPS/Wi-Fi）
- 位置过时(>5min)时自动尝试 IP 定位刷新
- 3 个免费 IP 定位源自动轮换降级
- 500m 移动阈值去重存储
- 独立 location_history 表存储（v5.0，不再复用 long_term_memory）
- 线程安全（RLock）
- 零新依赖（仅 Python 标准库）
"""
import time
import json
import math
import sqlite3
import threading
import logging
import urllib.request
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, List

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────
LOCATION_TABLE = "location_history"   # v5.0: 定位独立表

DEFAULT_UPDATE_INTERVAL = 300   # 5 分钟自动更新
DEFAULT_MOVE_THRESHOLD = 500    # 500 米视为位置变化
REQUEST_TIMEOUT = 5             # 网络请求超时
STALE_THRESHOLD = 600           # 10 分钟视为过时

# 默认身份键（与 db.py 保持一致）
_IDENTITY_KEY_DEFAULT = "gui:default"


# ════════════════════════════════════════════════════════════════
#  数据结构
# ════════════════════════════════════════════════════════════════

@dataclass
class GPSLocation:
    """GPS 位置数据"""
    latitude: float
    longitude: float
    accuracy: float          # 精度（米），实际动态值
    city: Optional[str] = None
    region: Optional[str] = None
    country: Optional[str] = None
    street: Optional[str] = None     # v1.5: 街道（Photon 逆地理编码）
    district: Optional[str] = None   # v1.5: 区/街道级行政单位
    source: str = "ip"       # "qt_gps" / "qt_wifi" / "qt_cell" / "qt_unknown" / "ip" / "cache"
    timestamp: float = 0     # 数据采集时刻（unix 时间戳）

    def to_dict(self) -> dict:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "accuracy": self.accuracy,
            "city": self.city,
            "region": self.region,
            "country": self.country,
            "street": self.street,
            "district": self.district,
            "source": self.source,
            "timestamp": self.timestamp or time.time(),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @property
    def is_fresh(self) -> bool:
        """位置信息是否在有效期内（5 分钟）"""
        return (time.time() - self.timestamp) < DEFAULT_UPDATE_INTERVAL

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


@dataclass
class LocationResult:
    """定位结果"""
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
    # v1.3.1 调整顺序：ip.sb 优先（IPv6支持好，国内IP识别更准），
    #               ip-api.com 次之（IPv4有时识别为骨干网出口城市），
    #               ipapi.co 兜底（免费配额低易403）
    IP_SOURCES = [
        {"name": "ip.sb",      "url": "https://api.ip.sb/geoip",  "parser": "_parse_ip_sb"},
        {"name": "ip-api.com", "url": "http://ip-api.com/json/",  "parser": "_parse_ip_api"},
        {"name": "ipapi.co",   "url": "https://ipapi.co/json/",   "parser": "_parse_ipapi"},
    ]

    @staticmethod
    def _reverse_geocode_cached(lat: float, lng: float) -> Optional[tuple]:
        """坐标 → (city, region, country)，带内存缓存"""
        return _reverse_geocode(lat, lng)

    def __init__(self, db_path: str, config: dict = None,
                 identity_key: str = _IDENTITY_KEY_DEFAULT):
        self._db_path = db_path
        self._config = config or {}
        self._enabled = self._config.get("location_enabled", True)
        self._update_interval = self._config.get(
            "location_update_interval", DEFAULT_UPDATE_INTERVAL)
        self._identity_key = identity_key

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
        """获取当前位置（Qt 高精度定位优先 → IP 多源兜底 → 缓存兜底）

        v1.5.2: 顶层定位（Qt）正常时，兜底（IP）不再触发。
        - 数据库中存在新鲜的 qt_ 记录时，无论 force_refresh 与否都直接返回，
          不再发起 IP 请求（修复 Qt 定位正常却仍触发 ipapi.co 等 IP 源的问题）
        - 仅当无 Qt 记录、或 Qt 记录过期（GUI 定位已停止）时才走 IP 兜底
        """
        with self._lock:
            if not self._enabled:
                return LocationResult(success=False, error="定位功能已禁用")

            # 1. 数据库中的高精度位置（GUI 层 Qt 定位写入）优先
            db_location = self._read_latest_from_db()
            if db_location:
                age = time.time() - db_location.timestamp
                # Qt 记录新鲜 → 顶层定位正常，直接返回，不触发 IP 兜底
                qt_fresh = db_location.source.startswith("qt_") and age < self._update_interval
                # 非 Qt 记录（如 IP 缓存）且非强制刷新 → 复用缓存
                cache_fresh = (not force_refresh) and age < self._update_interval
                if qt_fresh or cache_fresh:
                    self._current = db_location
                    self._last_fetch_time = db_location.timestamp
                    return LocationResult(success=True, location=db_location)

            # 2. 尝试 IP 定位（多源交叉验证，避免单一源错误）
            #    v1.3.1: 不再是"第一个成功就停止"，也不再按 _source_index 轮转，
            #    而是始终按 IP_SOURCES 优先级顺序从0开始遍历，收集所有成功结果，
            #    然后通过省份一致性选出最可信的；这样即使有跨省差异的异常结果，
            #    results[0] 也一定是优先级最高源（ip.sb）的结果作为兜底。
            all_results: List[GPSLocation] = []
            for i, source in enumerate(self.IP_SOURCES):
                location = self._fetch_from_source(source)
                if location:
                    all_results.append(location)
                    # 已有2个源省份一致 → 停止后续请求（省流量+省时间）
                    if len(all_results) >= 2:
                        r0, r1 = all_results[0], all_results[1]
                        if (r0.region == r1.region) or (r0.city == r1.city):
                            break
            # 更新轮转索引，供未来可能的单源模式复用（不影响当前顺序遍历）
            self._source_index = (self._source_index + len(all_results)) % len(self.IP_SOURCES)

            # 从多源结果中选出最可信的
            best_location = self._select_best_location(all_results)
            if best_location:
                self._handle_location_update(best_location)
                # v1.3.2: _handle_location_update 可能保留了 Qt 定位而不覆盖，
                # 此时 self._current 是 Qt 定位（更高精度），应返回它而非 IP 结果
                return LocationResult(success=True, location=self._current)

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
        """获取缓存位置（不触发网络请求）"""
        with self._lock:
            return self._current

    def get_location_history(self, limit: int = 20) -> list:
        """查询历史位置记录"""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    "SELECT latitude, longitude, city, region, country, "
                    "source, accuracy, status, created_at "
                    f"FROM {LOCATION_TABLE} "
                    "WHERE identity_key=? "
                    "ORDER BY id DESC LIMIT ?",
                    (self._identity_key, limit),
                )
                history = []
                for row in cursor.fetchall():
                    history.append({
                        "lat": row["latitude"],
                        "lng": row["longitude"],
                        "city": row["city"],
                        "source": row["source"],
                        "accuracy": row["accuracy"],
                        "status": row["status"],
                        "time": row["created_at"],
                    })
                return history
        except Exception as e:
            logger.error(f"[Location] 查询历史失败: {e}")
            return []

    def clear_location_history(self) -> int:
        """清除历史记录，返回清除条数"""
        try:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    f"DELETE FROM {LOCATION_TABLE} WHERE identity_key=?",
                    (self._identity_key,),
                )
                conn.commit()
                return cursor.rowcount
        except Exception as e:
            logger.error(f"[Location] 清除历史失败: {e}")
            return 0

    # ── 内部：数据库读取 ────────────────────────────────────

    def _read_latest_from_db(self) -> Optional[GPSLocation]:
        """从数据库读取最新位置（由 GUI 层 Qt 定位写入）"""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    f"SELECT latitude, longitude, accuracy, city, region, "
                    "country, source, created_at "
                    f"FROM {LOCATION_TABLE} "
                    "WHERE status='active' AND identity_key=? "
                    "ORDER BY id DESC LIMIT 1",
                    (self._identity_key,),
                )
                row = cursor.fetchone()
                if row:
                    # v1.4: Qt 定位通常无城市名，尝试逆地理编码补全
                    # （IP 城市名精度差：习水县坐标会被标成贵阳，故不用 IP 补充）
                    city, region, country = (row["city"], row["region"], row["country"])
                    street = row["street"] if "street" in row.keys() else None
                    district = row["district"] if "district" in row.keys() else None
                    source = row["source"]
                    if source.startswith("qt_") and not city and row["latitude"] is not None:
                        lat = float(row["latitude"])
                        lng = float(row["longitude"])
                        reverse = self._reverse_geocode_cached(lat, lng)
                        if reverse and (reverse[0] or reverse[1]):
                            city, region, country, street, district = reverse
                            self._write_city_to_db(lat, lng, city, region, country, street, district)
                            logger.info(
                                "[Location] Qt 定位逆地理编码: "
                                f"{city}, {region}"
                            )
                    return GPSLocation(
                        latitude=float(row["latitude"]),
                        longitude=float(row["longitude"]),
                        accuracy=float(row["accuracy"] or 5000),
                        city=city,
                        region=region,
                        country=country,
                        street=street,
                        district=district,
                        source=source,
                        timestamp=self._parse_db_time(row["created_at"]),
                    )
        except Exception as e:
            logger.error(f"[Location] 读取数据库位置失败: {e}")
        return None

    # ── 内部：多源结果交叉验证选择 ────────────────────────────────

    def _select_best_location(self, results: List[GPSLocation]) -> Optional[GPSLocation]:
        """
        从多个IP定位结果中选出最可信的一个。

        选择策略（按优先级）：
        1. 只有1个结果 → 直接用
        2. 有2+个结果省份一致 → 选组内精度最高的（核心交叉验证规则）
        3. 省份不一致但国家一致 → 直接选第一个（即 IP_SOURCES 优先级最高的源，
           因为我们已按"国内识别更准"排序过优先级，避免错误聚类）
        4. 完全不一致 → 兜底用第一个
        """
        if not results:
            return None
        if len(results) == 1:
            return results[0]

        # 按省份分组
        region_groups: dict = {}
        for r in results:
            key = (r.country or "", r.region or "")
            if key not in region_groups:
                region_groups[key] = []
            region_groups[key].append(r)

        # 找最大一致组（size≥2 才算可信一致）
        best_group = None
        best_size = 0
        for group in region_groups.values():
            if len(group) > best_size:
                best_size = len(group)
                best_group = group
        if best_group and best_size >= 2:
            return min(best_group, key=lambda r: r.accuracy)

        # 省份不一致：直接用优先级最高源的结果（列表第一个）
        # 不要用"距离聚类中心最近"——当两个源跨省差异时，聚类中心无意义
        return results[0]

    # ── 内部：网络请求 ────────────────────────────────────────

    def _fetch_from_source(self, source: dict) -> Optional[GPSLocation]:
        """从单个 IP 源获取定位"""
        last_attempt = self._source_cooldown.get(source["name"], 0)
        if (time.time() - last_attempt) < 1.0:
            return None
        self._source_cooldown[source["name"]] = time.time()

        try:
            req = urllib.request.Request(
                source["url"],
                headers={"User-Agent": "BNOS-AI/1.0 (+location-module)"},
            )
            response = urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT)
            data = json.loads(response.read().decode("utf-8"))
            parser = getattr(self, source["parser"])
            return parser(data, source["name"])
        except Exception as e:
            logger.warning(f"[Location] {source['name']} 获取失败: {e}")
            return None

    def _parse_ip_api(self, data: dict, source_name: str) -> Optional[GPSLocation]:
        """解析 ip-api.com 响应"""
        if data.get("status") != "success":
            return None
        return GPSLocation(
            latitude=float(data["lat"]),
            longitude=float(data["lon"]),
            accuracy=5000,
            city=data.get("city"),
            region=data.get("regionName"),
            country=data.get("country"),
            source="ip",
            timestamp=time.time(),
        )

    def _parse_ipapi(self, data: dict, source_name: str) -> Optional[GPSLocation]:
        """解析 ipapi.co 响应"""
        if not data.get("latitude"):
            return None
        return GPSLocation(
            latitude=float(data["latitude"]),
            longitude=float(data["longitude"]),
            accuracy=10000,
            city=data.get("city"),
            region=data.get("region"),
            country=data.get("country_name"),
            source="ip",
            timestamp=time.time(),
        )

    def _parse_ip_sb(self, data: dict, source_name: str) -> Optional[GPSLocation]:
        """解析 ip.sb 响应"""
        # ip.sb 可能直接返回字段，也可能包在 data 字段里
        info = data.get("data", data) if isinstance(data, dict) else {}
        if not info.get("latitude"):
            return None
        return GPSLocation(
            latitude=float(info["latitude"]),
            longitude=float(info["longitude"]),
            accuracy=5000,
            city=info.get("city"),
            region=info.get("region"),
            country=info.get("country_name") or info.get("country"),
            source="ip",
            timestamp=time.time(),
        )

    # ── 内部：位置更新与持久化 ────────────────────────────────

    @staticmethod
    def _haversine_distance(lat1, lng1, lat2, lng2) -> float:
        """Haversine 公式计算两点距离（米）"""
        R = 6371000
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlng / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _is_location_changed(self, old: GPSLocation, new: GPSLocation) -> bool:
        """判断位置是否发生变化"""
        if (new.city or "") != (old.city or "") or \
                (new.country or "") != (old.country or ""):
            return True
        distance = self._haversine_distance(
            old.latitude, old.longitude,
            new.latitude, new.longitude,
        )
        return distance > self.MOVE_THRESHOLD

    def _handle_location_update(self, new_location: GPSLocation):
        """处理位置更新（去重 + 持久化）

        v1.4: IP 定位不应覆盖新鲜的 Qt 高精度定位，也不应把 IP 城市名
        写入 Qt 记录（IP 为城市级 5000m 精度，坐标与城市可能不匹配，
        如习水县坐标会被 IP 标为贵阳）。
        """
        old = self._current

        # v1.4: IP 定位不应覆盖新鲜的 Qt 高精度定位
        if new_location.source == "ip":
            db_location = self._read_latest_from_db()
            if db_location and db_location.source.startswith("qt_"):
                db_age = time.time() - db_location.timestamp
                if db_age < self._update_interval:
                    # Qt 位置仍然新鲜 → 保留 Qt 定位，不覆盖、不补充 IP 城市
                    self._current = db_location
                    self._last_fetch_time = time.time()
                    return  # 不写入 IP 记录

        self._current = new_location
        self._last_fetch_time = time.time()

        if old and not self._is_location_changed(old, new_location):
            self._touch_timestamp()
        else:
            self._write_new_record(new_location)

    def _load_cached_location(self):
        """从数据库加载最新的位置缓存"""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    f"SELECT latitude, longitude, accuracy, city, region, "
                    "country, street, district, source, created_at "
                    f"FROM {LOCATION_TABLE} "
                    "WHERE status='active' AND identity_key=? "
                    "ORDER BY id DESC LIMIT 1",
                    (self._identity_key,),
                )
                row = cursor.fetchone()
                if row:
                    ts = self._parse_db_time(row["created_at"])
                    self._current = GPSLocation(
                        latitude=float(row["latitude"]),
                        longitude=float(row["longitude"]),
                        accuracy=float(row["accuracy"] or 5000),
                        city=row["city"],
                        region=row["region"],
                        country=row["country"],
                        street=row["street"] if "street" in row.keys() else None,
                        district=row["district"] if "district" in row.keys() else None,
                        source=row["source"],
                        timestamp=ts,
                    )
                    self._last_fetch_time = ts
        except Exception as e:
            logger.error(f"[Location] 加载缓存失败: {e}")

    @staticmethod
    def _parse_db_time(time_str) -> float:
        """将 DB 中的时间字符串转为 unix 时间戳（兼容 TEXT/REAL 格式）"""
        try:
            return datetime.strptime(str(time_str), "%Y-%m-%d %H:%M:%S").timestamp()
        except Exception:
            try:
                return float(time_str)
            except Exception:
                return time.time()

    def _write_city_to_db(self, lat: float, lng: float,
                          city: str, region: str, country: str,
                          street: str = None, district: str = None):
        """将逆地理编码的城市名写入 active 定位记录（按坐标匹配，不覆盖坐标）

        v1.5: 支持街道/区级信息写入（street/district）。
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    f"UPDATE {LOCATION_TABLE} SET city=?, region=?, country=?, "
                    "street=COALESCE(street, ?), district=COALESCE(district, ?) "
                    "WHERE status='active' AND identity_key=? "
                    "AND ABS(latitude - ?) < 0.001 AND ABS(longitude - ?) < 0.001",
                    (city, region, country, street, district,
                     self._identity_key, lat, lng),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"[Location] 写入城市信息失败: {e}")

    def _supplement_qt_location(self, qt_location: GPSLocation,
                                ip_location: GPSLocation = None):
        """用逆地理编码补充 Qt 定位的城市/街道信息（坐标 → 行政区）

        v1.4: 弃用 IP 城市名补充（IP 为城市级精度，习水坐标会被标成贵阳）。
        v1.5: Photon 优先返回街道级（street/district），BigDataCloud 兜底区县级。
        """
        if qt_location.latitude is None or qt_location.longitude is None:
            return
        reverse = self._reverse_geocode_cached(
            qt_location.latitude, qt_location.longitude) or (None, None, None, None, None)
        city, region, country, street, district = reverse
        if not (city or region):
            return  # 逆地理编码失败则保持无城市名
        try:
            with sqlite3.connect(self._db_path) as conn:
                # SQLite 的 UPDATE 不支持 ORDER BY/LIMIT，
                # 先查出最新的 active 记录 id
                row = conn.execute(
                    f"SELECT id FROM {LOCATION_TABLE} "
                    "WHERE status='active' AND identity_key=? "
                    "ORDER BY id DESC LIMIT 1",
                    (self._identity_key,),
                ).fetchone()
                if row:
                    # 仅补充城市/省份/国家/街道，不修改坐标和精度
                    conn.execute(
                        f"UPDATE {LOCATION_TABLE} SET city=COALESCE(city, ?), "
                        "region=COALESCE(region, ?), country=COALESCE(country, ?), "
                        "street=COALESCE(street, ?), district=COALESCE(district, ?) "
                        "WHERE id=?",
                        (city, region, country, street, district, row[0]),
                    )
                    conn.commit()
                    logger.info(
                        "[Location] Qt 定位已逆地理编码: "
                        f"{city}, {region}"
                    )
        except Exception as e:
            logger.error(f"[Location] 补充 Qt 城市信息失败: {e}")

    def _touch_timestamp(self):
        """位置未变化 → 仅更新时间戳"""
        try:
            new_ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    f"UPDATE {LOCATION_TABLE} SET created_at=? "
                    "WHERE status='active' AND identity_key=?",
                    (new_ts_str, self._identity_key),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"[Location] 更新时间戳失败: {e}")

    def _write_new_record(self, location: GPSLocation):
        """写入新的位置记录（同时标记旧记录为 superseded）"""
        try:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with sqlite3.connect(self._db_path) as conn:
                # 1. 标记旧记录为 superseded
                conn.execute(
                    f"UPDATE {LOCATION_TABLE} SET status='superseded' "
                    "WHERE status='active' AND identity_key=?",
                    (self._identity_key,),
                )
                # 2. 写入新记录（含 street/district）
                conn.execute(
                    f"INSERT INTO {LOCATION_TABLE}("
                    "identity_key, latitude, longitude, accuracy, city, region, "
                    "country, street, district, source, status, created_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (self._identity_key, location.latitude, location.longitude,
                     location.accuracy, location.city, location.region,
                     location.country, location.street, location.district,
                     location.source, "active", now_str),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"[Location] 写入新记录失败: {e}")


# ════════════════════════════════════════════════════════════════
#  Prompt 段构建函数
# ════════════════════════════════════════════════════════════════

# 逆地理编码（坐标 → 行政区）内存缓存: (lat, lng) -> (city, region, country, street, district) | None
_REVERSE_GEO_CACHE: dict = {}
_REVERSE_GEO_URL = ("https://api.bigdatacloud.net/data/reverse-geocode-client"
                    "?latitude={lat}&longitude={lng}&localityLanguage=zh")
_STREET_GEO_URL = "https://photon.komoot.io/reverse?lon={lng}&lat={lat}"


def _reverse_geocode(lat: float, lng: float) -> Optional[tuple]:
    """逆地理编码：精确坐标 → (city, region, country, street, district)

    v1.5.1: 双源合并（修复城市显示为地级市而非县级的问题）。
    - Photon(OSM)：街道级 street/district 精确，但其 city 是地级市（如"遵义市"）
    - BigDataCloud：免费接口的 locality 是县级（如"习水县"，比 Photon 的 city 更精确）
    合并规则：
    - city 优先用 BigDataCloud 的 locality（县级），无则回退 Photon 的 city
    - street/district 用 Photon 的（BigDataCloud 免费接口无街道级）
    - region/country 取任一源
    返回 5 元组，两源全失败返回 None。
    """
    try:
        key = (round(lat, 3), round(lng, 3))
        if key in _REVERSE_GEO_CACHE:
            return _REVERSE_GEO_CACHE[key]

        photon = _reverse_geocode_photon(lat, lng)
        bigdata = _reverse_geocode_bigdata(lat, lng)

        if not (photon or bigdata):
            return None

        p_city, p_region, p_country, p_street, p_district = photon or (None, None, None, None, None)
        b_city, b_region, b_country, _, _ = bigdata or (None, None, None, None, None)

        result = (
            b_city or p_city,          # 县级 locality 优先（习水县），回退地级市（遵义市）
            b_region or p_region,      # 贵州省
            b_country or p_country,    # 中国
            p_street,                  # 赤水西路（仅 Photon 提供）
            p_district,                # 杉王街道（仅 Photon 提供）
        )
        _REVERSE_GEO_CACHE[key] = result
        return result
    except Exception as e:
        logger.warning(f"[Location] 逆地理编码失败: {e}")
        return None


def _reverse_geocode_photon(lat: float, lng: float) -> Optional[tuple]:
    """Photon(OSM) 逆地理编码：坐标 → (city, region, country, street, district)"""
    try:
        url = _STREET_GEO_URL.format(lng=round(lng, 5), lat=round(lat, 5))
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "BNOS-AI/1.0 (+location-module)"},
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        features = data.get("features") or []
        if not features:
            return None
        props = features[0].get("properties", {})
        return (
            props.get("city") or props.get("county") or None,
            props.get("state") or None,
            props.get("country") or None,
            props.get("street") or props.get("name") or None,
            props.get("district") or None,
        )
    except Exception as e:
        logger.warning(f"[Location] Photon 逆地理编码失败: {e}")
        return None


def _reverse_geocode_bigdata(lat: float, lng: float) -> Optional[tuple]:
    """BigDataCloud 逆地理编码（区县级兜底）"""
    try:
        url = _REVERSE_GEO_URL.format(lat=round(lat, 5), lng=round(lng, 5))
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "BNOS-AI/1.0 (+location-module)"},
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return (
            data.get("locality") or data.get("city") or None,
            data.get("principalSubdivision") or None,
            data.get("countryName") or None,
            None,
            None,
        )
    except Exception as e:
        logger.warning(f"[Location] BigDataCloud 逆地理编码失败: {e}")
        return None


def build_location_section(db_path: str, identity_key: str) -> str:
    """构建位置信息 Prompt 段落

    由 AAA 的 prompt.py / main.py 调用，将位置信息注入系统提示词。

    Returns:
        位置信息文本，或空字符串（无定位数据时）
    """
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                f"SELECT latitude, longitude, accuracy, city, region, "
                "country, street, district, source, created_at "
                f"FROM {LOCATION_TABLE} "
                "WHERE status='active' AND identity_key=? "
                "ORDER BY id DESC LIMIT 1",
                (identity_key,),
            )
            row = cursor.fetchone()
            if not row:
                return ""

            db_ts = LocationManager._parse_db_time(row["created_at"])
            age_minutes = int((time.time() - db_ts) / 60)

            accuracy = float(row["accuracy"] or 5000)
            accuracy_text = _describe_accuracy(accuracy)
            freshness_text = _describe_freshness(age_minutes)
            source_text = _describe_source(row["source"])

            city = row["city"]
            region = row["region"]
            country = row["country"]
            street = row["street"] if "street" in row.keys() else None
            district = row["district"] if "district" in row.keys() else None
            lat = float(row["latitude"])
            lng = float(row["longitude"])

            # v1.4/v1.5: Qt 定位无城市名 → 逆地理编码补全（含街道级）
            if not city and row["source"].startswith("qt_"):
                reverse = _reverse_geocode(lat, lng)
                if reverse and (reverse[0] or reverse[1]):
                    city, region, country, street, district = reverse
                    # 写回数据库，避免重复请求
                    try:
                        with sqlite3.connect(db_path) as upd_conn:
                            upd_conn.execute(
                                f"UPDATE {LOCATION_TABLE} SET city=?, region=?, "
                                "country=?, street=COALESCE(street, ?), "
                                "district=COALESCE(district, ?) "
                                "WHERE status='active' AND identity_key=? "
                                "AND ABS(latitude - ?) < 0.001 "
                                "AND ABS(longitude - ?) < 0.001",
                                (city, region, country, street, district,
                                 identity_key, lat, lng),
                            )
                            upd_conn.commit()
                    except Exception:
                        pass

            city = city or "未知"
            region = region or ""
            country = country or ""

            # 城市信息可能为 None（Qt 定位不直接给城市名）
            # v1.5: 街道级信息（street/district）优先展示
            parts = []
            if street:
                parts.append(street)
            if district:
                parts.append(district)
            parts.append(city)
            if region:
                parts.append(region)
            if country:
                parts.append(country)
            location_line = ", ".join(parts)
            if city == "未知" and not (street or district):
                location_line = (f"坐标 {lng:.4f}°E, "
                                 f"{lat:.4f}°N (无城市名)")

            coord_line = ""
            if accuracy <= 1000:
                coord_line = (f"- 精确坐标: {lng:.4f}°E, "
                              f"{lat:.4f}°N\n")

            # v1.5: 有街道信息 → 提示 AI 可说到街道级
            street_hint = (
                "   - 街道级（≤100m 且已知街道）：可以说\"你在 {street}，{city}\"\n"
            ).format(street=street or "", city=city) if (street and accuracy <= 100) else ""

            return (
                "### 当前位置信息（系统提供）\n"
                f"- 位置: {location_line}\n"
                f"{coord_line}"
                f"- 精度: {accuracy_text}（{accuracy:.0f} 米）\n"
                f"- 时效: {freshness_text}\n"
                f"- 来源: {source_text}\n\n"
                "**位置信息使用规则**:\n"
                "1. 你可以基于此位置提供天气查询、本地推荐、交通信息等服务\n"
                "2. 如果用户询问\"我在哪里\"，根据精度等级回答：\n"
                "   - 精确位置（≤100m）：可以说\"你在 XX 市 XX 区附近\"\n"
                f"   - 街区级别（≤1000m）：可以说\"你在 XX 市 XX 区一带\"\n"
                "   - 城市级别（>1000m）：只说\"你在 XX 市\"\n"
                f"{street_hint}"
                "3. 永远不要在对用户的回答中提及经纬度数值\n"
                "4. 如果位置信息超过 30 分钟未更新，主动提示用户位置可能已过时\n"
            )
    except Exception as e:
        logger.error(f"[Prompt] 加载位置信息失败: {e}")
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
