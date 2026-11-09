# Implementation Plan: Blender Tutor

Owners: A = Core & Contract, B = Experience, C = Adapters. Gates: J0 Wed 11 Nov, J1 Thu 19 Nov, J2 Fri 27 Nov, J3 Tue 1 Dec.
Depends on adapter-contract tasks 2, 7 and 9. Use the `blender-adapter` agent for these tasks.

- [ ] 1. Generate the demo scene
  - `demo/build_scene.py` building "Pumpkin Patch" and saving `demo/pumpkin.blend` (`blender -b --python build_scene.py -- --out ...`); the `.blend` is generated, not committed
  - _Owner: C_ · _Gate: J0_
  - _Requirements: 8.3_

- [ ] 2. Create the extension skeleton and the connection
  - `blender_manifest.toml` (5.2, permissions with reasons, wheels), preferences (Core URL, token path), sidebar panel, `runtime.py` with the SDK client, QueueDispatcher and timer pump, clean unregister
  - _Owner: C_ · _Gate: J0 + 1 day (Thu 12 Nov)_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2_

- [ ] 2.1 Write property test for main-thread confinement
  - **Property BLD-P1: Main-thread confinement**
  - **Validates: Requirement 2.1**

- [ ] 3. Implement observation and context
  - `observe.py` and `rna_props.py` following design.md, manifest entity kinds, context summary and facts
  - _Owner: C_ · _Gate: J1 (Mon 16 Nov)_
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 3.1 Write property test for modifier projection
  - **Property BLD-P3: Modifier projection is total**
  - **Validates: Requirement 3.2**

- [ ] 4. Implement the actions and the undo mechanism
  - One file per action in `actions/` (the `new-action-integration` hook wires each one), `undo.py` compensation records, `undo_push`, `apply_modifier` dry run with vertex preview, BUSY detection
  - _Owner: C_ · _Gate: J1 (add_modifier, set_modifier_property, select_object first)_
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 2.3_

- [ ] 4.1 Write property test for compensation undo
  - **Property BLD-P2: Compensation undo**
  - **Validates: Requirement 4.3**

- [ ] 5. Implement events and origin tagging
  - Depsgraph handler with 250 ms flush, digest diff, derived user actions, msgbus selection, `load_post` re-subscription, `tag_origin` window
  - _Owner: C_ · _Gate: J1_
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ] 5.1 Write property tests for events
  - **Property BLD-P4: Origin tagging**
  - **Property BLD-P5: Debounce**
  - **Validates: Requirements 5.1, 5.4**

- [ ] 6. End-to-end in text mode (gate J1)
  - With the Core and the Panel: explain the Pumpkin's modifiers, board in `stack` layout, propose `add_modifier` BEVEL on the Candle, approve, verify, undo
  - _Owner: C with A and B_ · _Gate: J1 (Thu 19 Nov)_
  - _Requirements: 3.1, 4.1, 4.3, 5.4_

- [ ] 7. Implement highlight
  - Viewport bounding-box outline with `gpu`, Properties tab switch, cleanup, `NOT_SUPPORTED` in background mode
  - _Owner: C_ · _Gate: J2_
  - _Requirements: 6.1, 6.2, 6.3, 7.2_

- [ ] 8. Headless runner and contract fixture
  - `demo/run_adapter.py` with manual pump loop, `contract.fixture.yaml` (safe calls, invalid calls, skip highlight), kit green
  - _Owner: C_ · _Gate: J1 (fixture), J2 (kit green with all actions)_
  - _Requirements: 7.1, 7.2, 7.3_

- [ ] 9. Write the Blender profile
  - `profile.yaml` (skills, board props), `concepts.yaml` (≥ 12 concepts with manual links), lessons L01, L02, L03 with the `bevel_segments` exercise, validated by `wysp validate-profile`
  - Content is written by B (learning experience); C reviews technical accuracy and the action ids used
  - _Owner: B (technical review: C)_ · _Gate: J2_
  - _Requirements: 8.1, 8.2_

- [ ] 10. Write the ScriptedLLM demo scenario
  - `demo/scenario.yaml` matching the video script, used as offline fallback
  - _Owner: C (review: B)_ · _Gate: J3_
  - _Requirements: 8.1_

- [ ] 11. Write the tutor README
  - Install, connect, run, action table (id, risk, reversible, description), what the tutor demonstrates
  - _Owner: C_ · _Gate: J3_
  - _Requirements: 1.1, 4.1_

- [ ] 12. Checkpoint: Blender tutor ready for recording
  - Manual GUI checklist of design.md done on the demo machine
  - Ask the user if questions arise
