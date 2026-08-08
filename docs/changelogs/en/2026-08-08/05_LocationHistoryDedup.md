# Location History Dedup by Coordinates

## Problem

In the data-browser "location history" tab, the same place appeared as two entries:
one showing coordinates ("坐标 106.1866°E, 28.3304°N") and one showing the address
("赤水西路，杉王街道，习水县，贵州省"). The user asked why coordinates and the
resolved address are stored as two rows.

## Root Cause

- Coordinates and the city name are **already in the same row**
  (`location_history` stores latitude/longitude and city/street/district as different
  columns); there is no split storage. What looked like "two entries" was actually
  **multiple snapshots** of the same position.
- Qt positioning fires every 5 minutes; the GUI `_write_to_db` INSERTs a new row on
  every callback (marking the previous active row `superseded`). Standing still keeps
  the coordinates nearly identical → same-coordinate rows pile up.
- Reverse geocoding only fills in the city for the **latest active** row
  (`_read_latest_from_db`); older same-coordinate `superseded` rows have no city, so
  the UI shows both a "with address" and a "coordinates only" row for the same place.

## Solution

Added dedup at the GUI write side (`gui/core/location_provider.py` `_write_to_db`,
v1.5.3): **same coordinates (~330 m tolerance to cover cell-tower jitter) + an
active row within the last 30 minutes → only update that row's timestamp/accuracy/
source instead of inserting**; a row is inserted only after movement beyond the
tolerance, preserving the movement trail.

```python
# Before insert: same coordinates + active row within 30 min → dedup, refresh ts only
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
        "UPDATE location_history SET created_at=?, accuracy=?, source=? WHERE id=?",
        (now_str, float(location_data.get("accuracy", 5000)),
         location_data.get("source", "qt_cell"), row[0]),
    )
    conn.commit()
    return
# Otherwise: mark old active as superseded + insert new row (unchanged)
```

## Impact

| File | Change |
|------|--------|
| `gui/core/location_provider.py` | `_write_to_db` dedup: same coordinates + 30-minute window (v1.5.3) |

Existing data: `location_history` was cleared during testing (including historical
superseded rows); after GUI restart it accumulates under the new logic and keeps only
"places visited".

## Verification

Instantiated via `QtLocationProvider.__new__` (skipping the positioning source) and
called `_write_to_db` directly:

| Scenario | Rows in table |
|----------|---------------|
| Same coordinates written 3 times (simulating 5-min standing-still updates) | 1 (timestamp refreshed only) |
| Moved 0.005° (~500 m) then written again | 2 (old superseded + new active) |

Test rows were cleaned afterwards; restart the GUI to confirm no duplicate
same-coordinate rows appear.
