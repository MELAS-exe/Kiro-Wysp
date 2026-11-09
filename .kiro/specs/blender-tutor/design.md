# Design Document: Blender Tutor

## Overview

```
apps/blender-tutor/
  adapter/                       Blender extension (GPL-3.0-or-later)
    blender_manifest.toml        id "wysp_tutor", blender_version_min "5.2.0", permissions network + files, wheels
    __init__.py                  register/unregister, preferences, sidebar panel
    runtime.py                   AdapterClient (SDK) + QueueDispatcher + timer pump
    observe.py                   entity projection (scene, collections, objects, modifiers, materials), context
    rna_props.py                 generic RNA property extraction for modifiers
    events.py                    depsgraph handler, msgbus, load_post, debounce, origin tagging, diff
    highlight.py                 gpu/blf draw handler, Properties editor tab switch
    undo.py                      compensation records, undo tokens, undo_push
    actions/                     one file per action (id = file name)
      select_object.py  show_properties_tab.py  add_modifier.py  remove_modifier.py
      set_modifier_property.py  move_modifier.py  toggle_modifier_visibility.py
      assign_material.py  apply_modifier.py
    wheels/                      websocket-client, jsonschema dependencies (pure Python)
  profile/                       profile.yaml, concepts.yaml, lessons/L01..L03
  demo/                          build_scene.py, run_adapter.py, scenario.yaml (ScriptedLLM fallback)
  contract.fixture.yaml
  tests/                         pytest with `bpy` from PyPI (headless) and a fake dispatcher
```

## Threading model

```
network thread (websocket-client)           main thread (Blender)
  recv request ─▶ queue.put(req) ─────────▶ timer pump every 50 ms (≤ 20 ms budget per tick)
                                              handler(req) uses bpy
  send(response) ◀── outbox.put(resp) ◀──────  result / error
  heartbeat every 15 s (no bpy)
```

- `QueueDispatcher` from the SDK; the pump is registered with `bpy.app.timers.register(pump, first_interval=0.05, persistent=True)`.
- Event handlers (`depsgraph_update_post`, msgbus callbacks) run on the main thread; they compute diffs and put notifications in the outbox.
- Headless mode (`run_adapter.py`): the same handlers, pumped by a `while` loop on the main thread with `time.sleep(0.01)`.

## Observation

- Entity order: scene, collections (depth first), objects sorted by name, modifiers in stack order, materials sorted by name.
- `rna_props.py`: for a modifier `mod`, iterate `mod.bl_rna.properties`, keep properties that are not read-only, whose type is `BOOLEAN`, `INT`, `FLOAT`, `ENUM` or `STRING`, which are not arrays longer than 4, skipping `name`, `rna_type` and UI-only properties (`show_expanded`, `show_in_editmode`, `show_on_cage`, `is_active`). Floats rounded to 4 decimals. Arrays become lists. The same function serves validation of `set_modifier_property` (only listed properties can be set).
- Object props: `type`, `location` (rounded to 3 decimals), `dimensions`, `modifiers_count`, `material_slots` (names), `hide_viewport`, `parent`.
- Volatile props declared in the manifest: none for modifiers; `location` is not volatile (users move objects on purpose).
- Size: demo scenes are small; truncation at 500 entities keeps the active object's subtree first.

## Actions (catalog)

| id | risk | params | postcondition (summary) | guide.ui_path (summary) |
|---|---|---|---|---|
| `select_object` | ui_state | `target` | target in focus | click the object in the Outliner |
| `show_properties_tab` | ui_state | `tab: MODIFIER\|MATERIAL\|OBJECT` | none (UI only) | click the tab icon in the Properties editor |
| `add_modifier` | reversible | `target`, `type` (enum from `bpy.types.Modifier.bl_rna.properties['type'].enum_items`), `name?` | a modifier of `type` exists on target | Properties › Modifiers (wrench) › Add Modifier › category › type |
| `remove_modifier` | reversible | `target` (modifier ref) | the modifier ref no longer exists | modifier header › dropdown › Delete |
| `set_modifier_property` | reversible | `target`, `property`, `value` | `props.<property> == value` | modifier panel › field |
| `move_modifier` | reversible | `target`, `index` | `props.index == index` | modifier header › dropdown › Move to First/Last, or drag handle |
| `toggle_modifier_visibility` | reversible | `target`, `viewport: bool` | `props.show_viewport == viewport` | monitor icon in the modifier header |
| `assign_material` | reversible | `target`, `material` | link `uses_material` exists | Properties › Material › slot › browse |
| `apply_modifier` | irreversible | `target` | modifier no longer exists | modifier header › dropdown › Apply (Ctrl+A) |

- `add_modifier` uses `obj.modifiers.new(name, type)`. `move_modifier` uses `obj.modifiers.move(from, to)`. `apply_modifier` uses `bpy.ops.object.modifier_apply` inside `bpy.context.temp_override(object=obj, active_object=obj)`, with a dry run that evaluates `obj.evaluated_get(depsgraph).to_mesh()` to count vertices before and after.
- Compensation records (`undo.py`): `add` → remove by name; `remove` → recreate with the saved type, name, index and RNA props; `set` → previous value; `move` → previous index; `visibility` → previous value; `assign_material` → previous slot material. After each Wysp action: `bpy.ops.ed.undo_push(message="Wysp: <title>")`.
- Undo tokens expire when a new file is loaded.

## Events and origin tagging

- `depsgraph_update_post` (registered with `@persistent`) marks a dirty flag; the pump flushes at most every 250 ms: it re-observes the objects and modifiers, computes the per-entity digest diff, and sends `event.state_changed {changed}` and the derived `event.user_action` (modifier added, removed or moved).
- Origin: `with tag_origin("wysp"):` around action execution and undo sets a window that lasts until the next flush; changes flushed in that window are tagged `wysp`, others `user`. If a user change and a Wysp change land in the same window (rare), the event is tagged `unknown`, which never counts as evidence.
- `bpy.msgbus.subscribe_rna(key=(bpy.types.LayerObjects, "active"), ...)` for active object changes; re-subscribed in a `@persistent` `load_post` handler.

## Highlight

- A `SpaceView3D.draw_handler_add(..., 'WINDOW', 'POST_VIEW')` callback draws the object's bounding box with the `gpu` module (`POLYLINE_UNIFORM_COLOR` shader, wisp colour `#2DD4BF`, pulsing alpha), and tags 3D areas for redraw from a short-lived timer until the duration ends.
- Modifier highlight: switch the first Properties editor to `context = 'MODIFIER'` (UI only) and outline the object.

## Profile and demo

- Concepts: object, mesh, vertex/edge/face, modifier, modifier stack, non-destructive editing, evaluation order, Subdivision Surface, Bevel, Solidify, apply, material, Outliner, Properties editor (with Blender manual links).
- L01 scene tour (show the scene tree, `tree` layout), L02 modifier stack (show the Pumpkin's stack, `stack` layout, explain order with an `illustrative` "what if Solidify came first" node, quiz), L03 bevel (guide `add_modifier` on the Candle, exercise `bevel_segments`).
- `demo/scenario.yaml`: the ScriptedLLM scenario of the video, so the demo can be recorded offline if the LLM provider is unreliable.

## Correctness Properties

**BLD-P1: Main-thread confinement.** *For any* sequence of requests, every access to `bpy` happens on the main thread (checked with a recording fake `bpy` and with thread assertions in debug builds). **Validates: Requirement 2.1**

**BLD-P2: Compensation undo.** *For any* random sequence of `add_modifier`, `set_modifier_property`, `move_modifier`, `toggle_modifier_visibility` and `remove_modifier` on a test mesh, undoing in reverse order restores the initial digest. **Validates: Requirement 4.3**

**BLD-P3: Modifier projection is total.** *For any* modifier type available in Blender 5.2, adding it to a mesh and observing yields schema-valid JSON entities whose props are JSON-serialisable. **Validates: Requirement 3.2**

**BLD-P4: Origin tagging.** *For any* interleaving of Wysp actions and direct `bpy` changes (simulated user changes), events from Wysp actions are tagged `wysp`, direct changes are tagged `user`, and no event mixes both without being `unknown`. **Validates: Requirement 5.4**

**BLD-P5: Debounce.** *For any* burst of depsgraph updates, at most one `event.state_changed` is sent per 250 ms and the last state is always reported. **Validates: Requirement 5.1**

## Error Handling

- Exceptions inside handlers are caught per request, partial changes are compensated, and `-32014 EXECUTION_FAILED` is returned with a short message.
- Name collisions on `add_modifier`: Blender renames (`Bevel.001`); the result reports the real ref.
- Objects renamed by the user: refs change; the Core sees the change through `state_changed` and re-projects.

## Testing Strategy

- `bpy` from PyPI (Python 3.13) in `apps/blender-tutor/tests/` for observation, RNA props, actions and undo (BLD-P2, BLD-P3), with Hypothesis.
- Fake dispatcher and recording fake for BLD-P1; simulated depsgraph bursts for BLD-P5; BLD-P4 with real `bpy` in headless mode.
- Contract kit in headless mode (`run_adapter.py`) in CI when a Blender binary is available (`@pytest.mark.live` otherwise).
- Manual checklist in the 5.2 GUI: sidebar, connect, highlight, Ctrl+Z after a Wysp action, file reload.
