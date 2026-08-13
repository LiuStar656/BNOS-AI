# 2026-08-08 Changelog Overview

[Back to Index](../README.md)

---

## Updates

- [01 Message Pool Multi-User Interaction Infrastructure](#01-message-pool-multi-user-interaction-infrastructure)
- [02 Message Pool Data Collection & Multi-Agent Launch Script](#02-message-pool-data-collection--multi-agent-launch-script)
- [03 Reverse Geocode County-Level Accuracy Fix](#03-reverse-geocode-county-level-accuracy-fix)
- [04 Suppress IP Fallback While Qt Location Is Active](#04-suppress-ip-fallback-while-qt-location-is-active)
- [05 Location History Dedup by Coordinates](#05-location-history-dedup-by-coordinates)
- [06 Data Browser "Colon-Only" Placeholder Fix](#06-data-browser-colon-only-placeholder-fix)

---

## Summary

| # | Core change | Root cause | Impact |
|---|------------|------------|--------|
| 01 | Built the multi-user interaction experiment infrastructure (F1–F8, no experiments) per the `[PLAN] 消息池与弹幕式消息处理方案` design: AAA side adds `_on_pool_batch` batch entry, `batch_mode` explicit `{action: reply|silent}` decisions, v6.0 user_id migration and per-user cognition isolation; platform side adds the `tests/message_pool/` package (event bus / danmaku pool / @ mention routing / speech arbiter / collector / agent bridge / platform orchestration) | Multi-agent danmaku scenarios need batched consumption, speaker attribution, per-user cognition isolation, silent handling, a single speech floor, and structured data collection — the existing single-message `_on_text` path and user-less memory cannot support this | GUI direct path and existing tests are unaffected (new parameters have defaults); the pool experiment can reuse the platform package to orchestrate multiple agents and collect events/decisions/evolution data |
| 02 | Completed experiment data collection and launching: new `data_export.py` (per-agent raw DB exported by table + chat history md render), `collector.py`/`platform_runner.py` add `chat_history.jsonl` (user danmaku + agent broadcasts), new `run_pool_experiment.py` launch script (`--agents` default 5, count adjustable) | The experiment needs raw DB per-table dumps, message-pool chat history, and one-command multi-agent launching; the original platform only had events/decisions/evolution and the DB export logic was scattered in an old acceptance script | Each run gets an independent timestamped archive (runs/) with db/{agent}_final/ per-table JSON + sqlite, chat_history, events/decisions/evolution, _run_meta |
| 03 | Reverse geocoding switched from single-source (Photon) to dual-source merge: `city` takes BigDataCloud's county-level `locality` (习水县), `street`/`district` take Photon's street-level (赤水西路/杉王街道) | Photon's `city` is the prefecture-level city (遵义市); the county name (习水县) was only used as a fallback when Photon failed, so location showed prefecture instead of county | Location history and logs now show "习水县, 贵州省" (county) + street; qt_ rows in location_history had their admin info cleared and get re-filled on next read |
| 04 | `get_location()` decision logic reworked: a fresh Qt record returns directly regardless of `force_refresh`, never hitting the IP fallback | The GUI refresh button calls `get_location(force_refresh=True)`, and the old logic skipped the fresh Qt row and fell straight into IP multi-source fallback → ipapi.co was still queried (403) while Qt was healthy | As long as Qt keeps updating, `ipapi.co 获取失败` WARNINGs disappear; IP only runs when the Qt record is missing or stale |
| 05 | GUI `_write_to_db` coordinate dedup: same coordinates (~330 m tolerance) + an active row within 30 minutes → only refresh timestamp/accuracy, no insert | Qt fires every 5 minutes; standing still keeps coordinates nearly identical, yet every callback INSERTed → same-coordinate rows piled up (UI showed a "coordinates" row and an "address" row for the same place) | Location history keeps only "places visited"; standing still no longer piles up rows; movement beyond tolerance still inserts to preserve the trail |
| 06 | Data browser "colon-only" placeholder fix: `db.py` drops empty user messages (v5.5) + `knowledge_panel.py` unwraps JSON-wrapped messages and skips empty content (v1.6) | `_write` JSON-serialized the whole message dict when content was empty, producing `{"data_type":"text","content":"",...}` junk rows displayed as `"content": ""` | The 8 existing JSON junk rows are hidden; no new empty-message JSON rows will be created |

---

### 01 Message Pool Multi-User Interaction Infrastructure

See [01_MessagePoolMultiUserInfrastructure.md](./01_MessagePoolMultiUserInfrastructure.md).

### 02 Message Pool Data Collection & Multi-Agent Launch Script

See [02_MessagePoolDataCollectionAndLauncher.md](./02_MessagePoolDataCollectionAndLauncher.md).

### 03 Reverse Geocode County-Level Accuracy Fix

See [03_ReverseGeocodeCountyLevelFix.md](./03_ReverseGeocodeCountyLevelFix.md).

### 04 Suppress IP Fallback While Qt Location Is Active

See [04_SuppressIPFallback.md](./04_SuppressIPFallback.md).

### 05 Location History Dedup by Coordinates

See [05_LocationHistoryDedup.md](./05_LocationHistoryDedup.md).

### 06 Data Browser "Colon-Only" Placeholder Fix

See [06_DataBrowserColonPlaceholderFix.md](./06_DataBrowserColonPlaceholderFix.md).

---

## Modified Files

### New Files

| File | # |
|------|---|
| `tests/message_pool/__init__.py` | 01 |
| `tests/message_pool/event_bus.py` | 01 |
| `tests/message_pool/message_pool.py` | 01 |
| `tests/message_pool/router.py` | 01 |
| `tests/message_pool/arbiter.py` | 01 |
| `tests/message_pool/collector.py` | 01、02 |
| `tests/message_pool/agent_bridge.py` | 01 |
| `tests/message_pool/platform_runner.py` | 01、02 |
| `tests/message_pool/data_export.py` | 02 |
| `tests/message_pool/run_pool_experiment.py` | 02 |
| `tests/message_pool/infra_acceptance_test.py` | 01、02 |
| `tests/message_pool/README.md` | 01、02 |

### Major Changes

| File | Change | # |
|------|--------|---|
| `nodes/node_python_aaa_cognition/db.py` | v6.0 user_id column migration (user_messages / event_summary / other_cognition / user_facts); user_id dimension in `_dedup_and_merge` / `_write` / `_write_parsed`; new `g_where_identity_user` (user-specific first, global fallback) | 01 |
| `nodes/node_python_aaa_cognition/main.py` | new `_on_pool_batch` (batched write + F5 merged context + `_observe_counter`); `_on_parsed` batch_mode explicit decisions; `_gather_context` user_id / batch_items / pool_batch_section; fixed lost reflection-round pending context | 01 |
| `nodes/node_python_aaa_cognition/prompt.py` | cognition-label and user-text placeholders in `_CONTEXT_HEADER` (per-user rendering and batch section) | 01 |
| `tests/message_pool/collector.py` | New chat_history.jsonl output and `chat()` method | 02 |
| `tests/message_pool/platform_runner.py` | inject/step/drain_queue record chat history (role=user / agent) | 02 |
| `nodes/node_python_aaa_cognition/location.py` | `_reverse_geocode` dual-source merge: city from BigDataCloud county locality, street/district from Photon (v1.5.1); `get_location` fresh-Qt-first, force_refresh no longer bypasses Qt rows (v1.5.2) | 03、04 |
| `gui/core/location_provider.py` | `_write_to_db` same-coordinate + 30-min dedup: refresh timestamp/accuracy only, no insert (v1.5.3) | 05 |
| `nodes/node_python_aaa_cognition/db.py` | `_write` drops empty user messages (v5.5) | 06 |
| `gui/widgets/knowledge_panel.py` | `_read_db` unwraps JSON messages, skips empty content (v1.6) | 06 |

---

**Last updated**: 2026-08-08
