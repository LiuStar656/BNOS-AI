# 05 — Plugin System Design

> Date: 2026-07-25 | Files: 3 | Type: Documentation

---

## I. Summary

New design document for the BNOS AI plugin system, covering plugin lifecycle, communication protocol, security sandbox, and packaging.

Document-only change, no code modifications.

---

## II. Core Design

### 2.1 Plugin Lifecycle

```
Discover → Install → Register → Enable → Run → Disable → Uninstall
```

### 2.2 Communication

```
Plugin → BNOS: Emit events
BNOS → Plugin: Subscribe events (via hook registration)
Plugin ↔ Plugin: No direct communication, must go through core
```

### 2.3 Security

- Plugins run in isolated processes
- Filesystem access limited to `plugins/<name>/` directory
- Permission declaration in `plugin.json`

---

## III. Modified Files

| File | Changes |
|------|---------|
| `docs/design/BNOS AI plugin system design.md` | New: Complete design (326 lines) |
| `bnos_status.json` | Timestamp update |
| Component source path doc | Table restructured |

---

**Last updated**: 2026-07-25
