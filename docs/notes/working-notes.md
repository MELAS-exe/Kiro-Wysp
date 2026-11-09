# Working notes (Kiro session, 9 Nov 2026)

Temporary notes used while drafting the architecture document and the Kiro setup.

## Facts checked
- Kiroween 2026: submissions 30 Oct to 4 Dec 2026, 14:00 Pacific (= 22:00 GMT, Dakar). New projects only.
  Rules page (kiroween.devpost.com/rules) returned HTTP 403 to automated fetch: re-check manually.
- Reference repo Harpita-P/Kiro-InteractionKit (Grand Prize 2025):
  - core `kiro_interaction_kit/` (3 controllers, 18 gesture pure functions HA1..HA9, HE1..HE6, FA1..FA3).
  - `my_apps/` Math-O-Lantern (870 lines, 7 classes, one main.py) and Holo-Board (1,883 lines, 5 classes).
  - `.kiro/`: 5 steering (product, tech, structure, testing, game-development [manual]),
    2 specs (EARS requirements, design with 19 / 26 correctness properties, tasks 13 / 12 done),
    optional property/unit test tasks left undone (22 / 14), 3 hooks (legacy `.kiro.hook`, askAgent:
    auto-integrate a new gesture into controller, state, test demo, README), MCP Context7.
  - setup.sh/.bat, README with GIFs, MIT license, "delete the 2 apps and create your spec" onboarding.
- Kiro formats (kiro.dev, IDE 1.x + CLI V3): hooks in `.kiro/hooks/*.json` (`version: v1`, trigger,
  matcher regex, action command|agent, enabled); file triggers fire only on agent edits; agents in
  `.kiro/agents/*.md|json`; skills `.kiro/skills/<name>/SKILL.md`; MCP `.kiro/settings/mcp.json`.
- Blender 5.2 LTS (14 Jul 2026, Python 3.13); `bpy` on PyPI (Python 3.13) for headless tests.
  Blender add-ons: GPL-3.0-or-later.
- Chrome MV3: WebSocket messages within 30 s keep the service worker alive (Chrome 116+).
- LaTeX: Tectonic 0.17 at `~/bin/tectonic.exe` (works: tikz, tcolorbox, pgfgantt, pgf-umlsd, listings);
  also Docker image texlive:latest-medium.
- Local machine: Python 3.14, Node 24.18, no uv, npm.ps1 blocked by execution policy (use npm.cmd).
- Repo: no commits yet, remote origin MELAS-exe/Kiro-Wysp.

## Key decisions (ADR-style)
1. Contract = JSON-RPC 2.0 over WebSocket; adapters are clients, Core is server on 127.0.0.1:8765.
2. Pydantic v2 models = source of truth -> JSON Schema (schemas/) -> generated TS types.
3. Generic observation model = Entity Graph (refs URI, kinds declared in manifest, links, focus).
4. Verification evaluated by the Core: fresh observe + JMESPath predicates -> evidence.
5. LLM never executes: propose_action -> permission gate -> execute -> verify -> auto-undo on failure.
6. Provenance observed / inferred / illustrative; observed nodes created by projection only; validator.
7. Voice = cascaded pipeline (STT browser -> text core -> TTS via core proxy); push-to-talk + VAD barge-in.
8. One React panel served by the Core, shown in a Chrome app window next to the target app.
9. Learner model = simplified BKT; evidence verified 1.0 / answered 0.6 / declared 0.3; origin=wysp never counts.
10. Blender adapter: 5.2 LTS extension, websocket-client thread + bpy.app.timers main-thread pump, data API, compensation undo + undo_push.
11. Web adapter: MV3, SW holds WS (heartbeat 20 s), content script a11y snapshot (dom-accessibility-api), role+name locators, shadow-DOM overlay, allowlist + redaction.
12. Monorepo: uv workspace + npm workspaces. MIT + GPL-3.0-or-later for the Blender add-on folder.
13. Tests: contract kit (harness plays the Core), mock adapter (Kanban domain), Hypothesis / fast-check, shared JSON golden fixtures.
14. Repo artifacts (.kiro, code, README) in English for the jury; team document in French.

## Team split
- A: Core & Contract (contract models, gateway, orchestrator, LLM, board model, trust, pedagogy engine, kit, mock).
- B: Experience (panel, ui_api server, narration, board renderer, voice, demo dashboard, content of both profiles, visuals, video).
- C: Adapters (Python + TS SDKs, Blender adapter + demo scene, Chrome extension).

## Gates
- J0 Wed 11 Nov: contract v0.1, schemas, mock adapter, core serve + panel hello, CI.
- J1 Thu 19 Nov: Blender end-to-end in text mode (explain + board + permission + execute + verify + undo); dashboard v1.
- J2 Fri 27 Nov: browser tutor end-to-end without app code in core; voice + interruption.
- J3 Tue 1 Dec: exercises + evidence both apps, docs, CI green, feature freeze.
- Submit Fri 4 Dec before 12:00 GMT.
