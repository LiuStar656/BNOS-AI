# Reverse Geocode County-Level Accuracy Fix

## Problem

Location history and runtime logs show "遵义市, 贵州省" (prefecture-level city)
instead of the more precise county-level "习水县". `_read_latest_from_db` triggers
reverse geocoding whenever a Qt location record has no city and persists the result,
so logs kept showing `[Location] Qt 定位逆地理编码: 遵义市, 贵州省`.

## Root Cause

`_reverse_geocode` relied on a single source, Photon (OSM), whose `city` field is the
**prefecture-level** city (e.g. "遵义市"); BigDataCloud's free API `locality` is
**county-level** (e.g. "习水县"). The old logic returned Photon's result on success
and only fell back to BigDataCloud on failure, so the more precise county name was
never used. Measured comparison:

- Photon: `street="赤水西路"`, `district="杉王街道"`, `city="遵义市"` (prefecture)
- BigDataCloud: `locality="习水县"` (county, more precise, no street info)

## Solution

**Merge both sources**: `city` prefers BigDataCloud's `locality` (county-level),
`street`/`district` come from Photon (street-level), region/country from either.
`location.py` `_reverse_geocode`:

```python
# Old v1.5: Photon first, return on success
result = _reverse_geocode_photon(lat, lng)
if result is None:
    result = _reverse_geocode_bigdata(lat, lng)

# New v1.5.1: merge both sources, take the best of each
photon = _reverse_geocode_photon(lat, lng)
bigdata = _reverse_geocode_bigdata(lat, lng)
if not (photon or bigdata):
    return None
p_city, p_region, p_country, p_street, p_district = photon or (None,) * 5
b_city, b_region, b_country, _, _ = bigdata or (None,) * 5
result = (
    b_city or p_city,          # county locality first (习水县), fallback prefecture (遵义市)
    b_region or p_region,      # 贵州省
    b_country or p_country,    # 中国
    p_street,                  # 赤水西路 (Photon only)
    p_district,                # 杉王街道 (Photon only)
)
```

## Impact

| File | Change |
|------|--------|
| `nodes/node_python_aaa_cognition/location.py` | `_reverse_geocode` switched from single-source to dual-source merge (v1.5.1) |

Existing data: qt_ records already persisted "遵义市"; they were cleaned with
`UPDATE ... SET city=NULL, region=NULL, country=NULL, street=NULL, district=NULL
WHERE source LIKE 'qt_%'` so the next GUI/AAA read re-fills them via the new logic
(`_read_latest_from_db` only reverse-geocodes qt_ records whose `city` is empty).

## Verification

- Measured: `(28.3304, 106.1866) → ('习水县', '贵州省', '中华人民共和国',
  '赤水西路', '杉王街道')`; `(28.3302, 106.1864)` yields the same.
- After GUI restart, the log should show `Qt 定位逆地理编码: 习水县, 贵州省` and
  the location-history tab shows "赤水西路，杉王街道，习水县，贵州省" (street level).
