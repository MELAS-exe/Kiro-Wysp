# Design Document: Adapter Contract

## Overview

The contract is a small JSON-RPC 2.0 protocol over a local WebSocket. Adapters are **clients**: Blender's embedded Python and a Chrome service worker can both open an outgoing WebSocket, while neither can easily host a server. The Core is the **server** on `127.0.0.1:8765`. Requests flow in both directions on the same socket: the adapter sends `wysp.*` requests and `event.*` notifications, and the Core sends `adapter.*` requests.

The contract is application-independent because it never names application concepts. It exchanges generic **entities** (with kinds declared by the adapter), **actions** (declared by the adapter with JSON Schemas) and **predicates** (evaluated by the Core). Application knowledge stays in the adapter's manifest and catalog, and in the profile.

```
 Adapter (client)                                     Wysp Core (server)
 ───────────────────                                  ───────────────────
 wysp.hello {manifest, token}  ───────────────────▶   validate token, version, manifest
                               ◀───────────────────   {session_id, contract_version, heartbeat_interval_s}
 wysp.heartbeat (notification, every ≤ 20 s) ─────▶
                               ◀───────────────────   adapter.observe {scope}
 Observation                   ───────────────────▶
                               ◀───────────────────   adapter.execute {call}
 ActionResult {undo_token}     ───────────────────▶
 event.state_changed {origin: "wysp"} ────────────▶   verify postconditions (observe again)
```

## Architecture

| Piece | Location | Owner |
|---|---|---|
| Pydantic models (source of truth) | `core/src/wysp_core/contract/` (`rpc.py`, `manifest.py`, `observation.py`, `actions.py`, `events.py`, `predicates.py`, `errors.py`, `ui.py`) | A |
| Schema export | `core/src/wysp_core/contract/export.py` writes `schemas/*.schema.json` and `schemas/index.json` | A |
| Predicate evaluator | `core/src/wysp_core/contract/predicates.py` (pure, shared by Core and Kit) | A |
| State digest | `core/src/wysp_core/contract/digest.py` (pure, shared) | A |
| TypeScript types | `sdk/ts/src/generated/` generated with `json-schema-to-typescript` (`npm run gen:types -w sdk/ts`) | A |
| Python SDK | `sdk/python/wysp_adapter_sdk/`: `AdapterClient`, `ActionRegistry`, dispatchers, digest, validation | C |
| TypeScript SDK | `sdk/ts/src/`: `AdapterClient` (service-worker friendly), `defineAction`, validation helpers | C |
| Contract Test Kit | `contract-tests/wysp_contract/`: harness server, checks, CLI `wysp-contract` | A |
| Mock adapter | `contract-tests/wysp_mock/`: Kanban app, CLI `wysp-mock-adapter` | A |

The SDKs and the Kit import `wysp_core.contract` only (models, predicates, digest). They never import other Core modules.

## Components and Interfaces

### Methods

| Direction | Method | Params | Result | Capability | Budget |
|---|---|---|---|---|---|
| A → C | `wysp.hello` | `{manifest, token}` | `HelloResult` | — | 2 s |
| A → C | `wysp.heartbeat` (notification) | `{state_version}` | — | — | — |
| A → C | `wysp.bye` (notification) | `{reason}` | — | — | — |
| C → A | `adapter.observe` | `{scope}` | `Observation` | `observe` | 1 s |
| C → A | `adapter.get_context` | `{}` | `Context` | `context` | 500 ms |
| C → A | `adapter.get_actions` | `{}` | `ActionSpec[]` | `actions` | 500 ms |
| C → A | `adapter.execute` | `{call: ActionCall}` | `ActionResult` | `execute` | 5 s |
| C → A | `adapter.undo` | `{token}` | `ActionResult` | `undo` | 5 s |
| C → A | `adapter.highlight` | `{ref, style, duration_ms}` | `{ok: true}` | `highlight` | 500 ms |
| C → A | `adapter.verify` | `{goal: Predicate}` | `Evidence[]` | `verify.native` | 2 s |
| A → C | `event.state_changed` | `{state_version, changed[], origin}` | — | `events.state` | — |
| A → C | `event.selection_changed` | `{focus[]}` | — | `events.selection` | — |
| A → C | `event.user_action` | `{kind, target?, details, origin}` | — | `events.user_action` | — |
| A → C | `event.navigation` | `{url, title}` | — | `events.navigation` | — |

(A = adapter, C = Core.) The Core never calls a method whose capability is missing from the manifest.

### Example exchange (Blender)

```json
{"jsonrpc":"2.0","id":1,"method":"wysp.hello","params":{"token":"…","manifest":{
  "adapter_id":"blender-tutor","app":{"name":"Blender","version":"5.2.0"},
  "contract_version":"1.0.0","integration_level":"native","ref_scheme":"blender",
  "capabilities":["observe","context","actions","execute","undo","highlight","events.state","events.selection"],
  "entity_kinds":[{"kind":"object","label":"Object"},{"kind":"modifier","label":"Modifier"},
                  {"kind":"material","label":"Material"},{"kind":"collection","label":"Collection"}],
  "volatile_props":["matrix_world_cached","last_render_time"],"locales":["en","fr"],"profile_id":"blender-tutor"}}}

{"jsonrpc":"2.0","id":7,"method":"adapter.execute","params":{"call":{
  "action_id":"add_modifier","params":{"target":"blender://object/Candle","type":"BEVEL"},
  "request_id":"c3f1…","dry_run":false}}}

{"jsonrpc":"2.0","id":7,"result":{"status":"ok","state_version":42,
  "changed":["blender://object/Candle","blender://object/Candle/modifier/Bevel"],
  "undo_token":"u-42-7","message":"Added Bevel modifier to Candle"}}
```

## Data Models

Pydantic v2, `model_config = ConfigDict(extra="forbid")` for requests, `extra="allow"` only where noted. Abbreviated:

```python
Ref = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9+.-]*://.+$", max_length=512)]
Risk = Literal["read_only", "ui_state", "reversible", "irreversible"]
Origin = Literal["user", "wysp", "unknown"]

class EntityKind(BaseModel):  kind: str; label: str; description: str | None = None
class Manifest(BaseModel):
    adapter_id: str; app: AppInfo; contract_version: str; integration_level: Literal["native","interface","visual"]
    ref_scheme: str; capabilities: set[Capability]; entity_kinds: list[EntityKind]
    volatile_props: list[str] = []; locales: list[str] = ["en"]; profile_id: str | None = None

class Scope(BaseModel):  level: Literal["summary","focus","full"] = "focus"; root: Ref | None = None; depth: int | None = Field(None, ge=0, le=8)
class Entity(BaseModel):
    ref: Ref; kind: str; label: str; parent: Ref | None = None
    props: dict[str, JsonValue] = {}; confidence: float = Field(1.0, ge=0, le=1)
class Link(BaseModel):  from_: Ref = Field(alias="from"); to: Ref; kind: str
class Observation(BaseModel):
    observation_id: str; state_version: int; captured_at: datetime; scope: Scope
    entities: list[Entity]; links: list[Link] = []; focus: list[Ref] = []
    truncated: bool = False; counts: dict[str, int] = {}

class Context(BaseModel):  summary: str; mode: str | None; focus: list[Ref] = []; facts: dict[str, JsonValue] = {}
class GuideStep(BaseModel):  text: LocalizedText; target: Ref | None = None
class ActionSpec(BaseModel):
    id: str; title: LocalizedText; description: str; params_schema: dict[str, JsonValue]
    risk: Risk; reversible: bool; preconditions: list[Predicate] = []; postconditions: list[Predicate] = []
    guide: Guide | None = None          # guide.ui_path: list[GuideStep]
class ActionCall(BaseModel):  action_id: str; params: dict[str, JsonValue]; request_id: str; dry_run: bool = False
class ActionResult(BaseModel):
    status: Literal["ok","failed"]; state_version: int; changed: list[Ref] = []
    undo_token: str | None = None; message: str | None = None; preview: JsonValue | None = None
```

`LocalizedText` is `str | dict[locale, str]`. `JsonValue` is any JSON value.

### Predicate language

Postconditions, exercise success criteria and verification goals use one language, evaluated by `wysp_core.contract.predicates.evaluate(predicate, observation) -> PredicateOutcome(ok, actual, expected, path)`:

```
Predicate  := Compare | {"all": [Predicate…]} | {"any": [Predicate…]} | {"not": Predicate}
Compare    := {"ref"?: Ref, "path": JMESPath, "op": Op, "value"?: JSON}
Op         := eq | ne | gt | gte | lt | lte | in | contains | exists | not_exists | matches | len_eq | len_gte
```

- Without `ref`, `path` is evaluated on the Observation JSON (`entities[?kind=='modifier' && parent=='blender://object/Candle']`). With `ref`, it is evaluated on that entity (`props.segments`). A missing entity makes `exists` false and every other comparison false.
- `matches` uses a full-match regular expression with a 100 ms timeout.
- Placeholders `${params.<name>}`, `${bindings.<name>}` are allowed in `ref` and `value` (replaced by the raw value) and inside `path` **only within single-quoted JMESPath raw literals** (`'${params.target}'`), where the value is escaped (`'` becomes `\'`). Any other placeholder position is rejected at load time. This prevents parameter values from injecting JMESPath syntax.

Example (postcondition of `add_modifier`):

```json
{"path":"entities[?kind=='modifier' && parent=='${params.target}' && props.type=='${params.type}'] | length(@)","op":"gte","value":1}
```

### Guide templating

`GuideStep.text` may contain `${params.<name>}` (parameter value) and `${label:params.<name>}` (label of the entity referenced by a ref parameter, from the latest observation). The Core renders them before publishing guide steps. Unknown placeholders are left visible and logged. Rendered texts are plain text, never HTML.

### State digest

`digest(observation, volatile_props) = sha256(canonical_json([...]))` over the entities sorted by ref, each reduced to `ref`, `kind`, `parent` and `props` without volatile props, plus the links sorted by `(from, to, kind)`. It ignores `observation_id`, `captured_at`, `state_version`, `focus`, labels of `illustrative` data and entity order. Canonical JSON: sorted keys, no whitespace, floats rounded to 6 significant digits (avoids false differences from float noise in Blender).

### Errors

| Code | Name | Typical use |
|---|---|---|
| -32700 / -32600 / -32601 / -32602 / -32603 | JSON-RPC standard | parse error, invalid request, unknown method, invalid params, internal |
| -32010 | NOT_SUPPORTED | capability not declared or not available (e.g. highlight in headless Blender) |
| -32011 | ACTION_NOT_FOUND | unknown `action_id` |
| -32012 | TARGET_NOT_FOUND | ref does not resolve, ambiguous locator |
| -32013 | PRECONDITION_FAILED | precondition predicate false |
| -32014 | EXECUTION_FAILED | host raised an error; state rolled back by the adapter |
| -32015 | UNDO_UNAVAILABLE | unknown or expired undo token |
| -32016 | TIMEOUT | budget exceeded (raised by the caller side) |
| -32017 | BUSY | the application is in a modal state (e.g. Blender edit operator running) |
| -32018 | INCOMPATIBLE_VERSION | major contract version mismatch |
| -32019 | UNAUTHORIZED | bad pairing token |

### Versioning

- `contract_version` starts at `1.0.0` at gate J0. Additive, optional changes bump the minor version. Breaking changes bump the major version and need the agreement of A, B and C.
- `schemas/index.json` lists every schema with its `$id` (`https://wysp.dev/schemas/1/<name>.schema.json`) and the contract version.
- CI runs the export and fails on `git diff --exit-code schemas sdk/ts/src/generated`.

### Pairing and Origin checks

- On first start the Core writes a random 32-byte token (URL-safe base64) to `~/.wysp/token` with user-only permissions. Adapters read it from that file (Blender) or receive it once through the extension options page (paste or pairing link `http://127.0.0.1:8765/pair` shown by the Core).
- Allowed `Origin` values: absent (native clients), `http://127.0.0.1:<port>` (Panel), `chrome-extension://<id>` for ids listed in `~/.wysp/config.toml`.

## Contract Test Kit

```
wysp-contract --tutor <name> [--offline] [--only <check>] [--junit out.xml]
```

1. Reads `apps/<tutor>/contract.fixture.yaml`:

```yaml
tutor: blender-tutor
launch:
  kind: command            # command | playwright | in_process
  command: ["{blender}", "-b", "apps/blender-tutor/demo/pumpkin.blend", "--python",
            "apps/blender-tutor/demo/run_adapter.py", "--", "--port", "{port}", "--token", "{token}"]
  env: {WYSP_HEADLESS: "1"}
  connect_timeout_s: 60
expect:
  entity_kinds: [object, modifier, material, collection]
  min_entities: 5
safe_calls:
  - {action_id: add_modifier, params: {target: "blender://object/Candle", type: BEVEL}}
  - {action_id: set_modifier_property, params: {target: "blender://object/Pumpkin/modifier/Subdivision", property: levels, value: 1}}
invalid_calls:
  - {action_id: add_modifier, params: {target: "blender://object/DoesNotExist", type: BEVEL}, expect_error: -32012}
  - {action_id: add_modifier, params: {target: "blender://object/Candle", type: 12}, expect_error: -32602}
skip:
  - {check: highlight, reason: "no UI in background mode"}
```

2. Starts the harness server on a free port with a fresh token, launches the adapter and waits for `wysp.hello`.
3. Runs the checks (each is a pytest test): `handshake`, `manifest`, `observe_invariants`, `ref_stability`, `context_size`, `catalog`, `safe_calls` (execute, postconditions, undo, digest), `invalid_calls`, `events_origin`, `state_version_monotonic`, `budgets`, `highlight`, `heartbeat`.
4. Records every exchange to `apps/<tutor>/contract-recordings/<date>.jsonl` (tokens redacted). `--offline` re-validates the latest recording and the fixture against the current schemas, which tells the team which tutor a contract change would break, without launching Blender or Chrome.

## Mock adapter (Kanban)

- Entities: `board`, `column`, `card`, `label` (refs `mock://board/b1/column/todo/card/c3`).
- Actions: `create_card` (reversible), `move_card` (reversible), `rename_card` (reversible), `add_label` (reversible), `set_filter` (ui_state), `select_card` (ui_state), `archive_card` (irreversible, used to test the permission gate).
- Library API for in-process tests: `MockKanban.simulate_user(action_id, params)` applies a change with `origin: user` and emits events; options `latency_ms`, `fail_rate`, `disconnect_after_s`, `seed`.
- CLI: `wysp-mock-adapter --port 8765 --token-file ~/.wysp/token [--latency-ms 50] [--fail-rate 0.1]`.

## Correctness Properties

*A property is a statement that must hold for every valid input. Each one is implemented as a property-based test that cites its id.*

**CON-P1: Schema round trip.** *For any* contract model instance, serializing it, validating it against the exported JSON Schema and parsing it back yields an equal instance. **Validates: Requirements 10.1, 10.2**

**CON-P2: Observation referential integrity.** *For any* observation returned by an adapter, every `parent`, link endpoint and `focus` ref belongs to an entity of the same observation, refs are unique and every kind is declared in the manifest. **Validates: Requirements 2.5, 3.3, 3.4**

**CON-P3: Ref and digest stability.** *For any* application state, two observations taken without an intervening change have the same set of refs and the same digest. **Validates: Requirement 3.6**

**CON-P4: Digest invariance.** *For any* observation, permuting entities or links, or changing only volatile props, leaves the digest unchanged; changing a non-volatile prop changes it. **Validates: Requirement 6.5 (definition of state equality)**

**CON-P5: Invalid calls do not change state.** *For any* call whose params violate the schema or whose target does not exist, the adapter returns an error in {-32602, -32012, -32013} and the digest is unchanged. **Validates: Requirements 6.2, 6.3**

**CON-P6: Undo round trip.** *For any* sequence of successful reversible actions undone in reverse order, the final digest equals the initial digest. **Validates: Requirements 6.4, 6.5**

**CON-P7: Postconditions hold.** *For any* successful `execute`, every postcondition of the action, after placeholder substitution, is true on a fresh observation. **Validates: Requirements 5.3, 6.1**

**CON-P8: Monotonic state version.** *For any* sequence of results and events from one adapter session, `state_version` never decreases, and it strictly increases on each state event. **Validates: Requirement 7.1**

**CON-P9: Origin tagging.** *For any* state change caused by `execute` or `undo`, the resulting events carry `origin: wysp`; changes made through `simulate_user` carry `origin: user`. **Validates: Requirement 6.7**

**CON-P10: Size limits.** *For any* application state, an observation has at most 500 entities and 256 KB; when truncated, `counts[kind]` is at least the number of returned entities of that kind. **Validates: Requirement 3.5**

**CON-P11: Safe placeholder substitution.** *For any* parameter string (including quotes, brackets and JMESPath operators), substitution into an allowed placeholder position yields a path that parses, and the literal compared equals the parameter string. **Validates: Requirement 5.3**

## Error Handling

- Malformed JSON, unknown methods and invalid params return standard JSON-RPC errors and never close the socket. Three consecutive protocol errors from the same adapter close it with a logged reason.
- Requests that time out are cancelled on the caller side; late responses are logged and dropped.
- Adapters must catch host exceptions per request and convert them to `-32014 EXECUTION_FAILED`, after rolling back partial changes.

## Testing Strategy

- **Unit and property tests (Python):** models, export, predicates, digest (CON-P1, CON-P4, CON-P11) with Hypothesis; the mock adapter driven by a Hypothesis `RuleBasedStateMachine` (CON-P5, CON-P6, CON-P8, CON-P9).
- **Golden fixtures:** `contract-tests/fixtures/protocol/*.json` are valid and invalid messages that both the Python and the TypeScript test suites must accept or reject identically.
- **Kit self-test:** the Kit runs against the mock adapter in CI, with fault injection enabled in a second job.
