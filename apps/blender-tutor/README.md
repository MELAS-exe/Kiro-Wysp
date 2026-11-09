# Blender tutor

The first application built on Wysp: a tutor that sees your Blender scene, explains objects and their modifier stack on an interactive board, guides you step by step, and verifies in Blender what you did. Integration level: **native** (Blender 5.2 LTS Python API).

> Status: prototype. Spec: `.kiro/specs/blender-tutor/`. Licence of the extension: GPL-3.0-or-later.

## Quick start (development)

1. Start the Core: `uv run wysp serve` (see the root README). Open http://127.0.0.1:8765.
2. Build the demo scene once: `blender -b --python apps/blender-tutor/demo/build_scene.py`.
3. Connect Blender:
   - headless (tests, contract kit): `scripts/run_blender_headless.ps1`, or the kit does it for you;
   - with the interface: build and install the extension (`uv run python scripts/build_blender_extension.py`), then open the **Wysp** tab in the 3D viewport sidebar and click **Connect**.

## Actions

Every action is declared in `adapter/actions/<id>.py`. The LLM can only *propose* them; the Core asks you before running anything that changes the scene, then verifies the result.

| id | risk | reversible | description |
|---|---|---|---|
| `select_object` | ui_state | no (UI only) | Select an object and make it active |
| `show_properties_tab` | ui_state | no (UI only) | Switch the Properties editor to MODIFIER, MATERIAL, OBJECT or DATA (needs a window) |
| `add_modifier` | reversible | yes | Add a modifier (any type of the running Blender) to an object |
| `set_modifier_property` | reversible | yes | Set one scalar property of a modifier (generic RNA, no per-type code) |
| `move_modifier` | reversible | yes | Reorder a modifier in the stack (evaluation order) |
| `remove_modifier` | reversible | yes | Delete a modifier; undo recreates it with its settings and position |
| `apply_modifier` | irreversible | no | Bake a modifier into the mesh; needs an explicit click and shows a preview |

## Entities

`scene`, `collection`, `object`, `modifier`, `material`, with refs such as `blender://object/Pumpkin` and `blender://object/Pumpkin/modifier/Subdivision` (names are percent-encoded).

## Safety

- Blender's API is only used on the main thread: the network thread only queues requests, a timer pump runs them.
- Every Wysp change pushes a native undo step, so Ctrl+Z also works.
- No action runs arbitrary Python: the catalog is closed and declarative.
