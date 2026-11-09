---
inclusion: always
---

# Technology Stack

> Commands marked *(planned)* are created by spec tasks. Before relying on one, check that the file or script it uses exists.

## Languages and runtimes
- **Python 3.13** for Wysp Core, the Python adapter SDK, the contract test kit and the Blender adapter (Blender 5.2 LTS embeds Python 3.13). Python projects are managed with **uv** (one uv workspace at the repo root).
- **TypeScript 5** (strict) on **Node 24 LTS** for the Panel, the TypeScript SDK, the Chrome extension and the demo dashboard. **npm workspaces** at the repo root.

## Wysp Core (`core/`)
- FastAPI + uvicorn (HTTP and WebSocket), Pydantic v2 (contract models are the single source of truth), `jmespath` (verification predicates), PyYAML (profiles), httpx (LLM and TTS providers).
- Tests: pytest, pytest-asyncio, Hypothesis (property-based tests). Lint and format: ruff.

## Panel (`panel/`)
- React 19 + Vite, `@xyflow/react` (React Flow 12) for the board, `elkjs` for graph and tree layouts, Zustand for state.
- Voice: Web Speech API for speech-to-text (default), text-to-speech through the Core's `/api/tts` proxy (provider keys stay server-side), browser `speechSynthesis` as offline fallback.
- Tests: Vitest, Testing Library, fast-check. Lint and format: eslint + prettier.

## Blender adapter (`apps/blender-tutor/adapter/`)
- Blender **5.2 LTS** extension (`blender_manifest.toml`) with the bundled pure-Python wheel `websocket-client`.
- `fake-bpy-module` for editor typing; `bpy` from PyPI (Python 3.13) for headless tests.

## Chrome extension (`apps/web-tutor/extension/`)
- Manifest V3 (Chrome 116 or later), service worker + content script, `dom-accessibility-api` for roles and accessible names, built with Vite.
- Tests: Vitest + happy-dom for snapshot and locator logic, Playwright for the extension loaded in Chromium.

## External services (pluggable, configured by environment variables)
- LLM with tool calling: `WYSP_LLM_PROVIDER`, `WYSP_LLM_MODEL`, `WYSP_LLM_API_KEY`. A deterministic `scripted` provider exists for tests and as a demo fallback.
- Speech: `WYSP_TTS_PROVIDER`, `WYSP_TTS_API_KEY`, `WYSP_STT_PROVIDER` (default `browser`).
- Secrets live in a local `.env` (git-ignored). Never commit keys, never log them.

## Common commands *(planned)*

| Goal | Command |
|---|---|
| Install Python dependencies | `uv sync` |
| Install JS dependencies | `npm install` |
| Run the Core (serves the built Panel) | `uv run wysp serve` |
| Run with the scripted LLM and the mock adapter | `uv run wysp serve --llm scripted --mock` |
| Panel dev server | `npm run dev -w panel` |
| Regenerate schemas and TS types | `uv run --no-project python scripts/kiro/hook.py schemas` |
| Python tests | `uv run pytest` |
| TypeScript tests | `npm test --workspaces --if-present` |
| Contract kit against a tutor | `uv run wysp-contract --tutor blender-tutor` |
| Validate profiles | `uv run wysp validate-profile apps/blender-tutor/profile` |
| Core boundary check (available now) | `uv run --no-project python scripts/kiro/hook.py boundaries` |

## Windows notes
- If PowerShell refuses `npm` (execution policy), use `npm.cmd`, or run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.
- Keep shell-specific operators out of hooks and scripts. Put logic in Python scripts under `scripts/`.
