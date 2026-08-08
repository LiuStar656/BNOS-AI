# Knowledge Graph Physics Engine Fixes

## Problem

Five layout problems in the knowledge graph:

1. Nodes spawned at random coordinates; the desired behavior is all nodes spawning at the **same coordinate** (canvas center), immediately applying forces to show the physics effect.
2. **Force scale was ineffective**: layout size barely changed with L (only 1.37×), and gravity scaled down with L caused nodes to fly away at high L.
3. Two mutually attracting nodes sat too close together; the balance distance could not be tuned via the force scale.
4. Edges appeared only after all nodes finished loading; they should appear **streamingly** like the nodes.
5. **Infinite canvas but bounded node space**: at maximum force scale, nodes spread into a square outline and never escaped it.

## Root Cause

- The original `setup()` used random coordinates, so the physics animation started from an already-scattered initial state.
- Force scale L only changed repulsion strength, not the repulsion radius or the attraction balance distance; gravity first shrank with L (causing fly-off) and was then fixed but still constrained by a rectangular boundary.
- `step()` had a **rectangular hard-boundary bounce** with margin=30: at high L, nodes were pushed to the four walls of the 1500×1200 rectangle and lined up into a square — the direct cause of the "square outline".
- Edges were created once after `_load_next_node` finished; there was no streaming mechanism.

## Solution

All changes in `gui/widgets/knowledge_graph.py`:

1. **Same-coordinate spawning**: `setup()` spawns all nodes at the canvas center plus a random initial velocity impulse (1.0–2.0) to break symmetry; repulsion/attraction then take over and nodes bounce outward naturally.
2. **Force-scale L scaling system**:
   - Repulsion radius `REPEL_RADIUS * L` (capped at half canvas width) — larger L → wider repulsion → looser layout;
   - Attraction balance distance `ATTRACT_TARGET_DIST * L` (clamped 25–120) — fixes attracting nodes sitting too close and makes it tunable with L;
   - Center gravity **fixed** at `GRAVITY_STRENGTH`, independent of L — prevents infinite fly-off at high L.
3. **Circular soft boundary replaces rectangular hard boundary**: the margin=30 four-wall bounce is removed; new `BOUNDARY_RADIUS = AREA_WIDTH * 0.5` (750px) with `BOUNDARY_PULL = 0.01` softly pulls nodes back only beyond the radius — inside the radius there is no boundary force, so nodes spread freely in every direction and no square outline forms.
4. **Dynamic canvas expansion**: new `_expand_scene_to_fit(states)` grows sceneRect (never shrinks, margin=80) to follow the node bounding box so all nodes remain scrollable.
5. **Streaming edges**: GraphEdge records `start_idx` / `end_idx`; an edge appears only when both endpoint nodes are visible.
6. **Node display reset**: `_load_next_node` resets engine state to center and applies a velocity impulse (2.0–4.0) so the "pop from center" animation is visible.

## Impact

| File | Change |
|------|--------|
| `gui/widgets/knowledge_graph.py` | Same-coordinate spawn in setup; force-scale L scaling (repulsion radius / attraction balance); fixed gravity; circular soft boundary replacing rectangular bounce; `_expand_scene_to_fit` dynamic canvas; streaming edges; node display reset with impulse |

## Verification

- Parameter experiments (real similarity distribution: 15% strongly related + 30% weakly related + 55% unrelated): L=5 converges at ~400px radius with no wall-hugging nodes; L=1 default layout stays compact ~124px, unaffected by the soft boundary.
- Temporary verification script `_verify_nobound.py` (deleted after passing), 11/11 checks: L=5 no wall-hugging nodes (no square outline), layout converges max_r<700, L=1 compact, extreme all-repel case does not fly off (max_r<2500), sceneRect initial/expansion/never-shrink, no rectangular bounce code, circular soft boundary present, compile OK.
