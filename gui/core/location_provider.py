"""
GUI 层 Qt 定位提供者 (v1.3)

使用 Qt QGeoPositionInfoSource 获取系统级定位（GPS/Wi-Fi/基站融合），
将高精度位置写入共享数据库，供 AAA 节点消费。

特性：
- 跨平台（Windows/macOS/Linux）
- 自动适配系统定位能力
- 5 分钟定时刷新
- 写数据库供 AAA 节点读取
- Qt 定位不可用时自动降级（不写入，AAA 走 IP 路径）
"""
import time
import sqlite3
import logging
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtPositioning import QGeoPositionInfoSource, QGeoCoordinate

logger = logging.getLogger(__name__)

# 默认身份键（与 AAA 节点保持一致）
_IDENTITY_KEY_DEFAULT = "gui:default"


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
    location_error = Signal(str)      # 定位错误信号

    def __init__(self, db_path: str, identity_key: str = _IDENTITY_KEY_DEFAULT,
                 parent=None):
        super().__init__(parent)
        self._db_path = db_path
        self._identity_key = identity_key
        self._source: Optional[QGeoPositionInfoSource] = None
        self._last_location = None
        self._last_write_time: float = 0
        self._qt_available: bool = False

        # 30s 超时检测定时器（Qt startUpdates 后无信号 → 降级）
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_qt_timeout)

        self._init_source()

    def _init_source(self):
        """初始化 Qt 定位源"""
        try:
            self._source = QGeoPositionInfoSource.createDefaultSource(self)

            if self._source:
                self._source.positionUpdated.connect(self._on_position_updated)
                # 错误信号在不同 PySide6 版本中签名不同，用 try 兼容
                try:
                    self._source.errorOccurred.connect(self._on_position_error)
                except AttributeError:
                    try:
                        self._source.positionError.connect(self._on_position_error)
                    except AttributeError:
                        pass

                # 设置更新间隔（5 分钟）
                self._source.setUpdateInterval(300000)  # ms

                # 检查支持的定位方法
                methods = self._source.supportedPositioningMethods()
                if methods == QGeoPositionInfoSource.NoPositioningMethods:
                    logger.warning("[QtLocation] 系统无可用定位方法，将降级 IP 定位")
                    self._qt_available = False
                else:
                    self._qt_available = True
                    logger.info("[QtLocation] 定位源初始化成功，支持: %s", methods)
            else:
                logger.warning("[QtLocation] 无法创建默认定位源，将降级 IP 定位")
                self._qt_available = False
        except Exception as e:
            logger.error(f"[QtLocation] 初始化失败: {e}")
            self._source = None
            self._qt_available = False

    def start(self):
        """启动持续定位"""
        if self._source and self._qt_available:
            self._source.startUpdates()
            self._request_once()
            # 30s 超时检测
            self._timeout_timer.start(30000)
            logger.info("[QtLocation] 定位持续更新已启动")
        else:
            logger.info("[QtLocation] Qt 定位不可用，AAA 节点将走 IP 降级路径")

    def stop(self):
        """停止定位"""
        if self._source:
            self._source.stopUpdates()
            logger.info("[QtLocation] 定位已停止")
        self._timeout_timer.stop()

    def _request_once(self):
        """请求一次当前位置"""
        if self._source:
            self._source.requestUpdate(5000)

    def is_qt_available(self) -> bool:
        """Qt 定位是否可用"""
        return self._qt_available

    def get_last_location(self) -> Optional[dict]:
        return self._last_location

    # ── 内部回调 ──────────────────────────────────────────────

    def _on_position_updated(self, info):
        """接收 Qt 位置更新"""
        if not info.isValid():
            return

        self._timeout_timer.stop()  # 收到信号，取消超时降级

        coord = info.coordinate()

        # 获取水平精度（兼容不同 PySide6 版本）
        # 注意：HorizontalAccuracy 属于 QGeoPositionInfo.Attribute，
        # 早期 PySide6 版本也可能挂在 QGeoCoordinate.Attribute 上，因此用兼容写法
        accuracy_val = 5000.0  # 默认兜底 5000m
        try:
            # v6.11+: 正确归属 QGeoPositionInfo.Attribute
            from PySide6.QtPositioning import QGeoPositionInfo as _QPI
            _HA = _QPI.Attribute.HorizontalAccuracy
        except Exception:
            try:
                # 老版本 fallback: QGeoCoordinate.Attribute
                from PySide6.QtPositioning import QGeoCoordinate as _QGC
                _HA = _QGC.Attribute.HorizontalAccuracy
            except Exception:
                _HA = None
        if _HA is not None and info.hasAttribute(_HA):
            accuracy_val = float(info.attribute(_HA))

        # 根据精度判断来源类型
        if accuracy_val <= 50:
            source_type = "qt_gps"
        elif accuracy_val <= 200:
            source_type = "qt_wifi"
        else:
            source_type = "qt_cell"

        location_data = {
            "latitude": coord.latitude(),
            "longitude": coord.longitude(),
            "accuracy": float(accuracy_val),
            "source": source_type,
            "timestamp": time.time(),
            # Qt 定位不直接给城市名，城市信息从 IP 降级时补充
            "city": None,
            "region": None,
            "country": None,
        }

        self._write_to_db(location_data)
        self._last_location = location_data
        self._last_write_time = time.time()

        self.location_updated.emit(location_data)
        logger.info(f"[QtLocation] 位置更新: {accuracy_val:.0f}m ({source_type})")

    def _on_position_error(self, *args):
        """定位错误回调（兼容不同 PySide6 版本的信号签名）"""
        # error 信号可能传 (error_enum) 或 (error_enum, message)
        error_msg = str(args[0]) if args else "未知错误"
        logger.warning(f"[QtLocation] 定位错误: {error_msg}")
        self.location_error.emit(error_msg)

    def _on_qt_timeout(self):
        """Qt 定位 30s 超时无信号 → 标记不可用"""
        logger.warning("[QtLocation] 30s 内未收到位置更新，标记 Qt 定位为不稳定")
        self._qt_available = False
        if self._source:
            self._source.stopUpdates()

    # ── 内部：数据库写入 ────────────────────────────────────

    def _write_to_db(self, location_data: dict):
        """将高精度位置写入 location_history 表（v5.0 独立表）

        v1.5.3: 同坐标去重。Qt 定位每 5 分钟回调一次，人在原地时坐标基本
        不变，若每次都 INSERT 会积累大量同坐标重复记录（界面出现"一条坐标、
        一条城市名"）。现在：同坐标（≈330m 容差）且近 30 分钟内已有 active
        记录 → 只更新时间戳/精度，不插入新记录。
        """
        try:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            lat = float(location_data["latitude"])
            lng = float(location_data["longitude"])

            with sqlite3.connect(self._db_path) as conn:
                # 确保 location_history 表存在（GUI 独立于 AAA 节点启动）
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS location_history("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    "identity_key TEXT NOT NULL DEFAULT 'gui:default',"
                    "latitude REAL NOT NULL,"
                    "longitude REAL NOT NULL,"
                    "accuracy REAL DEFAULT 5000,"
                    "city TEXT DEFAULT NULL,"
                    "region TEXT DEFAULT NULL,"
                    "country TEXT DEFAULT NULL,"
                    "street TEXT DEFAULT NULL,"
                    "district TEXT DEFAULT NULL,"
                    "source TEXT NOT NULL DEFAULT 'ip',"
                    "status TEXT DEFAULT 'active',"
                    "created_at TEXT NOT NULL DEFAULT(datetime('now','localtime')))"
                )
                # v1.5.3: 同坐标 + 近30分钟已有 active 记录 → 只更新时间戳/精度
                row = conn.execute(
                    "SELECT id FROM location_history "
                    "WHERE status='active' AND identity_key=? "
                    "AND ABS(latitude - ?) < 0.003 AND ABS(longitude - ?) < 0.003 "
                    "AND created_at >= datetime('now','localtime','-30 minutes') "
                    "ORDER BY id DESC LIMIT 1",
                    (self._identity_key, lat, lng),
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE location_history SET created_at=?, accuracy=?, "
                        "source=? WHERE id=?",
                        (now_str, float(location_data.get("accuracy", 5000)),
                         location_data.get("source", "qt_cell"), row[0]),
                    )
                    conn.commit()
                    return
                # 标记旧记录为 superseded
                conn.execute(
                    "UPDATE location_history SET status='superseded' "
                    "WHERE status='active' AND identity_key=?",
                    (self._identity_key,),
                )
                # 写入新记录
                conn.execute(
                    "INSERT INTO location_history("
                    "identity_key, latitude, longitude, accuracy, city, region, "
                    "country, source, status, created_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        self._identity_key,
                        lat,
                        lng,
                        float(location_data.get("accuracy", 5000)),
                        location_data.get("city"),
                        location_data.get("region"),
                        location_data.get("country"),
                        location_data.get("source", "qt_cell"),
                        "active",
                        now_str,
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"[QtLocation] 写入数据库失败: {e}")
