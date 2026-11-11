---
inclusion: always
---

# Repository Structure and Boundaries

## Layout

```
.kiro/                 Kiro steering, specs, hooks, agents, MCP settings (shared, committed)
core/                  Wysp Core, Python package `wysp_core`                          (owner: A)
  src/wysp_core/
    contract/          Pydantic models (source of truth of the contract) + JSON Schema export
    gateway/           WebSocket JSON-RPC server for adapters, AdapterProxy, registry
    ui_api/            WebSocket server for the Panel, static Panel hosting, /api/tts    (owner: B)
    session/           Session, event bus, conversation memory, context builder
    orchestrator/      Tutor loop, LLM tools, generic prompts
    llm/               LLM provider interface, providers, ScriptedLLM
    board/             Visual model, board operations, projection, provenance validator
    narration/         Narration segments, cues, interruption and resume                (owner: B)
    pedagogy/          Profiles, skill graph, learner model, lessons, exercises
    verification/      Predicate evaluation (JMESPath) and evidence
    trust/             Permission gate, policy, undo stack, audit log
    store/             Local persistence under ~/.wysp/
    cli.py             `wysp` command line
  tests/
schemas/               Generated JSON Schemas of the contract (never edit by hand)     (owner: A)
contract-tests/        Contract Test Kit, harness, mock adapter                        (owner: A)
sdk/python/            Python adapter SDK `wysp_adapter_sdk` (embedded hosts)          (owner: C)
sdk/ts/                TypeScript SDK `@wysp/adapter-sdk` (generated types + client)   (owner: C, types: A)
panel/                 React Panel: board, captions, voice, dialogs                    (owner: B)
apps/
  blender-tutor/       Application 1                                                   (owner: C)
    adapter/           Blender extension: blender_manifest.toml, actions/, observe, events, highlight
    profile/           profile.yaml, concepts.yaml, lessons/*.yaml                    (owner: B, review: C)
    demo/              Script that builds the demo scene
    contract.fixture.yaml
  intellij-tutor/      Application 2                                                   (owner: C)
    plugin/            IntelliJ Platform plugin (Kotlin, Gradle): actions/, observe, highlight, tool window
    profile/           IntelliJ tutor profile                                         (owner: B)
    demo/sample-project/  Small project used in the demo and end-to-end checks
    contract.fixture.yaml
  web-tutor/           Deferred (planned Chrome extension; replaced by intellij-tutor as application 2)
docs/                  Architecture document (LaTeX), adapter guide, Kiro usage journal
scripts/               Dev scripts and the Kiro hook dispatcher (scripts/kiro/hook.py)
```

## Boundary rules
Enforced by `scripts/kiro/hook.py boundaries`, by a Kiro hook and by CI.

1. `core/` never imports from `apps/`, `sdk/` or any host API (`bpy`, browser APIs) and contains no application vocabulary (Blender, Chrome, DOM, modifier names...). Core tests use the mock adapter only. A line can opt out with the comment `# wysp: allow-app-term`, and every opt-out must be justified in review.
2. Adapters depend on the contract only: generated schemas or types and the SDKs. They never import Core internals.
3. The Panel talks to the Core only through the UI protocol (`/ws/ui`, `/api/*`). No tutoring logic in the Panel.
4. App knowledge goes into profiles (data) or adapters (code), never into Core prompts. Core prompts are generic and receive app context from the manifest and the profile.
5. `schemas/` and `sdk/ts/src/generated/` are generated. Edit the Pydantic models instead.

## Naming conventions
- Adapter actions: one file per action, `apps/<tutor>/adapter/actions/<verb>_<object>.py` (Blender) or `apps/<tutor>/extension/src/actions/<verb>_<object>.ts` (web). The action id is the file name (`<verb>_<object>`, snake_case).
- Lessons: `apps/<tutor>/profile/lessons/L<NN>_<slug>.yaml`. Lesson ids are dotted: `<tutor>.<topic>.<name>`.
- Skills and concepts: `snake_case` ids, unique within a profile.
- Entity refs: `<scheme>://<path>`, one scheme per adapter (`blender://`, `web://`, `mock://`).
- JSON-RPC methods: `wysp.*` (session), `adapter.*` (Core to adapter requests), `event.*` (adapter to Core notifications).
- Python: snake_case modules, PascalCase classes, type hints everywhere. TypeScript: camelCase, PascalCase components, no `any`.

## Ownership and collaboration
- **Person A**: Core & Contract. **Person B**: Experience (Panel, board, voice, demo dashboard, lesson content of both profiles, video). **Person C**: Adapters (SDKs, Blender adapter, Chrome extension).
- Each spec has one lead. Each task in `tasks.md` names its owner (`_Owner: A_`). Changing files owned by someone else requires their review.
- Contract change process (after gate J0):
  1. Update `.kiro/specs/adapter-contract/` first.
  2. Bump `contract_version`: minor for additive changes, major for breaking changes (avoid majors).
  3. Regenerate schemas and types.
  4. Run the contract kit on the mock adapter and on both tutors.
  5. Get approval from A and from the owner of each affected adapter.
- Trunk-based development: short branches `a/<topic>`, `b/<topic>`, `c/<topic>`, merged at least daily. Commit messages reference the spec task, for example `feat(core): permission gate [core-orchestrator 7]`.
