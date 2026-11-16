# Implementation Plan: Core Orchestrator

Owners: A = Core & Contract, B = Experience, C = Adapters. Gates: J0 Wed 11 Nov, J1 Thu 19 Nov, J2 Fri 27 Nov, J3 Tue 1 Dec.
Depends on adapter-contract tasks 2, 3 and 6. Property-test tasks are required.

- [x] 1. Create the Core service skeleton and CLI
  - `core/` package `wysp_core` with FastAPI app factory, `wysp serve` (uvicorn on 127.0.0.1:8765, `--port`, `--llm`, `--mock`, `--scenario`, `--unsafe-bind`), `/api/health`
  - `store/`: `~/.wysp/` layout, pairing token (user-only permissions), `config.toml`, redaction helper
  - Serve `panel/dist` at `/` when present
  - _Owner: A_ · _Gate: J0_
  - _Requirements: 1.1, 1.2, 1.3, 11.1_

- [ ] 1.1 Write property test for redaction
  - **Property CORE-P11: Redaction**
  - **Validates: Requirements 9.3, 11.2**

- [x] 2. Implement the adapter gateway and registry
  - `/ws/adapter` JSON-RPC server: hello validation (token, version, manifest), Origin allowlist, heartbeat watchdog (45 s), reconnection by `adapter_id`
  - `AdapterProxy` with typed async methods and per-method budgets, `TIMEOUT` mapping
  - Registry with change notifications; automatic activation when only one adapter is connected
  - _Owner: A_ · _Gate: J0_
  - _Requirements: 2.1, 2.3, 2.4 (contract 1.1–1.7, 9.3)_

- [x] 3. Implement the session, event bus and conversation memory
  - `Session` (active adapter, profile id, board, narration cursor, proposals), `EventBus` (asyncio pub/sub with typed topics), memory with rolling summary
  - _Owner: A_ · _Gate: J0_
  - _Requirements: 2.2, 8.1_

- [x] 4. Implement the UI protocol server
  - `contract/ui.py` message models (exported to schemas and TS types), `/ws/ui` with Origin check, initial `session.state`, `adapters.list`, `board.snapshot`
  - Routing of Panel messages to the session; test UI client helper for scenario tests
  - _Owner: B (review: A)_ · _Gate: J0 (hello), J1 (all messages)_
  - _Requirements: 2.1, 2.2, 5.4_

- [x] 5. Implement the LLM provider layer
  - `LLMProvider` protocol and events, `ScriptedLLM` with scenario YAML, `OpenAICompatProvider` (streaming + tool calls), configuration from `WYSP_LLM_*`
  - Secrets never logged; retry once with backoff; 20 s timeout
  - _Owner: A_ · _Gate: J1_
  - _Requirements: 9.1, 9.2, 9.3, 3.5_

- [ ]* 5.1 Add an Amazon Bedrock provider
  - `BedrockProvider` (Converse API with tool use), for teams with AWS credits
  - _Owner: A_
  - _Requirements: 9.2_

- [x] 6. Implement the board model, projection and provenance validator
  - `board/model.py`, `board/ops.py` (apply + patch building), `board/projection.py`, `board/provenance.py`, grouping above 60 nodes
  - Golden fixtures `contract-tests/fixtures/board/*.json` (initial board, ops, expected board) for the Panel
  - Board refresh on `event.state_changed` when changed refs intersect board refs
  - _Owner: A_ · _Gate: J1_
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [ ] 6.1 Write property tests for the board
  - **Property CORE-P1: Provenance soundness**
  - **Property CORE-P2: The LLM cannot create observed facts**
  - **Property CORE-P3: Patch convergence**
  - **Property CORE-P9: Board size bound**
  - **Property CORE-P12: Projection determinism**
  - **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.6**

- [x] 7. Implement the permission gate and the action pipeline
  - `trust/policy.py` (data-driven, profile overrides stricter only), `trust/gate.py` (proposal state machine, 60 s expiry, grants), `trust/undo.py`, `trust/audit.py` (JSONL, redacted)
  - Pipeline: validate params, gate, execute, observe, evaluate postconditions (contract predicates), auto-undo on failure, evidence, board update
  - Guide mode: publish `guide.ui_path` as steps, highlight targets, verify on user-origin events
  - Undo of the last Wysp change on request
  - _Owner: A_ · _Gate: J1_
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8_

- [ ] 7.1 Write property tests for the gate and the pipeline
  - **Property CORE-P4: Gate policy**
  - **Property CORE-P5: Audit completeness**
  - **Property CORE-P6: Verify or undo**
  - **Validates: Requirements 7.2, 7.3, 7.4, 7.5, 7.8**

- [x] 8. Implement the orchestrator turn loop, tools and prompts
  - `TurnRunner` with CancelToken, 8 tool rounds, status publication, clarification flow
  - Tool specs and handlers of design.md, capability filtering, structured tool errors
  - `ContextBuilder` (6k-token budget, `<app_data>` wrapping), generic prompts in `orchestrator/prompts/`
  - _Owner: A_ · _Gate: J1_
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.6, 4.1, 4.2, 4.3, 4.4_

- [ ] 8.1 Write property test for capability-based tool filtering
  - **Property CORE-P10: Tools follow capabilities**
  - **Validates: Requirement 4.2**

- [x] 9. Implement narration, interruption and resume
  - Segment builder (≤ 300 chars, cue validation against board node ids), playback cursor from `narration.progress`, `narration.cancel` within 100 ms, `user.continue`, "Why?" turns from `board.ask_why`
  - _Owner: B (review: A)_ · _Gate: J1 (text), J2 (with voice)_
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [ ] 9.1 Write property tests for interruption and resume
  - **Property CORE-P7: Interruption**
  - **Property CORE-P8: Resume**
  - **Validates: Requirements 6.2, 6.3**

- [x] 10. Implement event-driven behaviour
  - Event fan-out to board, pedagogy and orchestrator; unsolicited-turn throttle (30 s) for acknowledgements and help after two failed attempts
  - Stale board on adapter disconnection and recovery on reconnection
  - _Owner: A_ · _Gate: J2_
  - _Requirements: 8.1, 8.2, 8.3, 2.4_

- [x] 11. Implement the TTS proxy
  - `POST /api/tts {segment_id}` streaming audio from the configured provider, only for segments of the current session, cache by text hash, `503` fallback
  - _Owner: B_ · _Gate: J2_
  - _Requirements: 10.1, 10.2, 10.3_

- [x] 12. Write scenario tests with ScriptedLLM and the mock adapter
  - Explain-and-show, interruption and resume, permission approve/deny/timeout, verify-or-undo with an injected failing postcondition, guide mode verified by `simulate_user`
  - _Owner: A_ · _Gate: J1 (first three), J2 (all)_
  - _Requirements: 3.1, 6.2, 6.3, 7.2–7.7_

- [ ]* 13. Expose a read-only MCP bridge for development
  - `wysp mcp-bridge --read-only`: MCP server with tools `list_adapters`, `observe`, `get_board`, `get_audit_tail`, so that Kiro can inspect a running tutor while we build it (`wysp-dev` in `docs/kiro/mcp.example.json`)
  - _Owner: A_ · _Gate: J2, only if on schedule_
  - _Requirements: 11.1_

- [ ] 14. Checkpoint: Core ready for both tutors
  - All required tasks done, scenario tests green, boundary check clean, no application vocabulary in `core/`
  - Ask the user if questions arise

- [x] 15. Fewer LLM requests and visible approvals (from the session log of 2026-11-10)
  - A turn ends after a round that narrated using display tools only (`DISPLAY_TOOLS` in `orchestrator/turn.py`); the prompt asks for board and narration in one response, and to offer exercises rather than start them
  - Approvals that need the user are announced aloud; a message identical to the one that started the turn does not cancel a pending approval (`Session.user_message`), any other message still does
  - Every UI protocol message is recorded (`ui.message`, with `client` browser or native)
  - `POST /api/tts` with local voices, origin-checked like the WebSockets, no CORS headers
  - Tests: `contract-tests/tests/test_core_with_mock.py` (turn end, announced approval, repeat vs. new message, UI message log, TTS endpoint with a fake provider)
  - _Owner: A_ · _Gate: J2_

- [x] 16. One response per answer (from the session log of 2026-11-10: 5 model requests per turn, up to 111 s)
  - The model in use (gpt-oss on Groq) returns one tool call per response, so `narrate` can carry the board (`board.show`, `board.concepts`) and the whole answer fits in one request; `add_concept` takes `items` (steps chained) with optional `key` so cues can target `c:<key>`
  - Prompt rewritten around that; answers how-to questions before asking anything; past replies kept as a gist in the history; `observe` reports an unknown root; profiles can give `speech_hints`, sent with board and observed names as Whisper's prompt
  - Measured live on Groq: "how do I make a cube" 111 s / 5 requests -> 2.6 s / 1 request; "diagram of the steps" 35 s -> 3.8 s
  - _Owner: A_ · _Gate: J2_

- [ ] 17. Survey the application when it becomes active (decision of 2026-11-13: contract stays 1.0.0, on by default, opt-out)
  - `session/survey.py` (survey task, bounded rendering, retry, stale refresh), hook in `Session._on_new_active` and `state_changed`, survey block in `build_system_prompt`, `--no-survey` / `WYSP_SURVEY=off`
  - Tests: CORE-P13, CORE-P14 (Hypothesis) and scenario tests with the mock adapter (survey fills `observed_refs`, a slow survey does not block, opt-out, retry, stale refresh)
  - Then the adapters: IntelliJ project-wide pass inside `level=full` (file tree, symbols, project problems; sensitive and noise filters reused, no code text), Blender cap fix and scene facts
  - _Owner: A (Core), C (adapters)_ - _Gate: J2_
  - _Requirements: 12.1-12.9_

- [x] 18. One Panel speaks (live run of 2026-11-13: a second Panel read every sentence again)
  - `UiHub` elects the speaker (last Panel the user acted in, else the first); `narration.segment` carries `speaker`; progress and cues from other Panels are ignored; the Panel stays silent when it is not the speaker; stale utterance events no longer finish the current segment
  - Tests: `contract-tests/tests/test_single_speaker.py`
  - _Owner: A (Core), B (Panel)_ - _Gate: J2_
  - _Requirements: 14.1, 14.2_

- [ ] 20. Project exploration: code map and study phase (decision of 2026-11-15, the user asks first)
  - Profile `explore` section; `session/explore.py` (code map, crawl with budget, study plan, brief, coverage, persistence); tools `code_map`, `get_study_plan`, `record_understanding`, `finish_study`; `explore.start` / `explore.stop` / `explore.state` in the UI protocol; `study` inbox event and the tutor agent's instructions; Panel card (offer, progress, stop); survey retries with longer backoff; "Wysp" in the speech hints
  - IntelliJ adapter: `observe {level: full, root: <dir|file|project>}` returns that subtree with symbols, sizes and resolved dependencies (`intellij-tutor` Requirement 12)
  - Tests: CORE-P15, CORE-P16, scenario tests with a synthetic project tree, platform test for the subtree observation
  - _Owner: A (Core), C (adapter), B (Panel)_ - _Gate: J2_
  - _Requirements: 15.1-15.9_

- [ ] 19. Persistent highlights' (contract 1.1.0, decision of 2026-11-13)
  - Contract: `duration_ms` 0, `adapter.clear_highlight`, `event.highlight_dismissed`; Core: active highlight, `clear_highlight` tool, clearing rules, prompt; mock adapter and Python SDK; IntelliJ adapter (persistent code and UI highlights, dismissal when the user clicks, edits or moves into the element); Blender stays on timed highlights until it moves to 1.1
  - Tests: contract kit and Core scenario tests with the mock adapter, platform test for the IntelliJ highlighter
  - _Owner: A (contract, Core), C (adapters)_ - _Gate: J2_
  - _Requirements: 13.1-13.6, adapter-contract 8.3-8.6, 7.5_
