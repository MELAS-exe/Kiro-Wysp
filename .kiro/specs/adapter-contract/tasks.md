# Implementation Plan: Adapter Contract

Owners: A = Core & Contract, B = Experience, C = Adapters. Gates: J0 Wed 11 Nov, J1 Thu 19 Nov, J2 Fri 27 Nov, J3 Tue 1 Dec.
Property-test tasks are required (no `*`). Tasks marked `*` are optional.

- [x] 1. Scaffold the monorepo
  - Root `pyproject.toml` declaring a uv workspace with members `core`, `contract-tests`, `sdk/python`; Python 3.13; dev group with pytest, pytest-asyncio, hypothesis, ruff
  - Root `package.json` declaring npm workspaces `panel`, `sdk/ts`, `apps/web-tutor/extension`, `apps/web-tutor/demo-dashboard`; shared `tsconfig.base.json` (strict), eslint and prettier configs
  - `.gitignore` (keeps `.kiro/`), `.env.example`, `LICENSE` (MIT) and `apps/blender-tutor/adapter/LICENSE` (GPL-3.0-or-later)
  - GitHub Actions workflow: `uv sync`, `uv run pytest`, `npm ci`, `npm test --workspaces --if-present`, `python scripts/kiro/hook.py boundaries`
  - _Owner: A (npm part: B)_ · _Gate: J0_
  - _Requirements: 10.1_

- [x] 2. Define the contract models and the schema export
  - Create `core/src/wysp_core/contract/` with `rpc.py`, `manifest.py`, `observation.py`, `actions.py`, `events.py`, `errors.py` following the Data Models section of design.md
  - Implement `export.py` (`python -m wysp_core.contract.export`) writing `schemas/*.schema.json` and `schemas/index.json` with stable `$id`s and `contract_version = "1.0.0"`
  - Add a CI step that fails when `git diff --exit-code schemas` is not empty after export
  - _Owner: A_ · _Gate: J0_
  - _Requirements: 2.1, 2.2, 3.1, 3.2, 3.3, 5.1, 5.2, 6.1, 7.1, 9.1, 10.1, 10.2, 10.3_

- [ ] 2.1 Write property test for schema round trip
  - **Property CON-P1: Schema round trip**
  - **Validates: Requirements 10.1, 10.2**

- [x] 3. Implement the predicate language and the state digest
  - `contract/predicates.py`: parser, placeholder substitution with escaping, evaluator returning `PredicateOutcome(ok, actual, expected, path)`; regex timeout for `matches`
  - `contract/digest.py`: canonical JSON, volatile-props filtering, float rounding, SHA-256
  - _Owner: A_ · _Gate: J0_
  - _Requirements: 5.3, 6.5_

- [x] 3.1 Write property test for digest invariance
  - **Property CON-P4: Digest invariance**
  - **Validates: Requirement 6.5**

- [ ] 3.2 Write property test for safe placeholder substitution
  - **Property CON-P11: Safe placeholder substitution**
  - **Validates: Requirement 5.3**

- [ ] 4. Generate the TypeScript types
  - `sdk/ts` package with script `gen:types` (json-schema-to-typescript over `schemas/`) writing `sdk/ts/src/generated/`
  - CI fails when generated types differ from the committed ones
  - _Owner: A_ · _Gate: J0_
  - _Requirements: 10.2_

- [ ] 5. Write cross-language golden protocol fixtures
  - `contract-tests/fixtures/protocol/valid/*.json` and `invalid/*.json` (hello, observe result, action spec, results, events, errors)
  - Python test validating them with the models; TypeScript test validating them with ajv against `schemas/`
  - _Owner: A_ · _Gate: J0_
  - _Requirements: 10.2_

- [x] 6. Build the mock Kanban adapter
  - `contract-tests/wysp_mock/`: in-memory Kanban state, entity projection, the seven actions of design.md with undo, events with origin tagging, debounce
  - In-process API (`MockKanban.simulate_user`) and CLI `wysp-mock-adapter` with fault injection options
  - Uses its own minimal WebSocket client (`websockets`) so that it does not depend on the SDK
  - _Owner: A_ · _Gate: J0_
  - _Requirements: 12.1, 12.3, 1.2, 1.5, 6.1, 6.4, 6.7, 7.1, 7.4_

- [x] 6.1 Write stateful property tests on the mock adapter
  - Hypothesis `RuleBasedStateMachine` mixing execute, undo and simulated user actions
  - **Property CON-P5: Invalid calls do not change state**
  - **Property CON-P6: Undo round trip**
  - **Property CON-P8: Monotonic state version**
  - **Property CON-P9: Origin tagging**
  - **Validates: Requirements 6.2, 6.3, 6.4, 6.5, 6.7, 7.1**

- [x] 7. Build the Python adapter SDK
  - `sdk/python/wysp_adapter_sdk/`: `AdapterClient` on `websocket-client` in a background thread (hello, heartbeat, reconnect with backoff, request routing, budgets)
  - `ActionRegistry` (one module per action, id = file name, params validation with `jsonschema`), `Dispatcher` protocol with `ImmediateDispatcher` and `QueueDispatcher` (pumped by the host main thread)
  - Helpers: digest, ref building, error mapping, origin tagging context manager
  - Pure-Python dependencies only, so that it can be bundled as wheels in a Blender extension
  - _Owner: C_ · _Gate: J0 + 1 day_
  - _Requirements: 1.2, 1.5, 1.6, 6.2, 6.7, 9.2_

- [ ] 7.1 Write unit tests for the Python SDK
  - Dispatcher ordering, reconnect, budgets, error mapping, against the harness of task 9 or a local echo server
  - _Owner: C_
  - _Requirements: 1.5, 1.6, 9.3_

- [ ] 8. Build the TypeScript adapter SDK
  - `sdk/ts/src/`: `AdapterClient` designed for MV3 service workers (heartbeat ≤ 20 s, reconnect, re-hello, no in-memory-only state), `defineAction()` helper, ajv validation, error helpers
  - _Owner: C_ · _Gate: Sun 22 Nov (after the Blender end-to-end of J1)_

- [ ] 8.1 Write unit tests for the TypeScript SDK
  - Vitest with a mock WebSocket: hello order, heartbeat timing, reconnect, request routing
  - _Owner: C_
  - _Requirements: 1.5, 1.6_

- [ ] 9. Build the Contract Test Kit
  - `contract-tests/wysp_contract/`: harness server (independent from `wysp_core.gateway`), fixture loader, launcher (`command`, `playwright`, `in_process`), checks listed in design.md, recordings with redaction, JUnit report, CLI `wysp-contract`
  - `--offline` mode: validate the fixture and re-validate the latest recording against current schemas
  - `apps/<tutor>/contract.fixture.yaml` schema published in `schemas/`
  - _Owner: A_ · _Gate: J1 (online checks needed by C on Mon 16 Nov)_
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5_

- [ ] 9.1 Implement observation property checks in the Kit
  - **Property CON-P2: Observation referential integrity**
  - **Property CON-P3: Ref and digest stability**
  - **Property CON-P7: Postconditions hold**
  - **Property CON-P10: Size limits**
  - **Validates: Requirements 2.5, 3.3, 3.4, 3.5, 3.6, 5.3, 6.1**

- [ ] 10. Run the Kit against the mock adapter in CI
  - Normal job and fault-injection job (latency 300 ms, fail rate 0.1, one disconnect)
  - _Owner: A_ · _Gate: J1_
  - _Requirements: 12.2, 11.3_

- [ ] 11. Write the adapter author guide
  - `docs/adapter-guide.md`: "build your own tutor in four steps" (manifest, observe, actions, profile), with the mock adapter as a worked example; linked from the root README
  - _Owner: C (review: A)_ · _Gate: J3_
  - _Requirements: 2.1, 5.1, 11.1_

- [ ]* 12. Add a `visual` integration-level demo adapter
  - Screenshot plus OCR prototype that emits low-confidence entities, to illustrate the third integration level in the README
  - _Owner: C_ · _Gate: after J3, only if time allows_
  - _Requirements: 3.7_

- [ ] 13. Checkpoint: contract frozen for J1
  - All tasks above (except optional ones) done, Kit green on the mock adapter, schemas and types committed, contract version tagged `contract-v1.0.0`
  - Ask the user if questions arise
