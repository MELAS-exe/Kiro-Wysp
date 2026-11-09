---
inclusion: fileMatch
fileMatchPattern: ["apps/**", "sdk/**", "contract-tests/**", "core/src/wysp_core/contract/**", "core/src/wysp_core/gateway/**"]
---

# Adapter Contract: Implementer Guide

The normative definition is the spec `.kiro/specs/adapter-contract/` and the generated JSON Schemas in `schemas/`. This page is the short version for anyone writing or changing an adapter.

## Transport
- JSON-RPC 2.0 over WebSocket. The adapter is the client and the Core is the server: `ws://127.0.0.1:8765/ws/adapter`.
- First message: a `wysp.hello` request with `{manifest, token}`. Then a `wysp.heartbeat` notification at least every 20 s.

## Methods (Core to adapter)

| Method | Capability | Required | Budget |
|---|---|---|---|
| `adapter.observe {scope}` returns an Observation | `observe` | yes | 1 s |
| `adapter.get_context {}` returns a Context (8 KB max) | `context` | yes | 500 ms |
| `adapter.get_actions {}` returns ActionSpec[] | `actions` | yes | 500 ms |
| `adapter.execute {call}` returns an ActionResult | `execute` | no | 5 s |
| `adapter.undo {token}` returns an ActionResult | `undo` | if any action is reversible | 5 s |
| `adapter.highlight {ref, style, duration_ms}` | `highlight` | no | 500 ms |
| `adapter.verify {goal}` returns Evidence[] | `verify.native` | no | 2 s |

## Notifications (adapter to Core)
`event.state_changed {state_version, changed[], origin}`, `event.selection_changed {focus[]}`, `event.user_action {kind, target, details, origin}`, `event.navigation {url, title}`. `origin` is `user`, `wysp` or `unknown`. Debounce state events (200 ms minimum).

## Observation model
- An Observation holds an Entity Graph: `entities[]` (`ref`, `kind`, `label`, `parent`, `props`, `confidence`), `links[]` (`from`, `to`, `kind`), `focus[]`, `truncated`, `counts`.
- Refs are stable, unique and URI-like, with the adapter's scheme. Every `kind` used must be declared in the manifest's `entity_kinds`.
- Respect the size limits (500 entities, 256 KB). Otherwise set `truncated: true` and fill `counts`.
- Declare volatile props (timestamps, screen coordinates) in the manifest so that state digests ignore them.

## Actions
- One file per action (naming in `structure.md`). Each action declares `id`, `title`, `description` (written for the LLM), `params_schema` (JSON Schema), `risk`, `postconditions` (predicates with `${params.*}` placeholders) and, when useful, `guide.ui_path` (where the user would click to do it themselves).
- Reversible actions return an `undo_token`. `undo` must restore the same state digest.
- Validate parameters before touching the application. Invalid calls must leave the state unchanged.
- Forbidden: any action that evaluates code or scripts.

## Errors
`-32010 NOT_SUPPORTED`, `-32011 ACTION_NOT_FOUND`, `-32012 TARGET_NOT_FOUND`, `-32013 PRECONDITION_FAILED`, `-32014 EXECUTION_FAILED`, `-32015 UNDO_UNAVAILABLE`, `-32016 TIMEOUT`, `-32017 BUSY`, `-32018 INCOMPATIBLE_VERSION`, `-32019 UNAUTHORIZED`, plus the standard JSON-RPC codes. Put details in `error.data`, never stack traces.

## Host rules
- **Blender:** never touch `bpy` outside the main thread. The network thread only enqueues; a `bpy.app.timers` pump (every 50 ms) executes. Prefer the data API (`obj.modifiers.new`) over `bpy.ops`. Push an undo step (`bpy.ops.ed.undo_push`) after each Wysp change so that Ctrl+Z works too. Tag events caused by Wysp with `origin: wysp`.
- **Chrome MV3:** the WebSocket lives in the service worker and sends a heartbeat every 20 s (this keeps the worker alive since Chrome 116). DOM work happens in the content script. Resolve locators at execution time. Set values on React-controlled inputs through the native value setter, then dispatch `input` and `change` events.

## Definition of done for an adapter change
- The contract kit passes for the tutor, and `contract.fixture.yaml` is updated if the catalog changed.
- New actions appear in the tutor README action table with their risk and reversibility.
