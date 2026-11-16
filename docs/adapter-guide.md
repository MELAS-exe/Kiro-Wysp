# Writing a Wysp adapter

An **adapter** is the only code Wysp needs to teach a new application. It tells the Core what the application holds right now, runs a short list of actions, and points at things. Everything else (the voice, the board, the conversation, permissions, verification) is shared. A **profile** (YAML) adds the teaching content. Nothing application-specific goes in the Core.

This guide builds a complete adapter for a toy notes app. The code is `sdk/python/examples/notes_adapter.py`, and `sdk/python/tests/test_example_adapter.py` checks it against the Core's own contract models, so what you read here is what runs. The normative rules are in `.kiro/specs/adapter-contract/`; the one-page summary is `.kiro/steering/adapter-contract.md`.

## 1. What you build

```
apps/<your-tutor>/
  adapter/ or plugin/        your code (Python SDK, or any language that speaks the WebSocket protocol)
  profile/                   profile.yaml, concepts.yaml, lessons/*.yaml
  contract.fixture.yaml      what the contract kit checks offline
```

The Core is the server (`ws://127.0.0.1:8765/ws/adapter`), your adapter is the client. Messages are JSON-RPC 2.0. You can use the Python SDK (`wysp_adapter_sdk`, pure Python, safe to embed in Blender) or speak the protocol yourself, as the IntelliJ plugin does in Kotlin with `java.net.http.WebSocket`.

## 2. Connect and describe yourself (the manifest)

First message: `wysp.hello {manifest, token}`. The pairing token is in `~/.wysp/token`; never log it. Then a heartbeat at least every 20 s (the SDK does both).

```python
MANIFEST = {
    "adapter_id": "notes-demo",
    "app": {"name": "Notes", "version": "1.0"},
    "contract_version": "1.1.0",
    "integration_level": "native",
    "ref_scheme": "notes",
    "capabilities": ["observe", "context", "actions", "execute", "undo", "highlight", "events.state"],
    "entity_kinds": [{"kind": "notebook", "label": "Notebook"}, {"kind": "note", "label": "Note"}],
    "volatile_props": [],
    "locales": ["en"],
    "profile_id": "notes-demo",
}
```

- **Capabilities are promises.** The Core only calls what you declare, and only offers the tutor tools your capabilities back. `observe`, `context` and `actions` are required.
- **Integration level** is how you see the app: `native` (its own API), `interface` (DOM or accessibility tree), `visual` (screenshots; observations then carry a confidence below 1). Irreversible actions are forbidden at `visual`.
- **`volatile_props`** are properties that change on their own (timestamps, screen coordinates). State digests ignore them.
- **`contract_version`**: declare the version you implement. The Core accepts any 1.x and uses 1.1 features (persistent highlights) only with adapters that declare 1.1 or later.

## 3. Show the application: `observe` and `get_context`

`adapter.observe {scope}` returns an **entity graph**: `entities[]` (`ref`, `kind`, `label`, `parent`, `props`), `links[]`, `focus[]`, `truncated`, `counts`.

- **Refs** are stable, unique, URI-like (`notes://note/n1`) and use your scheme. The same thing must keep the same ref between observations. Every `kind` must be declared in the manifest.
- **Limits:** 500 entities and 256 KB. If you cut, set `truncated: true` and put the real totals in `counts`: the tutor is told, and will not claim a list is complete.
- **Scope:** `level` is `summary`, `focus` or `full`. A cheap adapter can ignore it. A big application should keep `summary` and `focus` fast; the Core calls `full` right after you connect (see "The survey" below) and the budget is 1 s.
- **Secrets:** mark anything sensitive with `props: {"sensitive": true}` and never send its text. The Core then names it nowhere.

`adapter.get_context` returns a short summary of where the user is now (`summary`, `mode`, `focus`, `facts`), at most 8 KB, in 500 ms. Multi-line string facts (such as code at the caret) are shown to the tutor whole, so keep them bounded and never include secrets.

The Python SDK routes methods for you: implement `observe` and `get_context` on an `AdapterRuntime` subclass.

## 4. Actions: a closed catalog

The tutor never runs anything. It can only **propose** one of your declared actions, and the Core asks the user, calls `adapter.execute`, then **verifies** the result.

An action spec has: `id` (snake_case, `<verb>_<object>`), a `title`, a `description` written for the LLM, a JSON-schema `params_schema` (`additionalProperties: false`), a `risk`, `postconditions`, and optionally `guide.ui_path` (where the user would click to do it themselves).

| Risk | What the Core does |
|---|---|
| `read_only`, `ui_state` | runs automatically, logged |
| `reversible` | needs approval (click, voice, or a lesson-scoped grant); must return an `undo_token` |
| `irreversible` | needs an explicit click with a preview; never by voice; forbidden at the `visual` level |

Rules for your action function:

1. **Validate before touching anything.** An invalid call leaves the state unchanged (the SDK's `ActionRegistry` validates params against your schema).
2. **Support `dry_run`**: return a preview and change nothing. The approval dialog shows it.
3. **Reversible means undoable.** `adapter.undo {token}` must restore the same state digest. Return an `undo` callable in the `ActionOutcome`.
4. **Postconditions are authored predicates** (JMESPath on a fresh observation, with `${params.*}` placeholders), for example `{"ref": "${params.note}", "path": "label", "op": "eq", "value": "${params.text}"}`. If they fail after execution, the Core undoes the action and reports the failure.
5. **Never add an action that runs arbitrary code** (Python `exec`, JavaScript injection, shell commands, arbitrary IDE action ids), even for debugging.

Tag the changes your own actions cause as `origin: "wysp"` (the SDK's `OriginTagger`), so the Core never counts them as the learner's achievement.

## 5. Events (adapter to Core)

Send these when the user changes things, so the board and guided steps follow along:

- `event.state_changed {state_version, changed[], origin}`, `state_version` strictly increasing, debounced to at most one per 200 ms.
- `event.selection_changed {focus[]}`.
- `event.user_action {kind, target, details, origin}` for operations you can recognise (if you declare `events.user_action`).
- `event.highlight_dismissed {ref, reason}` (1.1), see below.

`origin` is `user`, `wysp` or `unknown`.

## 6. Pointing: `highlight`

`adapter.highlight {ref, style, duration_ms}` emphasises something without changing the application. A `ref` can be an entity or an interface element your adapter documents (for example `intellij://ui/label/Commit`). Fail with `TARGET_NOT_FOUND` (and list what you can see) when you cannot find it.

Contract 1.1 makes highlights persistent: `duration_ms: 0` means "until cleared". Implement:

- **At most one highlight at a time**; a new one replaces the old one.
- `adapter.clear_highlight {}` returns `{cleared: bool}`; with nothing active it returns `{cleared: false}`, never an error.
- **When the user interacts with the highlighted thing** (clicks it, edits it, selects it), remove the highlight and send `event.highlight_dismissed {ref, reason: "user"}`. Ignore the caret moves, scrolls and selections your own highlight causes (a short grace period of about 1.5 s works).
- Remove the highlight when the connection drops.

The Core ends a persistent highlight on its own when the tutor clears it, replaces it, a guided step is verified, you disconnect, or after 10 minutes.

## 7. The survey

When your adapter becomes the active one, the Core surveys the application before the tutor answers: `get_actions`, `get_context` and one `observe` at level `full`, then keeps a bounded summary (counts per kind, structure, a few examples) in the tutor's context. Practical consequences for you:

- A `full` observation must finish within its 1 s budget even on a large project, or the Core falls back to `summary` and retries later. Time-box expensive scans (the IntelliJ adapter caps its file-tree walk at 200 ms) and report `truncated`.
- If your application is busy right after connecting (indexing, loading), send `event.state_changed` when it settles so the Core refreshes the survey.
- Names go to the tutor's language model, which may be remote. Skip secrets entirely.

## Letting the tutor explore a big project (optional)

If your application holds something big and structured (a codebase, a document tree), the Core can map it and let the tutor study it, after the user agrees. Two things make it work and neither needs a contract change:

- **Subtree observations.** `adapter.observe {level: "full", root: <ref>}` should return that subtree only: the root's ancestors, its direct children and, for leaves such as files, their details (here: symbols). Time-box the work and mark what you did not get to as pending (`props.symbols: "pending"`): the Core asks again for each pending item. If you can tell what depends on what, put the refs of what an item depends on in a property (`depends_on`).
- **The `explore` section of your profile.** It names the kinds (`root_kind`, `containers`, `files`, `details`), the dependency and pending properties, and glob patterns for what to read first or skip. Without that section the offer never appears.

The IntelliJ adapter (`Observe.kt`, `Imports.kt`) and `apps/intellij-tutor/profile/profile.yaml` are the reference.

## 8. Threading rules of the host


- **Blender:** never touch `bpy` off the main thread. The network thread only enqueues; a `bpy.app.timers` pump runs the work. Push an undo step after each Wysp change.
- **IntelliJ:** read the project model in read actions, change code only in write commands on the EDT, touch Swing only on the EDT.
- **Browser extension (`apps/web-tutor`, optional):** the WebSocket lives in the service worker with a heartbeat every 20 s; DOM work happens in the content script.

## 9. Test it without the application

1. **Unit-test the adapter against the Core's models**, as `test_example_adapter.py` does: validate your manifest, observation, context and action specs with `wysp_core.contract` (`Manifest`, `Observation`, `check_observation`, `ActionSpec`, `ActionResult`).
2. **Describe your catalog in `contract.fixture.yaml`** and run the kit offline: `uv run wysp-contract --tutor <your-tutor> --offline` (silent on success).
3. **Validate the profile:** `uv run wysp validate-profile apps/<your-tutor>/profile`.
4. **Read the Core's session log** after a real run: `uv run wysp logs summary`. Every adapter call has its duration there.
5. For a live check, run the Core with `--llm scripted --scenario <file>` so no model is involved.
6. **Run the observation checks of the kit on your adapter.** `wysp_contract.checks` (`check_observe_integrity`, `check_ref_stability`, `check_postconditions`) take one callable `request(method, params)`, so you can hand them your adapter's `handle` method directly. They verify what the contract promises about observations: refs unique and resolvable, kinds declared, 500 entities and 256 KB at most, no digest change without a change, and every postcondition true after each safe call. `uv run wysp-contract --mock` runs them on the mock adapter.
7. **Read the mock adapter as a second worked example.** `contract-tests/wysp_mock/kanban.py` (a Kanban board with six actions of every risk level, undo tokens, user-origin events) is what the Core's own tests run against; `contract-tests/tests/test_prop_contract.py` shows property tests of an adapter (undo round trip, invalid calls change nothing, monotonic `state_version`). In TypeScript, `defineAction()` and `ActionRegistry` from `@wysp/adapter-sdk/actions` declare an action once and validate its params with ajv (not for Manifest V3 pages: ajv needs `unsafe-eval`).

## 10. The profile

Application knowledge goes into data, never into the Core's prompts:

- `profile.yaml`: `id`, `app`, `languages`, `primer` (a short description for the LLM), `skills`.
- `concepts.yaml`: glossary entries (`id`, `term`, `short`, `detail`, `level`, `links`, `related`).
- `lessons/L<NN>_<slug>.yaml`: steps (`explain`, `show`, `guide`, `do`, `check`) and exercises whose success criteria are authored predicates.

The IntelliJ and Blender profiles in `apps/*/profile/` show the format for `profile.yaml` and `concepts.yaml`. Lessons and exercises are specified (`.kiro/specs/pedagogy-verification/`) but not written yet; the tutors work without them, because guided actions are verified through their postconditions.

## Checklist

- [ ] Manifest declares only what you implement, with the right `contract_version`
- [ ] Refs are stable and unique; every kind is declared
- [ ] Observations respect 500 entities / 256 KB and set `truncated` and `counts`
- [ ] Sensitive things are flagged and their text never leaves the application
- [ ] Every action validates first, supports `dry_run`, has postconditions, and reversible ones undo exactly
- [ ] No action evaluates code
- [ ] Wysp's own changes are tagged `origin: wysp`
- [ ] Persistent highlights clear on request, on interaction (with `event.highlight_dismissed`) and on disconnect
- [ ] The contract kit and the profile validator pass offline
