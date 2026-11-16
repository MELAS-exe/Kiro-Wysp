# Implementation Plan: Tutor Panel

Owners: A = Core & Contract, B = Experience, C = Adapters. Gates: J0 Wed 11 Nov, J1 Thu 19 Nov, J2 Fri 27 Nov, J3 Tue 1 Dec.
Depends on core-orchestrator task 4 (UI protocol) and task 6 (board golden fixtures).

- [x] 1. Scaffold the Panel and the protocol client
  - Vite + React 19 + TypeScript strict in `panel/`, Zustand store, typed WebSocket client with reconnection, connection banner, build to `panel/dist`
  - "Hello" screen showing session state and adapter list from the Core (works with `wysp serve --mock`)
  - _Owner: B_ · _Gate: J0_
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Implement the visual identity and the layout modes
  - Design tokens of `panel-ui.md`, `compact` / `side` / `full` modes with persistence, adapter switcher, status indicator, i18n setup (en, fr)
  - _Owner: B_ · _Gate: J1_
  - _Requirements: 1.3, 1.4, 6.1, 6.2, 6.3_

- [x] 3. Implement the board store and patch application
  - Pure `applyPatch`, version gap detection and snapshot requests, tests against `contract-tests/fixtures/board/`
  - _Owner: B_ · _Gate: J1_
  - _Requirements: 2.1_

- [ ] 3.1 Write property tests for patches
  - **Property PAN-P1: Patch parity with the Core**
  - **Property PAN-P2: Gap detection**
  - **Validates: Requirement 2.1**

- [x] 4. Implement the board renderer
  - React Flow view, node components by provenance, legend, confidence badge, group nodes, "Why?" and "Expand" actions, selection messages
  - Layouts `stack`, `tree`, `graph`, `sequence` with ELK (Web Worker above 30 nodes), focus animation with reduced-motion support
  - _Owner: B_ · _Gate: J1 (stack + tree), J2 (graph + sequence)_
  - _Requirements: 2.2, 2.3, 2.4, 2.5, 2.6_

- [ ] 4.1 Write property tests for layout and styles
  - **Property PAN-P3: Layout determinism**
  - **Property PAN-P6: Provenance style is total and distinct**
  - **Validates: Requirements 2.2, 2.3**

- [x] 5. Implement captions and the narration player
  - Segment queue, captions with provenance markers, cue application, progress reports, cancel within 100 ms, text input always available
  - Browser TTS first (J1), Core TTS through `/api/tts` with prefetch and fallback (J2)
  - _Owner: B_ · _Gate: J1 (captions + browser TTS), J2 (Core TTS)_
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 4.4_

- [ ] 5.1 Write property test for the narration state machine
  - **Property PAN-P4: Narration order and cancellation**
  - **Validates: Requirements 3.1, 3.3**

- [x] 6. Implement voice input and barge-in
  - `STTProvider` interface and `WebSpeechSTT`, push-to-talk (Space, mic button), interim transcript, VAD barge-in with calibration, `Esc` interrupt, microphone permission flow, graceful degradation without speech recognition
  - _Owner: B_ · _Gate: J2_
  - _Requirements: 4.1, 4.2, 4.3, 4.5_

- [x] 7. Implement the permission dialog and clarification chips
  - Dialog of design.md, focus on Deny for irreversible actions, lesson grant button for reversible actions, voice yes/no mapping
  - _Owner: B_ · _Gate: J1_
  - _Requirements: 5.1, 5.2, 5.3_

- [ ] 7.1 Write property test for voice approval
  - **Property PAN-P5: No voice approval for irreversible actions**
  - **Validates: Requirement 5.2**

- [ ] 8. Implement the exercise card, evidence badge and lesson progress
  - _Owner: B_ · _Gate: J2_
  - _Requirements: 5.4, 5.5_

- [ ] 9. Accessibility pass
  - Keyboard navigation, accessible names, contrast, axe checks in component tests, French strings complete
  - _Owner: B_ · _Gate: J3_
  - _Requirements: 6.1, 6.2, 6.3_

- [ ] 10. Prepare the window setup for the demo
  - Script `scripts/open_panel.py` opening a Chrome app window at a given size and position next to Blender or the browser
  - _Owner: B_ · _Gate: J3_
  - _Requirements: 1.4_

- [ ] 11. Checkpoint: Panel ready for recording
  - Ask the user if questions arise
