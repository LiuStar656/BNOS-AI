# Suppress IP Fallback While Qt Location Is Active

## Problem

While the top-level Qt positioning (cell/Wi-Fi/GPS) was working normally, the IP
fallback sources were still being queried, spamming logs with
`WARNING location: [Location] ipapi.co 获取失败: HTTP Error 403: Forbidden`.
User feedback: "顶层定位功能正常，兜底功能还在触发" (top-level positioning works, yet the fallback still fires).

## Root Cause

Old decision logic in `get_location()`:

```python
db_location = self._read_latest_from_db()
if db_location and not force_refresh:
    if (time.time() - db_location.timestamp) < self._update_interval:
        ...  # return directly
```

The GUI location page's "Refresh" button calls `get_location(force_refresh=True)`
(`gui/pages/location_page.py`). With `force_refresh=True`, `not force_refresh` is
always False → the fresh Qt record in the DB is **skipped** and execution falls
straight into the IP multi-source fallback. Even though Qt updates every 5 minutes,
every manual refresh still fired IP requests (hence the ipapi.co 403).

## Solution

`get_location()` (`location.py` v1.5.2) was reworked to "fresh Qt wins, fallback yields":

```python
db_location = self._read_latest_from_db()
if db_location:
    age = time.time() - db_location.timestamp
    # Fresh Qt record → top-level positioning is fine, return, do NOT hit IP fallback
    qt_fresh = db_location.source.startswith("qt_") and age < self._update_interval
    # Non-Qt record (e.g. IP cache) and not a forced refresh → reuse cache
    cache_fresh = (not force_refresh) and age < self._update_interval
    if qt_fresh or cache_fresh:
        self._current = db_location
        self._last_fetch_time = db_location.timestamp
        return LocationResult(success=True, location=db_location)
```

| Scenario | Behavior |
|----------|----------|
| Fresh Qt record (any call mode) | Returns Qt location directly, **0 IP requests** |
| No Qt record / Qt record stale (GUI positioning stopped) | IP fallback runs |
| Fresh non-Qt cache and not forced | Cache reused |

## Impact

| File | Change |
|------|--------|
| `nodes/node_python_aaa_cognition/location.py` | `get_location()` decision logic v1.5.2: fresh Qt wins; force_refresh no longer bypasses Qt records |

Manual refresh semantics are preserved: with a fresh Qt record the button still
returns the Qt high-precision result; IP is only queried when Qt positioning has
stopped (stale record) or never existed.

## Verification

Mocked `_fetch_from_source` and counted calls (no real network):

| Scenario | IP requests |
|----------|-------------|
| Fresh Qt, normal `get_location()` | 0 |
| Fresh Qt, `get_location(force_refresh=True)` (manual refresh) | 0 |
| Qt record 10 minutes old (stale) | Fires (3 sources when all fail) |

After GUI restart, as long as Qt keeps updating, `ipapi.co 获取失败`-style
WARNINGs no longer appear.
