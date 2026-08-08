# Qt 定位正常时抑制 IP 兜底

## 问题描述

顶层定位（Qt 基站/GPS/Wi-Fi）正常工作时，IP 兜底定位源仍被请求，
日志持续出现 `WARNING location: [Location] ipapi.co 获取失败: HTTP Error 403: Forbidden`。
用户明确反馈"顶层定位功能正常，兜底功能还在触发"。

## 根因分析

`get_location()` 的旧决策逻辑：

```python
db_location = self._read_latest_from_db()
if db_location and not force_refresh:
    if (time.time() - db_location.timestamp) < self._update_interval:
        ...  # 直接返回
```

GUI 定位页"刷新位置"按钮调用 `get_location(force_refresh=True)`
（`gui/pages/location_page.py`），`force_refresh=True` 时 `not force_refresh`
恒为 False → **跳过数据库里新鲜的 Qt 定位记录**，直接进入第 2 步 IP 多源兜底。
于是 Qt 定位明明新鲜（每 5 分钟更新），每次手动刷新仍发起 IP 请求（ipapi.co 403）。

## 修改方案

`get_location()`（`location.py` v1.5.2）重构为"Qt 新鲜优先、兜底让位"：

```python
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
```

判定结果：

| 场景 | 行为 |
|------|------|
| Qt 记录新鲜（任意调用方式） | 直接返回 Qt 定位，**0 次 IP 请求** |
| 无 Qt 记录 / Qt 记录过期（GUI 定位已停止） | 走 IP 兜底 |
| 非 Qt 缓存新鲜且非强制刷新 | 复用缓存 |

## 影响范围

| 文件 | 改动 |
|------|------|
| `nodes/node_python_aaa_cognition/location.py` | `get_location()` 决策逻辑 v1.5.2：Qt 新鲜优先，force_refresh 不再绕过 Qt 记录 |

手动刷新语义不变：Qt 新鲜时用户点击刷新返回的仍是 Qt 高精度结果（这是想要的）；
仅当 GUI 定位停止（Qt 记录过期）或从未有 Qt 记录时才真正发起 IP。

## 验证方法

用 mock 替换 `_fetch_from_source` 计数验证（不触发真实网络请求）：

| 场景 | IP 请求次数 |
|------|-------------|
| Qt 新鲜，正常调用 `get_location()` | 0 |
| Qt 新鲜，`get_location(force_refresh=True)`（模拟手动刷新） | 0 |
| Qt 记录 10 分钟前（过期） | 触发（3 源全失败时遍历 3 次） |

验证后重启 GUI，运行期间只要 Qt 定位在更新，日志不再出现
`ipapi.co 获取失败` 类 WARNING。
