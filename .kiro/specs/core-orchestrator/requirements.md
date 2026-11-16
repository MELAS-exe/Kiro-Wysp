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

### Requirement 12: Survey of the application on activation

**User Story:** As a user opening a tutor on my scene, my project or my page, I want Wysp to look at everything it can see before it answers, so that its first answer already starts from my real situation.

#### Acceptance Criteria

1. WHEN an adapter becomes the active adapter (first connection, selection in the Panel, or reconnection), THE Core SHALL start a survey in the background: it reads the action catalog, the context and a full observation, using only the existing adapter contract (no new method, `contract_version` unchanged).
2. THE survey SHALL NOT delay the adapter handshake. WHEN a turn starts while the survey runs, THE Core SHALL wait for it at most 3 s and then continue with what it has.
3. THE survey SHALL go through `Session.observe`, so that every surveyed ref is a ref of a recorded observation and an `observed` board node may point at it (Requirement 5).
4. THE Core SHALL give the tutor a bounded summary of the survey (at most 4,000 characters inside `<app_data>`: counts per kind, the structure under the roots, a few examples per kind, the survey's age). The summary SHALL say when the observation was truncated or the survey is partial, and the tutor SHALL NOT present a truncated list as complete.
5. IF the survey fails or times out, THEN THE Core SHALL continue exactly as before (observation on demand) and SHALL retry at most 3 times, after 5, 10 and 20 s.
6. WHEN the adapter reports `state_changed`, THE Core SHALL mark the survey stale and refresh it after a debounce of 2 s.
7. THE survey SHALL show its progress to the Panel as `activity` messages and SHALL log its counts and duration, never the entities' properties.
8. THE user SHALL be able to turn the survey off (`wysp serve --no-survey` or `WYSP_SURVEY=off`). It is on by default.
9. Entities flagged `sensitive: true` by an adapter SHALL appear in the summary by kind and count only, never by label or props.

### Requirement 13: Highlights that stay until they are done

**User Story:** As a user looking for something in the application, I want what Wysp points at to stay highlighted until I have found it or Wysp moves on, so that I do not lose it after a few seconds.

#### Acceptance Criteria

1. WHEN the tutor points at an element with the `highlight` tool (or a guided step ends on one), THE Core SHALL ask the adapter for a persistent highlight (`duration_ms: 0`) and SHALL remember it as the session's active highlight.
2. THE Core SHALL end the active highlight when: the tutor calls `clear_highlight`; another element is highlighted (it replaces it); the adapter reports `event.highlight_dismissed` (the user interacted with it); a guided step is verified; the adapter disconnects or another application is activated; or 10 minutes have passed.
3. THE tutor SHALL be told in its prompt which element is highlighted, and SHALL be instructed to clear it when the user is done or the conversation moves on.
4. Highlights from narration cues and step tours SHALL stay short (timed), so they never outlive the sentence or the tour.
5. WITH an adapter older than contract 1.1, THE Core SHALL use the longest timed highlight and SHALL NOT send `adapter.clear_highlight` (adapter-contract Requirement 8.6).
6. WHEN an adapter reports `event.highlight_dismissed` with reason `user`, THE Core SHALL log it (`highlight.dismissed`) and SHALL NOT count it as evidence of mastery.

### Requirement 14: One Panel speaks

**User Story:** As a user with two Panels open (the IDE's tool window and a browser tab), I want each sentence read once.

#### Acceptance Criteria

1. THE Core SHALL tell each Panel, in every `narration.segment`, whether it is the speaking Panel (`speaker`). Exactly one connected Panel is the speaker: the one the user acted in last, else the first connected; when it disconnects another takes over.
2. A Panel that is not the speaker SHALL show captions only. `narration.progress` and `narration.cue` from a Panel that is not the speaker SHALL be ignored.

### Requirement 15: Project exploration: a code map and a study phase

**User Story:** As a student opening an unfamiliar project, I want the tutor to study it properly before it teaches me, so that what it says about the code is something it has read, not a guess.

#### Acceptance Criteria

1. WHERE the active application's profile has an `explore` section, WHEN the application becomes active, THE Core SHALL offer the user to explore the project and SHALL NOT read or crawl anything until the user accepts (`explore.start`). The user can decline or stop at any time.
2. WHEN the user accepts, THE Core SHALL build a **code map** without any language model: it walks the adapter's containers breadth first with `observe {level: full, root: <container or file>}` and keeps the files, their symbols and their dependencies. The walk SHALL stop at a budget (calls, time, entries) and SHALL report when it stopped early.
3. THE map SHALL contain only what the adapter reported. Entities flagged `sensitive` SHALL NOT enter it. The tutor SHALL receive a bounded overview (at most 3,000 characters) and SHALL be able to read any part of the map with the `code_map` tool (at most 6,000 characters per call).
4. WHEN the map is ready and an external agent drives the tutor, THE Core SHALL hand it a **study** task (a `study` event for `wait_for_user`). The agent reads the files named by `get_study_plan` with the application's read-only actions, records what it learned with `record_understanding {topic, summary, files}`, and ends with `finish_study`.
5. THE Core SHALL track which files the agent actually read (targets of read-only actions it executed). A `record_understanding` entry SHALL list its files as `read` or `not read`, and the tutor's context SHALL say which parts of the project it has read and which it has not.
6. THE Core SHALL keep the study brief per project on disk (`~/.wysp/projects/`), and WHEN the same project is opened again SHALL offer to reuse it (marked as possibly out of date) or to study again.
7. THE Panel SHALL show the offer, the progress (files mapped, files read) and a way to stop. THE Core SHALL publish the state as `explore.state` messages.
8. THE tutor SHALL speak with certainty only about what is in the map, the brief or what it read, and SHALL say plainly what it has not read yet.
9. THE study phase SHALL use only read-only tools. Code text read this way goes to the model like any other read tool result, and the map carries names and signatures, never code bodies.
