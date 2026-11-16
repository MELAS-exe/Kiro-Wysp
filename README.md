<p align="center"><img src="docs/brand/lockup-color-dark.png" alt="Wysp" width="460"></p>

# Wysp

**A skeleton for building AI tutors for software applications.** A Wysp tutor observes the real state of an application, explains its concepts on an interactive visual board, guides the user through actions with permission, and verifies in the application what the user has learned. It works by voice, with a board, and through one adapter per application.

Wysp is our entry for **Kiroween 2026, category Skeleton Crew**. One shared core (Wysp Core) powers two very different tutors:

| Tutor | Folder | Integration level | Demo |
|---|---|---|---|
| Blender tutor | `apps/blender-tutor/` | native (Blender 5.2 Python API) | explain an object's modifier stack, add a Bevel with permission, verify it |
| IntelliJ tutor | `apps/intellij-tutor/` | native (IntelliJ Platform API: project model, code structure, editors, Swing UI) | explore the student's project, explain the function under the caret, point at the IDE control, guide a rename refactoring and verify it |

> **Status (16 Nov 2026): both tutors run end to end on the same Core and Panel,** with lessons and exercises that Wysp verifies in the application, and an optional Chrome connector (`apps/web-tutor`) as a third application. The Blender tutor and the IntelliJ tutor are working prototypes. Specs, steering, hooks and agents are in `.kiro/`.

![The Panel in guide mode on the Blender demo scene](docs/img/panel-guide.png)

## How it works

```
Blender extension ─┐                         ┌─ Panel (React): board, captions, voice, permissions
                   ├─ JSON-RPC / WebSocket ─ Wysp Core (Python) ─┤
IntelliJ plugin ───┘   (adapter contract)    └─ LLM with tool calling, text-to-speech
```

- **Adapter contract**: `observe`, `get_context`, `get_actions`, `execute`, `undo`, `highlight`, events. Defined once as Pydantic models, exported to JSON Schema and TypeScript.
- **Trust rules**: every fact is labelled `observed`, `inferred` or `illustrative`; the LLM can only *propose* actions; a permission gate decides; every action is verified afterwards and undone if verification fails.
- **Contract Test Kit**: the same contract fixtures run against the mock adapter, the Blender tutor and the IntelliJ tutor.

To build your own tutor, start with the [adapter guide](docs/adapter-guide.md) (its example adapter is tested). The architecture document (English, 25 pages) is [`docs/architecture/wysp-architecture.pdf`](docs/architecture/wysp-architecture.pdf); the French design document written before the implementation is kept in [`docs/architecture/fr/`](docs/architecture/fr/). The normative specs (in English) are in [`.kiro/specs/`](.kiro/specs/).

## Try it in two minutes (no application, no account, no key)

Needs Python 3.13 with [uv](https://docs.astral.sh/uv/) and Node 24. A small mock Kanban application stands in for Blender or IntelliJ, and a scripted model replays a scenario, so nothing leaves your machine.

```powershell
uv sync
npm install; npm run build -w panel          # npm.cmd if PowerShell blocks npm
uv run wysp serve --llm scripted --scenario contract-tests/wysp_mock/scenario.yaml
# in a second terminal:
uv run wysp-mock-adapter
# open http://127.0.0.1:8765 and ask: "explain this board", then "help me move the card" or "do it for me"
```

You will see the board build from the application's real entities, the highlight, the permission prompt for "do it for me", the verification and the undo. The same Core and Panel then drive Blender, IntelliJ IDEA and Chrome below.

## Run it with the real applications (Windows)

Prerequisites: Python 3.13 with [uv](https://docs.astral.sh/uv/), Node 24, Chrome, Blender 5.2 LTS (Blender tutor), IntelliJ IDEA 2026.2 (IntelliJ tutor).

Prerequisites: Python 3.13 with [uv](https://docs.astral.sh/uv/), Node 24, Chrome, Blender 5.2 LTS.

```powershell
uv sync                         # Python workspace
npm install; npm run build -w panel   # use npm.cmd if PowerShell blocks npm
copy .env.example .env          # optional: add a free GROQ_API_KEY (console.groq.com/keys) for a fast LLM
```

**1. Core + headless Blender (quickest)**

```powershell
scripts\dev_up.ps1                                   # Core on http://127.0.0.1:8765 + headless Blender with the demo scene
# offline and deterministic (no LLM account needed):
scripts\dev_up.ps1 -Llm scripted -Scenario apps\blender-tutor\demo\scenario.yaml
uv run python scripts\dev_chat.py                    # terminal Panel, or open http://127.0.0.1:8765
scripts\dev_down.ps1                                 # stop everything
```

**2. With the Blender interface**

```powershell
uv run python scripts\build_blender_extension.py --install   # builds and installs the extension
uv run wysp serve                                            # then in Blender: sidebar (N) > Wysp > Connect
```

Everything also works from inside Blender: the **Wysp** sidebar tab has the chat, permission prompts
(Approve / Deny / Allow for this lesson) and the guided steps, and **Open Board** shows the board as a node
tree in its own window (or in the Timeline area). Wysp can point at the interface itself: editors, viewport
regions and Properties tabs (`blender://ui/...` refs). Wysp speaks in Blender with the voices installed in
Windows (offline), and you can talk to it: hold Alt+Space and speak (transcribed by Whisper on Groq; the clip is sent
to Groq, `WYSP_STT_PROVIDER=none` turns it off). The browser Panel (http://127.0.0.1:8765) has voice too.

**Logs and performance.** Each Core session and each Blender session writes a JSONL log to `~/.wysp/logs/`
(level `full` by default, `WYSP_LOG=off|basic|full`, `wysp serve --log ...`, or live from either Panel).

```powershell
uv run wysp logs list        # log files, newest first
uv run wysp logs summary     # latency (turns, LLM, tools, Blender queue), rate limits, guides, findings
uv run wysp logs timeline    # Core and Blender records merged in time order
```

**3. In IntelliJ IDEA 2026.2.** Build and install the plugin (`apps\intellij-tutor\plugin\gradlew.bat buildPlugin`, then Settings > Plugins > Install Plugin from Disk), start the Core and open a project: the plugin connects by itself and the **Wysp** tool window shows the Panel. Details, actions and privacy notes: [`apps/intellij-tutor/README.md`](apps/intellij-tutor/README.md). Offline demo: `uv run wysp serve --llm scripted --scenario apps\intellij-tutor\demo\scenario.yaml` with `apps/intellij-tutor/demo/sample-project`.

**4. In Chrome (optional extra).** Build the extension (`npm run build -w apps/web-tutor/extension`), load `apps/web-tutor/extension/dist` unpacked, start the Core with `WYSP_ALLOWED_ORIGINS=chrome-extension://cnmikeniefgoeibijogfncggjkafakhk`, paste the token from `~/.wysp/token` on the extension's options page, allow `http://localhost:5180` and click the Wysp icon: the Panel opens in the side panel. Demo page: `node apps/web-tutor/demo-dashboard/serve.mjs`. Details and privacy notes: [`apps/web-tutor/README.md`](apps/web-tutor/README.md).

**Voice.** Speech for Panels without their own voice is offline: Windows voices, or a natural female neural voice (Kokoro, Apache-2.0): `uv sync --all-packages --extra voice`, `uv run wysp install-voice`, then `WYSP_TTS_PROVIDER=kokoro` (see `.env.example`).

**LLM providers.** `auto` picks the first of Groq, Cerebras, OpenRouter whose key is in `.env`, otherwise keyless
Pollinations (works, but stalls on about every second request). `--llm scripted` replays a scenario offline.

**Bring your own AI CLI.** `--llm external` runs the Core without a model and serves an authenticated MCP endpoint (`/mcp`): Claude Code, kiro-cli or any MCP client does the thinking and calls the Wysp tools, while the board, voice, permission gate and verification stay in Wysp. See [`docs/agent-mode.md`](docs/agent-mode.md) and `uv run wysp mcp-config`.

## Tests

```powershell
uv run pytest                                              # about 370 tests: contract, Core, pedagogy, property tests, end-to-end with the mock adapter
uv run pytest -m live -o addopts="" apps\blender-tutor\tests   # live tests inside a real headless Blender
npm test -w panel                                          # Panel unit, accessibility and property tests
npm test -w apps/web-tutor/extension                        # Chrome extension
apps\intellij-tutor\plugin\gradlew.bat test                 # IntelliJ plugin unit and platform tests
uv run wysp-contract --tutor blender-tutor                  # online Contract Test Kit (also: web-tutor, --mock, --offline)
uv run python scripts\kiro\hook.py boundaries              # the Core must stay application-agnostic
```

## Build your own tutor in four steps (see `docs/adapter-guide.md`)

1. **Manifest**: id, integration level, capabilities, entity kinds, ref scheme.
2. **Observation**: map the application state to entities (the SDK gives you the client, state digest and validation).
3. **Actions**: one file per action with params schema, risk level, postconditions and UI path.
4. **Profile**: skills, concepts, lessons and exercises in YAML.

Then `uv run wysp-contract --tutor <name>` tells you whether your adapter is compliant. No change to the core or the Panel is needed.

## How we use Kiro

| Kiro feature | Where | What it does for us |
|---|---|---|
| Specs | `.kiro/specs/` | 7 specs (contract, core, pedagogy, panel, Blender tutor, IntelliJ tutor, web tutor as an optional extra), EARS requirements, correctness properties, tasks with owner and milestone |
| Steering | `.kiro/steering/` | product vocabulary, structure and boundaries, trust and safety, testing, contract guide, pedagogy, UI design system, demo and release checklists |
| Hooks | `.kiro/hooks/` | core boundary guard, schema sync, offline contract checks, trust review, new-action integration, formatting, profile validation, tests after each task |
| Agents | `.kiro/agents/` | `blender-adapter`, `browser-adapter`, `contract-guardian` (read-only reviewer) |
| MCP | `docs/kiro/mcp.example.json` | Context7 (up-to-date docs), Playwright, and `uv run wysp mcp-bridge` (read-only stdio bridge to a running tutor) |

Hooks call `scripts/kiro/hook.py`, a standard-library Python script that CI runs too.

## Repository layout

```
.kiro/          specs, steering, hooks, agents
core/           Wysp Core (Python)
contract-tests/ Contract Test Kit and mock adapter
sdk/            adapter SDKs (Python, TypeScript)
panel/          shared React Panel
apps/           blender-tutor/, intellij-tutor/ (web-tutor/ optional extra)
docs/           architecture document, adapter guide, Kiro journal
scripts/        dev scripts and the Kiro hook dispatcher
```

## License

MIT (see `LICENSE`). The Blender extension in `apps/blender-tutor/adapter/` will be licensed GPL-3.0-or-later, as required for Blender add-ons.
