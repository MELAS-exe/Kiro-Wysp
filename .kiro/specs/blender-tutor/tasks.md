# Implementation Plan: Blender Tutor

Owners: A = Core & Contract, B = Experience, C = Adapters. Gates: J0 Wed 11 Nov, J1 Thu 19 Nov, J2 Fri 27 Nov, J3 Tue 1 Dec.
Depends on adapter-contract tasks 2, 7 and 9. Use the `blender-adapter` agent for these tasks.

- [x] 1. Generate the demo scene
  - `demo/build_scene.py` building "Pumpkin Patch" and saving `demo/pumpkin.blend` (`blender -b --python build_scene.py -- --out ...`); the `.blend` is generated, not committed
  - _Owner: C_ · _Gate: J0_
  - _Requirements: 8.3_

- [x] 2. Create the extension skeleton and the connection
  - `blender_manifest.toml` (5.2, permissions with reasons, wheels), preferences (Core URL, token path), sidebar panel, `runtime.py` with the SDK client, QueueDispatcher and timer pump, clean unregister
  - _Owner: C_ · _Gate: J0 + 1 day (Thu 12 Nov)_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.1, 2.2_

- [ ] 2.1 Write property test for main-thread confinement
  - **Property BLD-P1: Main-thread confinement**
  - **Validates: Requirement 2.1**

- [x] 3. Implement observation and context
  - `observe.py` and `rna_props.py` following design.md, manifest entity kinds, context summary and facts
  - _Owner: C_ · _Gate: J1 (Mon 16 Nov)_
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 3.1 Write property test for modifier projection
  - **Property BLD-P3: Modifier projection is total**
  - **Validates: Requirement 3.2**

- [x] 4. Implement the actions and the undo mechanism
  - One file per action in `actions/` (the `new-action-integration` hook wires each one), `undo.py` compensation records, `undo_push`, `apply_modifier` dry run with vertex preview, BUSY detection
  - _Owner: C_ · _Gate: J1 (add_modifier, set_modifier_property, select_object first)_
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 2.3_

- [ ] 4.1 Write property test for compensation undo
  - **Property BLD-P2: Compensation undo**
  - **Validates: Requirement 4.3**

- [x] 5. Implement events and origin tagging
  - Depsgraph handler with 250 ms flush, digest diff, derived user actions, msgbus selection, `load_post` re-subscription, `tag_origin` window
  - _Owner: C_ · _Gate: J1_
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ] 5.1 Write property tests for events
  - **Property BLD-P4: Origin tagging**
  - **Property BLD-P5: Debounce**
  - **Validates: Requirements 5.1, 5.4**

- [x] 6. End-to-end in text mode (gate J1)
  - With the Core and the Panel: explain the Pumpkin's modifiers, board in `stack` layout, propose `add_modifier` BEVEL on the Candle, approve, verify, undo
  - _Owner: C with A and B_ · _Gate: J1 (Thu 19 Nov)_
  - _Requirements: 3.1, 4.1, 4.3, 5.4_

- [x] 7. Implement highlight
  - Viewport bounding-box outline with `gpu`, Properties tab switch, cleanup, `NOT_SUPPORTED` in background mode
  - _Owner: C_ · _Gate: J2_
  - _Requirements: 6.1, 6.2, 6.3, 7.2_

- [x] 8. Headless runner and contract fixture
  - `demo/run_adapter.py` with manual pump loop, `contract.fixture.yaml` (safe calls, invalid calls, skip highlight), kit green
  - _Owner: C_ · _Gate: J1 (fixture), J2 (kit green with all actions)_
  - _Requirements: 7.1, 7.2, 7.3_

- [x] 9. Write the Blender profile
  - `profile.yaml` (skills, board props), `concepts.yaml` (≥ 12 concepts with manual links), lessons L01, L02, L03 with the `bevel_segments` exercise, validated by `wysp validate-profile`
  - Content is written by B (learning experience); C reviews technical accuracy and the action ids used
  - _Owner: B (technical review: C)_ · _Gate: J2_
  - _Requirements: 8.1, 8.2_

- [x] 10. Write the ScriptedLLM demo scenario
  - `demo/scenario.yaml` matching the video script, used as offline fallback
  - _Owner: C (review: B)_ · _Gate: J3_
  - _Requirements: 8.1_

- [x] 11. Write the tutor README
  - Install, connect, run, action table (id, risk, reversible, description), what the tutor demonstrates
  - _Owner: C_ · _Gate: J3_
  - _Requirements: 1.1, 4.1_

- [ ] 12. Checkpoint: Blender tutor ready for recording
  - Manual GUI checklist of design.md done on the demo machine
  - Ask the user if questions arise

- [x] 13. Interface highlighting
  - `adapter/ui_targets.py`, region frames, labels and Properties tab markers in `adapter/highlight.py`; guided steps carry UI refs; primer lists them
  - Checked with screenshots of a separate Blender instance (`tests/gui_shot.py`); unit tests in `tests/test_ui_targets.py`
  - _Owner: C_ · _Gate: J2_
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

- [x] 14. Chat and board inside Blender
  - `ui_client.py`, `ui_state.py`, `ui_panel.py`, `board_tree.py`, `board_layout.py`; board tree removed before save
  - _Owner: C (review: B)_ · _Gate: J2_
  - _Requirements: 10.1, 10.2, 10.3, 10.4_

- [x] 14.1 Write property test for the board mirror
  - **Property BLD-P6: Board mirror**
  - **Validates: Requirement 10.3**

- [x] 15. Blender-side telemetry
  - `adapter/telemetry.py`, SDK `AdapterClient(on_request_done=...)` with queue and run times
  - _Owner: C_ · _Gate: J2_
  - _Requirements: 10.5_

- [x] 16. Voice and approval-first chat in Blender
  - Core `POST /api/tts` (`wysp_core/tts.py`, local Windows voices); `adapter/ui_voice.py`; voiced timing in `ui_state.py`; chat order and approval banner in `ui_panel.py`
  - Tested with a fake voice (`tests/test_ui_state.py`) and in a GUI Blender against a test Core
  - _Owner: C (Core endpoint: A)_ · _Gate: J2_
  - _Requirements: 10.6, 10.7_

- [x] 17. `set_object_transform` action
  - `adapter/actions/set_object_transform.py`, observation props `rotation` and `scale`, fixture calls, README row; `tests/probe_transform.py` checks postconditions and undo digests in Blender
  - _Owner: C_ · _Gate: J2_
  - _Requirements: 11.1, 11.2_

- [x] 18. Hybrid pointing and spoken-order chat
  - Core `POST /api/ocr` (`wysp_core/ocr.py`, Windows OCR); `adapter/label_match.py`, `adapter/nav_detect.py`; label refs and tab detection in `highlight.py`; guided steps target labels; effective UI scale
  - Tests on OCR output recorded from real screenshots (`tests/fixtures/`), synthetic tab columns, GUI runs at Resolution Scale 0.85, 1.0 and 1.25
  - _Owner: C (Core endpoint: A)_ · _Gate: J2_
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5_

- [x] 19. Push-to-talk and message field
  - Core `POST /api/listen/{start,stop,cancel}` (`wysp_core/listen.py`: `sounddevice` recording, Whisper on Groq); `adapter/ui_listen.py`; `wysp.talk` operator with Alt+Space keymap and Talk button; voice approvals in `ui_state.route_transcript`; deferred clearing of the message field
  - Tests: endpoints with a fake recorder and transcriber, client against a stand-in Core, GUI runs with `tests/fake_voice_core.py` (button and simulated Alt+Space hold with auto-repeat); never the real microphone in tests
  - _Owner: C (Core endpoints: A)_ · _Gate: J2_
  - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

- [x] 20. Fixes from the session of 2026-11-10
  - OCR ignores the 3D Viewport sidebar (Wysp's own chat) and Wysp's banners: "Bisect." had been framed inside Wysp's own sentence (`label_match.without`)
  - Label OCR runs off the main thread: the SDK (0.3.0) lets a handler return a `Deferred` answered later; main-thread time per label highlight 125-600 ms -> 50-110 ms; numpy pre-loaded at connect (first tab highlight took up to 4.8 s)
  - A new message dismisses an old clarification (Blender and browser Panels)
  - Primer: items inside a closed menu are not visible; the sidebar is never a target
  - _Owner: C_ · _Gate: J2_

- [x] 21. Live check of the lessons and the exercise engine on real Blender 5.2
  - `tests/test_pedagogy_live.py` (Core in-process + headless adapter, agent over `/mcp`, scripted learner in `tests/live_driver.py`): `learner_status`, `start_exercise`, evidence from a user change, Wysp's own changes never count (PED-P4), the `move_solidify_first` and `bevel_segments` predicates on real observations
  - Fix: a selection change now bumps the adapter's state version and calls `on_focus_changed`; before, no "select X" exercise could pass (the Core saw no newer observation) and the persistent-highlight dismissal was never triggered
  - Open (core, owner A): `ExerciseEngine.evaluate` only checks `own_change_total` on a claim; a later user-origin event passes an exercise that Wysp satisfied (xfail test `test_prop_ped_p4_a_later_user_change_does_not_credit_wysps_selection`)
  - Done (task 22): the in-Blender panel shows the lesson and exercise card (`ui_state.py`, `ui_panel.py`), screenshots in `docs/img/blender-panel-exercise.png` and `-lesson.png`
  - _Owner: C_ · _Gate: J2_
