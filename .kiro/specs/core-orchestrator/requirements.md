# Requirements Document: Core Orchestrator

Lead: Person A. Person B owns the UI protocol server (`ui_api/`, task 4), narration (task 9) and the TTS proxy (task 11). Reviewer: Person C (adapter usage).

## Introduction

Wysp Core turns a user's request into tutoring: it gathers context from the active adapter, reasons with an LLM that can only use safe tools, builds the board, streams narration, and runs actions through a permission gate followed by verification. It serves the Panel and holds the session. It is application-agnostic: everything it knows about an application comes from the adapter manifest, observations, the action catalog and the profile.

## Glossary

- **Session**: one tutoring session (conversation, board, learner state, active adapter).
- **Turn**: processing of one user message, from the request to the end of the narration.
- **Tool**: a function the LLM may call; tools are implemented by the Core.
- **Board state**: the Visual Model shown by the Panel (nodes, edges, groups, steps, annotations, focus, layout).
- **Projection**: deterministic conversion of observed entities into board nodes and edges.
- **Narration segment**: a short piece of speech or caption with cues that synchronise the board.
- **Proposal**: an action suggested by the LLM, waiting for the permission gate.
- **Grant**: a temporary permission given by the user for reversible actions within a lesson.
- **UI protocol**: the WebSocket protocol between the Core and the Panel (`/ws/ui`).

## Requirements

### Requirement 1: Service

**User Story:** As a user, I want to start Wysp with one command, so that both tutors and the Panel work locally.

#### Acceptance Criteria

1. WHEN the user runs `wysp serve`, THE Core SHALL listen on `127.0.0.1:8765` (configurable), serve the built Panel at `/`, the adapter endpoint at `/ws/adapter`, the UI endpoint at `/ws/ui`, `/api/health`, `/api/tts` and `/pair`.
2. THE Core SHALL never bind to a non-loopback interface unless the user passes `--unsafe-bind` explicitly.
3. WHEN the Core starts for the first time, THE Core SHALL create `~/.wysp/` with the pairing token, `config.toml`, and the `sessions/`, `learners/` and `audit/` folders.
4. WHERE `--llm scripted --mock` is passed, THE Core SHALL run with the ScriptedLLM provider and an in-process mock adapter, with no network access needed.

### Requirement 2: Adapter registry and active application

**User Story:** As a user with Blender and the browser open, I want to choose which application the tutor is looking at, so that answers refer to the right application.

#### Acceptance Criteria

1. THE Core SHALL keep a registry of connected adapters with manifest, status and last heartbeat, and SHALL publish it to the Panel on every change.
2. WHEN the user selects an adapter in the Panel, THE Core SHALL make it the active adapter of the session and load its profile.
3. WHEN only one adapter is connected, THE Core SHALL activate it automatically.
4. IF the active adapter disconnects, THEN THE Core SHALL tell the user, keep the board with a "stale" flag and resume when the adapter reconnects.

### Requirement 3: Turn processing

**User Story:** As a learner, I want to ask a question in my own words and get an answer grounded in my real application state.

#### Acceptance Criteria

1. WHEN the Core receives `user.message {text}`, THE Core SHALL start a turn that builds the LLM context from the active adapter's context, focus observation, profile, learner state, current lesson and recent conversation.
2. WHILE a turn is running, THE Core SHALL publish status updates (`thinking`, `acting`, `speaking`, `idle`) to the Panel.
3. THE orchestrator SHALL let the LLM respond only through Core tools and narration, with at most 8 tool rounds per turn.
4. IF the request is ambiguous, THEN THE orchestrator SHALL allow the LLM to ask a clarification question with up to four suggested answers, shown as buttons in the Panel.
5. IF the LLM provider fails or times out (20 s), THEN THE Core SHALL tell the user in plain language and keep the session usable.
6. WHEN a new `user.message` arrives during a turn, THE Core SHALL interrupt the current turn before starting the new one.

### Requirement 4: Tools offered to the LLM

**User Story:** As the Core, I want the LLM to act only through a small set of typed tools, so that its behaviour is controllable and testable.

#### Acceptance Criteria

1. THE orchestrator SHALL offer the tools `observe`, `show_entities`, `add_concept`, `annotate`, `narrate`, `highlight`, `propose_action`, `start_exercise`, `lookup_concept` and `ask_clarification`, each with a JSON Schema.
2. THE orchestrator SHALL only offer tools whose required adapter capability is declared in the manifest.
3. IF the LLM calls a tool with invalid arguments, THEN THE orchestrator SHALL return a structured error to the LLM and SHALL NOT perform any side effect.
4. THE LLM SHALL NOT have any tool that executes an adapter action directly.

### Requirement 5: Board and provenance

**User Story:** As a learner, I want to see the structure of what I am working on, and to know what is real, what is deduced and what is only an example.

#### Acceptance Criteria

1. WHEN the LLM calls `show_entities {refs, layout, focus}`, THE Core SHALL project the referenced entities from the latest observation into board nodes and edges with provenance `observed`.
2. WHEN the LLM calls `add_concept` or `annotate`, THE Core SHALL add nodes or annotations with provenance `inferred` or `illustrative`, never `observed`.
3. THE provenance validator SHALL downgrade to `inferred` any node marked `observed` whose ref is not present in an observation of the current session, and SHALL log the downgrade.
4. THE Core SHALL publish board changes as versioned patches (`board.patch {base_version, version, ops}`) and a full `board.snapshot` on Panel connection or on request.
5. WHEN an adapter reports changed refs that appear on the board, THE Core SHALL refresh the projected nodes and publish a patch.
6. THE board SHALL hold at most 60 visible nodes; above that, THE Core SHALL group the remaining nodes of the same parent into a collapsed group node.

### Requirement 6: Narration and interruption

**User Story:** As a learner, I want to interrupt the explanation at any moment, and ask "why?", so that the tutor follows my pace.

#### Acceptance Criteria

1. THE Core SHALL stream narration as segments of at most 300 characters, each with an id, text, language, provenance marker and cues that reference board nodes or refs.
2. WHEN the Core receives `user.interrupt`, THE Core SHALL publish `narration.cancel` within 100 ms, stop the running turn and record the last segment the Panel reported as played.
3. WHEN the user says or clicks "continue" after an interruption, THE Core SHALL resume from the first segment that was not played.
4. WHEN the user clicks "Why?" on a board node, THE Core SHALL start a turn whose request is an explanation of that node, with the node's ref and provenance in the context.

### Requirement 7: Permission gate and action pipeline

**User Story:** As a user, I want to approve every change the tutor makes, see whether it worked, and undo it.

#### Acceptance Criteria

1. WHEN the LLM calls `propose_action {action_id, params, rationale, mode}`, THE Core SHALL validate the parameters against the action's schema, then pass the proposal to the permission gate.
2. THE gate SHALL apply the policy: `read_only` and `ui_state` run without asking; `reversible` asks unless an active grant covers the action; `irreversible` always asks for a click with a preview and SHALL NOT accept voice approval.
3. WHEN approval is required, THE Core SHALL send `permission.request` with action title, target, risk, reversibility, rationale and preview, and SHALL wait at most 60 s before treating the request as denied.
4. WHEN a proposal is approved, THE Core SHALL execute it through the adapter, observe again and evaluate the action's postconditions.
5. IF a postcondition fails after execution, THEN THE Core SHALL undo the action when possible and report the failure with evidence to the user.
6. WHEN the user asks to undo the last change made by Wysp, THE Core SHALL call `adapter.undo` with the latest undo token and confirm the result.
7. WHERE the proposal mode is `guide`, THE Core SHALL show the action's `guide.ui_path` steps instead of executing, highlight each target, and verify the postconditions when the user's own changes are reported.
8. THE Core SHALL append every proposal, decision (approver and channel), execution, verification and undo to the audit log.

### Requirement 8: Events from the application

**User Story:** As a learner, I want the tutor to notice what I do in the application, so that it can follow me and confirm my progress.

#### Acceptance Criteria

1. WHEN the active adapter sends an event, THE Core SHALL publish it on the session event bus to the board, the pedagogy engine and the orchestrator.
2. WHEN a user-origin change happens while a guided step or an exercise is active, THE Core SHALL trigger verification of that step or exercise.
3. THE Core SHALL not start an unsolicited LLM turn more than once every 30 seconds, and only to acknowledge a verified step or offer help after two failed attempts.

### Requirement 9: LLM providers

**User Story:** As a team, we want to switch LLM providers and run deterministic tests, so that development and demos do not depend on one vendor or on network luck.

#### Acceptance Criteria

1. THE Core SHALL define an `LLMProvider` interface with streaming text and tool calls.
2. THE Core SHALL provide a `scripted` provider that replays scenario files deterministically, and at least one real provider selected by `WYSP_LLM_PROVIDER`.
3. THE Core SHALL never send pairing tokens, API keys or redacted fields to the LLM provider.

### Requirement 10: Text-to-speech proxy

**User Story:** As a learner, I want natural speech without exposing API keys to the browser.

#### Acceptance Criteria

1. WHEN the Panel requests `POST /api/tts {segment_id}`, THE Core SHALL return audio for the text of that segment from the configured provider, using the server-side key.
2. THE TTS proxy SHALL only synthesise text of narration segments produced by the Core in the current session.
3. IF no TTS provider is configured or the provider fails, THEN THE Core SHALL answer `503` so that the Panel falls back to browser speech synthesis.

### Requirement 11: Persistence and audit

**User Story:** As a learner, I want my progress kept between sessions, and as a user I want to know what the tutor did.

#### Acceptance Criteria

1. THE Core SHALL persist the learner model per profile, the session summaries and the audit log under `~/.wysp/` as JSON or JSONL files.
2. THE Core SHALL redact tokens, keys and sensitive field values in logs and in the audit log.
