"""
AI 地理位置可视化组件 (v1.3)

显示内容：
1. 静态地图图片（带红色位置标记）
2. 当前位置文字描述
3. 无网络时显示降级文字

地图源：高德静态地图（有 Key 时优先） → OpenStreetMap 兜底
"""
import urllib.request
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel

from gui.core.config import AppConfig


class _MapFetchWorker(QThread):
    """后台线程：获取静态地图图片，避免阻塞 UI"""
    fetched = Signal(QPixmap)
    failed = Signal()

    def __init__(self, lat: float, lng: float, amap_key: str = ""):
        super().__init__()
        self._lat = lat
        self._lng = lng
        self._amap_key = amap_key

    def run(self):
        pixmap = self._fetch_map_image()
        if pixmap and not pixmap.isNull():
            self.fetched.emit(pixmap)
        else:
            self.failed.emit()

    def _fetch_map_image(self) -> QPixmap:
        """获取静态地图图片（高德 → OSM 兜底）"""
        if self._amap_key:
            pixmap = self._fetch_amap()
            if pixmap and not pixmap.isNull():
                return pixmap
        return self._fetch_osm()

    def _fetch_amap(self) -> QPixmap:
        """高德静态地图 API"""
        try:
            url = (
                "https://restapi.amap.com/v3/staticmap"
                f"?location={self._lng},{self._lat}"
                "&zoom=14&size=480*360"
                f"&markers=mid,0xFF6B35,A:{self._lng},{self._lat}"
                f"&key={self._amap_key}"
            )
            response = urllib.request.urlopen(url, timeout=10)
            pixmap = QPixmap()
            pixmap.loadFromData(response.read())
            return pixmap
        except Exception:
            return QPixmap()

    def _fetch_osm(self) -> QPixmap:
        """OpenStreetMap 静态地图（免费兜底）"""
        try:
            url = (
                "https://staticmap.openstreetmap.de/staticmap.php"
                f"?center={self._lat},{self._lng}&zoom=14&size=480x360"
                f"&markers={self._lat},{self._lng},red-pushpin"
            )
            response = urllib.request.urlopen(url, timeout=15)
            pixmap = QPixmap()
            pixmap.loadFromData(response.read())
            return pixmap
        except Exception:
            return QPixmap()


class LocationMapWidget(QLabel):
    """AI 地理位置可视化组件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # 读取高德 Key 配置
        loc_cfg = AppConfig().get("location", {})
        self._amap_key = loc_cfg.get("amap_key", "") if isinstance(loc_cfg, dict) else ""
        self._last_location = None
        self._fetch_worker: Optional[_MapFetchWorker] = None
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
        self._show_placeholder("点击\"刷新位置\"获取当前位置")

    def update_location(self, location_dict: dict):
        """更新位置并刷新地图显示"""
        lat = location_dict.get("latitude")
        lng = location_dict.get("longitude")
        if lat is None or lng is None:
            self._show_location_fallback(location_dict)
            return

        self._last_location = location_dict
        self._show_placeholder("地图加载中...")

        # 后台获取地图图片
        if self._fetch_worker and self._fetch_worker.isRunning():
            self._fetch_worker.quit()
            self._fetch_worker.wait(1000)

        self._fetch_worker = _MapFetchWorker(lat, lng, self._amap_key)
        self._fetch_worker.fetched.connect(self._on_map_fetched)
        self._fetch_worker.failed.connect(
            lambda: self._show_location_fallback(self._last_location or location_dict)
        )
        self._fetch_worker.start()

    def _on_map_fetched(self, pixmap: QPixmap):
        """地图图片获取完成回调"""
        scaled = pixmap.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        self.setPixmap(scaled)

    def _show_placeholder(self, text: str):
        self.setText(text)
        self.setPixmap(QPixmap())

    def _show_location_fallback(self, location_dict: dict):
        """地图加载失败时显示文字信息"""
        city = location_dict.get("city") or "未知城市"
        accuracy = location_dict.get("accuracy", "?")
        self.setText(f"{city}\n精度: {accuracy}米\n(地图加载失败)")
        self.setStyleSheet("""
            QLabel {
                background: #f5f6fa;
                border: 1px solid #e0e0e0;
                border-radius: 8px;
                color: #666;
                font-size: 14px;
            }
        """)
