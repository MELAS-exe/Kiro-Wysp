---
inclusion: always
---

# Testing Guidelines

## Principles
- Every component must be testable without the real application: use the **mock adapter** (`contract-tests/`), the **ScriptedLLM** provider and recorded fixtures.
- Correctness properties listed in each spec's `design.md` are implemented as property-based tests (Hypothesis in Python, fast-check in TypeScript). Property tasks without the `*` marker in `tasks.md` are required, not optional.
- Tests run in seconds locally. Anything slow or needing Blender or Chrome is marked (`@pytest.mark.live`, separate Playwright project) and runs on demand and in CI.

## Layers

| Layer | Tooling | Location |
|---|---|---|
| Unit | pytest / Vitest | next to each package (`core/tests`, `panel/src/**/*.test.ts`, ...) |
| Property-based | Hypothesis / fast-check | same places; names start with `test_prop_` (Python) or `prop:` (TS) and cite the property id |
| Contract | Contract Test Kit (pytest) | `contract-tests/`, configured by `apps/<tutor>/contract.fixture.yaml` |
| Cross-language golden fixtures | JSON files read by Python and TS tests | `contract-tests/fixtures/` (board patches, predicates, protocol messages) |
| End-to-end smoke | ScriptedLLM + real adapters | `scripts/demo_smoke.py` *(planned)* |

## Rules
- Property ids follow `<SPEC>-P<n>`: `CON` (adapter-contract), `CORE` (core-orchestrator), `PED` (pedagogy-verification), `PAN` (tutor-panel), `BLD` (blender-tutor), `WEB` (web-tutor).
- A bug fix starts with a failing test.
- Do not mock the contract. Adapters are tested through the Kit; the Core is tested against the mock adapter over a real WebSocket.
- Blender logic that does not need the UI is tested with `bpy` from PyPI. Code that depends on the main-thread dispatcher is tested with a manual dispatcher.
- The Chrome extension's snapshot and locator logic is tested on generated DOMs (happy-dom). The full extension is tested with Playwright against the demo dashboard.
- Automated tests never call real LLM, STT or TTS providers.

## Commands *(planned)*
- `uv run pytest`: all Python tests except `live`.
- `uv run pytest -m live`: tests that need a running Blender or Chrome.
- `npm test --workspaces --if-present`: all TypeScript tests.
- `uv run wysp-contract --tutor <tutor>`: contract kit against a connected adapter.
