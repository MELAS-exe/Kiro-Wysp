# Requirements Document: Tutor Panel

Lead: Person B. Reviewer: Person A (UI protocol).

## Introduction

The Panel is the single user interface shared by every Wysp tutor. It shows the board, the captions and the narration, handles voice input and output, and asks for permission before the tutor acts. It stays discreet next to the application (compact or side mode) and can become a full workspace. It contains no tutoring logic: it renders the state sent by the Core and sends user intents through the UI protocol.

## Glossary

- **Board renderer**: the React Flow view of the Visual Model.
- **Narration player**: the component that plays segments as captions and speech, and applies their cues.
- **Barge-in**: interrupting the narration by starting to speak.
- **Push-to-talk (PTT)**: holding a key or button to speak.
- **Layout mode**: `compact`, `side` or `full`.

## Requirements

### Requirement 1: Connection and shell

**User Story:** As a user, I want the Panel to connect to the local Core and show which application the tutor is looking at.

#### Acceptance Criteria

1. WHEN the Panel loads from the Core at `http://127.0.0.1:8765`, THE Panel SHALL connect to `/ws/ui` and render the session state, the adapter list and the board snapshot.
2. IF the connection drops, THEN THE Panel SHALL show a reconnecting state and reconnect with exponential backoff (maximum 5 s).
3. THE Panel SHALL show the connected adapters with their application name and integration level, and let the user choose the active one.
4. THE Panel SHALL offer the `compact`, `side` and `full` layout modes and remember the last mode.

### Requirement 2: Board rendering

**User Story:** As a learner, I want a clear diagram of what the tutor is explaining, with the difference between real and illustrative elements visible at a glance.

#### Acceptance Criteria

1. THE board renderer SHALL apply `board.patch` messages in version order and SHALL request a snapshot when a patch's `base_version` differs from its current version.
2. THE renderer SHALL support the `stack`, `tree`, `graph` and `sequence` layouts and produce the same positions for the same board state.
3. THE renderer SHALL style nodes by provenance as defined in `.kiro/steering/panel-ui.md` and SHALL show a legend in `side` and `full` modes.
4. WHEN a node has confidence below 1.0, THE renderer SHALL show a confidence badge.
5. WHEN the focus changes, THE renderer SHALL animate the focused nodes within 300 ms, or without animation when `prefers-reduced-motion` is set.
6. WHEN the user clicks a node, THE Panel SHALL send `board.select`, and the node SHALL offer "Why?" and, when it has hidden children, "Expand".

### Requirement 3: Captions and narration

**User Story:** As a learner, I want to read and hear the explanation, synchronised with the board.

#### Acceptance Criteria

1. WHEN a narration segment arrives, THE narration player SHALL queue it, show it as a caption when it starts and apply its cues when the corresponding word is reached.
2. THE player SHALL report `narration.progress` for each segment that finishes playing.
3. WHEN `narration.cancel` arrives, THE player SHALL stop audio and captions of that turn within 100 ms.
4. THE captions SHALL show the provenance markers ("likely", "for example") of the segment.
5. THE user SHALL be able to type a message instead of speaking at any time.

### Requirement 4: Voice

**User Story:** As a learner, I want to talk to the tutor and interrupt it naturally.

#### Acceptance Criteria

1. WHILE the user holds `Space` (Panel focused) or the mic button, THE Panel SHALL capture speech with the configured speech-to-text and show the interim transcript.
2. WHEN the user releases push-to-talk, THE Panel SHALL send the final transcript as `user.message {source: voice}`.
3. WHEN the user starts speaking or presses `Esc` while narration is playing, THE Panel SHALL stop playback and send `user.interrupt` within 150 ms.
4. THE Panel SHALL play narration audio from `/api/tts`, and fall back to the browser's speech synthesis when the endpoint answers 503 or fails.
5. WHERE the browser has no speech recognition, THE Panel SHALL hide the mic button and keep text input.

### Requirement 5: Permission, clarification and exercises

**User Story:** As a user, I want clear prompts when the tutor wants to act or needs an answer.

#### Acceptance Criteria

1. WHEN `permission.request` arrives, THE Panel SHALL show a dialog with action title, target, risk badge, reversibility, rationale and preview, with Approve, Deny and, for reversible actions only, "Allow for this lesson".
2. THE Panel SHALL accept a spoken "yes" or "no" as `via: voice` only for reversible actions; irreversible actions SHALL require a click.
3. WHEN `clarification` arrives, THE Panel SHALL show the options as buttons and send the chosen option as a user message.
4. WHEN an exercise is active, THE Panel SHALL show an exercise card with prompt, hint button, attempts and status, and SHALL label success as "verified in the application" or "declared".
5. THE Panel SHALL show lesson progress (steps with status) in `side` and `full` modes.

### Requirement 6: Accessibility and languages

**User Story:** As any user, I want a Panel I can use with the keyboard and in my language.

#### Acceptance Criteria

1. Every interactive control SHALL have an accessible name and be reachable with the keyboard.
2. Text contrast SHALL be at least 4.5:1.
3. THE Panel SHALL provide English and French strings and follow the session language.
