# Design Document: Tutor Panel

## Overview

A React 19 + Vite single-page app, built to `panel/dist` and served by the Core. It is opened in a Chrome app window (`chrome --app=http://127.0.0.1:8765`) placed next to Blender or the browser tab. State lives in a Zustand store fed by the UI protocol; components only render the store and send messages.

## Architecture

```
panel/src/
  protocol/   ws client (reconnect, typed messages from @wysp/adapter-sdk generated UI types)
  store/      session, adapters, board (patch apply), narration queue, permission, exercise, lesson
  board/      BoardView (React Flow), nodes/ (ObservedNode, InferredNode, IllustrativeNode, GroupNode),
              layout/ (elk layered, tree, stack, sequence), legend, focus animation
  narration/  NarrationPlayer (queue, captions, cues, progress), CaptionBar
  voice/      stt/ (WebSpeechSTT, provider interface), tts/ (CoreTTS via /api/tts, BrowserTTS fallback),
              vad.ts (barge-in detection), ptt.ts
  dialogs/    PermissionDialog, ClarificationChips
  learning/   ExerciseCard, LessonProgress, EvidenceBadge
  shell/      App, LayoutModes (compact | side | full), AdapterSwitcher, ConnectionBanner
  i18n/       en.json, fr.json
```

## Components and Interfaces

### Board

- `applyPatch(board, patch)` is a pure function with the same semantics as `wysp_core.board.ops`. It is tested against the golden fixtures in `contract-tests/fixtures/board/` produced by the Core.
- Layout: `elkjs` layered for `graph` and `tree` (direction DOWN for trees, RIGHT for graphs), a simple column layout for `stack` (ordered by the node order of the board, which is the modifier or layer order coming from the adapter), and a row layout for `sequence`. Inputs are sorted by node id before layout, and ELK runs with fixed options, so positions are deterministic. Layout runs in a Web Worker when the board has more than 30 nodes.
- Node components show label, kind icon, `props_view` (up to 6 rows), badges, provenance style, confidence badge, and the action buttons "Why?" and "Expand".
- Focus: glow and 1.03 scale; `fitView` on focus with 300 ms animation, disabled under reduced motion.

### Narration player

State machine per turn: `idle → playing(segment i) → (cue events) → finished(i) → playing(i+1) … → idle`, with `cancelled` reachable from any state. For each segment:
1. Request audio (`POST /api/tts {segment_id}`), or use the browser speech synthesis. Prefetch the next segment.
2. Word timing: `SpeechSynthesisUtterance` boundary events for browser TTS; for Core TTS, use provider word timestamps when available, otherwise estimate from the text length and the audio duration.
3. Apply cues (`focus` → store focus, `highlight` → send `board.select`-like highlight request through the Core, `step` → lesson step highlight) when their word index is reached.
4. Report `narration.progress {segment_id, played: true}` at the end.

### Voice

- `STTProvider` interface: `start(lang)`, `stop() → final transcript`, `onInterim`. Default `WebSpeechSTT` (Chrome Web Speech API, `interimResults: true`). Optional provider through the Core later.
- PTT: hold `Space` (only when focus is not in a text field) or the mic button.
- Barge-in: while narration plays, `vad.ts` monitors the microphone RMS energy (WebAudio `AnalyserNode`, threshold calibrated during the first second, 120 ms above threshold). On trigger: stop audio, send `user.interrupt`, start PTT capture automatically. Echo risk is reduced by `echoCancellation: true` constraints and by raising the threshold while audio plays. `Esc` always interrupts.
- Microphone permission is requested once on the first PTT, with an explanation in the Panel.

### Permission dialog

Props from `permission.request`. Voice: while the dialog is open, a short "yes" / "no" transcript maps to approve or deny only when `risk !== "irreversible"`. Keyboard: `Enter` does not approve by default (focus starts on Deny for irreversible actions).

## Data Models

The store holds `session`, `adapters[]`, `board` (with `version`), `narration {queue, current, cursor}`, `permission | null`, `clarification | null`, `exercise | null`, `lesson | null`, `status`, `settings {lang, layoutMode, voice}`. Message types come from the generated UI protocol types.

## Correctness Properties

**PAN-P1: Patch parity with the Core.** *For any* golden fixture produced by the Core, `applyPatch` applied to the initial board yields exactly the expected board. **Validates: Requirement 2.1**

**PAN-P2: Gap detection.** *For any* sequence of patches delivered with gaps or duplicates, the store either applies them in order or requests a snapshot; it never applies a patch whose `base_version` differs from its version. **Validates: Requirement 2.1**

**PAN-P3: Layout determinism.** *For any* board, running the layout twice, including with nodes given in a different order, yields the same positions. **Validates: Requirement 2.2**

**PAN-P4: Narration order and cancellation.** *For any* interleaving of segment arrivals, playback ends and cancel messages, segments start in index order, never overlap, and nothing of a cancelled turn plays after the cancel. **Validates: Requirements 3.1, 3.3**

**PAN-P5: No voice approval for irreversible actions.** *For any* permission request and transcript, a voice approval is sent only if the risk is not `irreversible`. **Validates: Requirement 5.2**

**PAN-P6: Provenance style is total and distinct.** *For any* node, exactly one provenance style applies, and the three styles differ in border and label. **Validates: Requirement 2.3**

## Error Handling

- WebSocket loss: banner, input disabled except typing a draft, automatic reconnection and snapshot request.
- TTS failure: switch to browser TTS for the rest of the session and show a small notice.
- STT error or no permission: show the reason and keep text input.

## Testing Strategy

- Vitest + fast-check for `applyPatch` (PAN-P1, P2), layout (PAN-P3), the narration state machine with a fake clock and fake audio (PAN-P4), the permission voice mapping (PAN-P5) and styles (PAN-P6).
- Testing Library for components; axe checks for accessibility in component tests.
- Manual checklist for voice and barge-in on the demo machine (microphone and speakers).
