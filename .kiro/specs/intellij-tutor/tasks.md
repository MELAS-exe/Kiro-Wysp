# Implementation Plan: IntelliJ Tutor

- [x] 1. Gradle project and plugin skeleton
  - Gradle 9.9.1 wrapper, Kotlin 2.4.0, IntelliJ Platform Gradle Plugin 2.20.1, local IntelliJ IDEA 2026.2, Java 25 (bundled JBR)
  - `plugin.xml` with the application service, settings, actions, tool window; `buildPlugin` produces a ZIP
  - _Owner: C_ · _Requirements: 1.1_

- [x] 2. JSON codec and JSON-RPC client
  - `Json.kt`, `RpcClient.kt` (hello, heartbeat, reconnect with backoff, request routing, notifications)
  - _Owner: C_ · _Requirements: 1.2, 1.3_

- [x] 2.1 Write property test for the codec
  - **Property IJ-P1: Codec round trip**
  - **Validates: Requirement 10.1**

- [x] 3. Refs, privacy rules and observation
  - `Refs.kt`, `Privacy.kt`, `Observe.kt` (entities, focus, context, size limits, dumb mode)
  - _Owner: C_ · _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.4_

- [x] 3.1 Write property tests for refs and privacy
  - **Property IJ-P2: Refs round trip**
  - **Property IJ-P3: Sensitive files never leak**
  - **Validates: Requirements 3.1, 4.4**

- [x] 4. Actions
  - `open_file`, `go_to_symbol`, `show_tool_window`, `rename_symbol` with undo; contract fixture
  - _Owner: C_ · _Requirements: 5.1, 5.2, 5.3, 5.4_

- [x] 4.1 Write platform test for rename and undo
  - **Property IJ-P4: Rename is undoable**
  - **Validates: Requirement 5.2**

- [x] 5. Highlight
  - Editor range markers; tool windows; Swing label search with balloons; not-found feedback
  - _Owner: C_ · _Requirements: 6.1, 6.2, 6.3_

- [x] 6. Events
  - Editor/caret/document listeners, debounce, origin tagging
  - _Owner: C_ · _Requirements: 7.1, 7.2_

- [x] 7. Wysp tool window and settings
  - JCEF Panel, fallback, settings page with the privacy note, connect/disconnect actions
  - _Owner: C (review: B)_ · _Requirements: 1.2, 4.3, 8.1, 8.2_

- [x] 8. Profile and sample project
  - `profile.yaml`, `concepts.yaml`, `demo/sample-project`
  - _Owner: B (review: C)_ · _Requirements: 9.1, 9.2, 10.3_

- [x] 9. End-to-end check
  - Sandbox IDE + test Core: observe, context, highlight (screenshots), rename + undo, tool window
  - _Owner: C_ · _Requirements: 10.2, 10.3_

- [x] 10. Checkpoint: IntelliJ tutor ready for the demo
  - README (install, actions table, privacy), journal entry
  - Ask the user if questions arise
