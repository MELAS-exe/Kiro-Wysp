# Requirements Document: Adapter Contract

Lead: Person A. Reviewers: Person C (adapters), Person B (UI protocol types).

## Introduction

The adapter contract is the stable boundary between Wysp Core and application adapters. It defines the transport, the session handshake, the adapter manifest, the methods the Core calls, the events adapters emit, the observation and action models, the error codes and the versioning rules. The contract is defined once as Pydantic models, exported as JSON Schemas and TypeScript types, and checked by a Contract Test Kit that runs against every adapter. The same contract must serve a native integration (Blender), an interface integration (web browser) and, later, a visual integration.

## Glossary

- **Core**: Wysp Core, the WebSocket JSON-RPC server.
- **Adapter**: the client process or extension that implements the contract for one application.
- **Manifest**: the adapter's self-description sent at handshake.
- **Entity**: one element of the application state (object, control, layer...), identified by a ref.
- **Ref**: a stable, URI-like identifier `<scheme>://<path>`.
- **Observation**: a snapshot of the application state as an entity graph.
- **State digest**: a hash of an observation that ignores volatile props.
- **Action**: an operation declared in the adapter's catalog, described by an ActionSpec.
- **Postcondition**: a predicate that must be true after an action succeeds.
- **Contract Test Kit (Kit)**: pytest suite that plays the Core and checks an adapter.
- **Mock adapter**: a reference adapter for a fictional Kanban application, used by Core tests.

## Requirements

### Requirement 1: Transport and session

**User Story:** As an adapter developer, I want one simple transport that works from Blender's embedded Python and from a Chrome extension, so that I can connect any application to the Core.

#### Acceptance Criteria

1. THE Core SHALL accept adapter connections over WebSocket at `ws://127.0.0.1:<port>/ws/adapter` and exchange JSON-RPC 2.0 messages encoded as UTF-8 JSON text frames.
2. WHEN an adapter connects, THE adapter SHALL send `wysp.hello {manifest, token}` as its first message, and THE Core SHALL reply with `{session_id, contract_version, core_version, heartbeat_interval_s}`.
3. IF the token does not match the pairing token, THEN THE Core SHALL reply with error `-32019 UNAUTHORIZED` and close the connection.
4. IF the manifest's major `contract_version` differs from the Core's, THEN THE Core SHALL reply with error `-32018 INCOMPATIBLE_VERSION` that states both versions, and close the connection.
5. WHILE a session is open, THE adapter SHALL send `wysp.heartbeat` at least every 20 seconds, and THE Core SHALL mark the adapter as disconnected after 45 seconds without any message.
6. WHEN an adapter reconnects with the same `adapter_id`, THE Core SHALL replace the previous connection and keep the tutoring session.
7. THE Core SHALL reject WebSocket upgrades whose `Origin` header is present and not in the configured allowlist.

### Requirement 2: Manifest and capabilities

**User Story:** As the Core, I want each adapter to declare what it can do, so that I only offer the tools and behaviours it supports.

#### Acceptance Criteria

1. THE manifest SHALL contain `adapter_id`, `app` (`name`, `version`), `contract_version`, `integration_level` (`native`, `interface` or `visual`), `capabilities`, `entity_kinds`, `ref_scheme`, `volatile_props`, `locales` and `profile_id`.
2. THE capability set SHALL use the identifiers `observe`, `context`, `actions`, `execute`, `undo`, `highlight`, `events.state`, `events.selection`, `events.user_action`, `events.navigation` and `verify.native`.
3. WHEN the Core needs a capability the adapter did not declare, THE Core SHALL not call the corresponding method, and THE orchestrator SHALL not offer the corresponding LLM tool.
4. IF an adapter receives a request for a method it does not support, THEN it SHALL return error `-32010 NOT_SUPPORTED`.
5. THE manifest SHALL declare every entity `kind` that the adapter's observations use, each with a label and an optional description for the LLM.

### Requirement 3: Observation

**User Story:** As the Core, I want a structured, application-independent view of the application state, so that one reasoning engine and one board work for every application.

#### Acceptance Criteria

1. WHEN the Core calls `adapter.observe {scope}`, THE adapter SHALL return an Observation with `observation_id`, `state_version`, `captured_at`, `scope`, `entities`, `links`, `focus`, `truncated` and `counts`.
2. THE scope SHALL support `summary`, `focus` and `full` levels, and optionally a `root` ref and a `depth`.
3. Each entity SHALL have a `ref` unique within the observation, a `kind` declared in the manifest, a `label`, an optional `parent` ref, `props` (JSON values) and a `confidence` in [0, 1].
4. Every `parent`, link endpoint and `focus` ref SHALL reference an entity present in the same observation.
5. IF an observation would exceed 500 entities or 256 KB, THEN THE adapter SHALL truncate it, set `truncated` to true and report the full counts per kind in `counts`.
6. WHEN the application state has not changed, THE adapter SHALL return the same refs for the same elements across observations.
7. WHERE the integration level is `visual`, THE adapter SHALL set entity `confidence` below 1.0.

### Requirement 4: Context

**User Story:** As the reasoning engine, I want a compact text-and-JSON summary of the situation, so that I can ground my answers without sending the whole state to the LLM.

#### Acceptance Criteria

1. WHEN the Core calls `adapter.get_context {}`, THE adapter SHALL return a Context with `summary` (short natural-language text), `mode` (application mode or page), `focus` refs and `facts` (key-value pairs) of at most 8 KB in total.
2. THE context SHALL only contain information that is also observable through `adapter.observe`.

### Requirement 5: Action catalog

**User Story:** As the Core, I want a closed, declarative catalog of actions with schemas and risk levels, so that I can propose safe, valid actions and check their effect.

#### Acceptance Criteria

1. WHEN the Core calls `adapter.get_actions {}`, THE adapter SHALL return a list of ActionSpec with `id`, `title`, `description`, `params_schema` (JSON Schema draft 2020-12), `risk`, `reversible`, `postconditions`, optional `preconditions` and optional `guide`.
2. THE `risk` field SHALL be one of `read_only`, `ui_state`, `reversible`, `irreversible`, and `reversible` SHALL be true for every action whose risk is `reversible`.
3. Each postcondition SHALL be a predicate in the Wysp predicate language, where `${params.<name>}` placeholders are replaced by call parameters before evaluation.
4. THE catalog SHALL NOT contain any action that evaluates arbitrary code or scripts.
5. WHERE an action can be performed by the user in the application's own interface, THE ActionSpec SHOULD provide `guide.ui_path`, an ordered list of UI steps with optional target refs.

### Requirement 6: Execution and undo

**User Story:** As a user, I want every change made by Wysp to be checked and reversible when possible, so that I can let the tutor act without fear.

#### Acceptance Criteria

1. WHEN the Core calls `adapter.execute {call}` with a valid call, THE adapter SHALL perform the action and return an ActionResult with `status`, `changed` refs, `state_version`, optional `undo_token` and `message`.
2. IF the parameters do not validate against `params_schema`, THEN THE adapter SHALL return error `-32602 INVALID_PARAMS` without changing the application state.
3. IF the target entity does not exist, THEN THE adapter SHALL return error `-32012 TARGET_NOT_FOUND` without changing the application state.
4. WHEN a reversible action succeeds, THE adapter SHALL return an `undo_token`.
5. WHEN the Core calls `adapter.undo {token}` with a valid token, THE adapter SHALL restore a state whose digest equals the digest before the action.
6. IF an undo token is unknown or expired, THEN THE adapter SHALL return error `-32015 UNDO_UNAVAILABLE`.
7. THE adapter SHALL tag every state event caused by an `execute` or `undo` call with `origin: wysp`.

### Requirement 7: Events

**User Story:** As the Core, I want to know when the user changes the application, so that I can follow along, update the board and verify exercises.

#### Acceptance Criteria

1. WHEN the application state changes, THE adapter SHALL send `event.state_changed {state_version, changed, origin}` with `state_version` strictly greater than the previous one.
2. WHEN the selection or focus changes, THE adapter SHALL send `event.selection_changed {focus}`.
3. WHERE the adapter declares `events.user_action`, THE adapter SHALL send `event.user_action {kind, target, details, origin}` for user operations it can recognise.
4. THE adapter SHALL debounce state events so that it sends at most one `event.state_changed` per 200 ms.

### Requirement 8: Highlight

**User Story:** As a learner, I want the tutor to show me where things are in the application, so that I connect the explanation to the real interface.

#### Acceptance Criteria

1. WHEN the Core calls `adapter.highlight {ref, style, duration_ms}`, THE adapter SHALL visually emphasise the entity in the application for the requested duration without changing the application state.
2. IF the entity cannot be highlighted, THEN THE adapter SHALL return error `-32012 TARGET_NOT_FOUND` or `-32010 NOT_SUPPORTED`.

### Requirement 9: Errors and timeouts

**User Story:** As a developer, I want predictable errors, so that the Core can recover and explain failures to the user.

#### Acceptance Criteria

1. THE contract SHALL use the JSON-RPC standard codes and the Wysp codes `-32010` to `-32019` with fixed meanings.
2. Error responses SHALL contain a human-readable `message` and structured `data`, and SHALL NOT contain stack traces.
3. IF an adapter does not answer within the method budget (observe 1 s, context and actions 500 ms, execute and undo 5 s, verify 2 s), THEN THE Core SHALL treat the call as failed with `-32016 TIMEOUT`.

### Requirement 10: Single source of truth and versioning

**User Story:** As a team of three, we want the contract to be defined in one place, so that the Core, the Python SDK and the TypeScript SDK never drift apart.

#### Acceptance Criteria

1. THE contract SHALL be defined as Pydantic v2 models in `core/src/wysp_core/contract/`.
2. WHEN a contract model changes, THE export tool SHALL regenerate the JSON Schemas in `schemas/` and the TypeScript types in `sdk/ts/src/generated/`, and CI SHALL fail if the committed files differ from the generated ones.
3. THE contract SHALL carry a semantic `contract_version`, where a minor bump only adds optional fields or methods and a major bump marks a breaking change.

### Requirement 11: Contract Test Kit

**User Story:** As an adapter developer, I want to run one test suite against my adapter, so that I know it works with the Core before integrating.

#### Acceptance Criteria

1. THE Kit SHALL run as `wysp-contract --tutor <name>`, play the Core role on a local port and wait for the adapter to connect.
2. THE Kit SHALL read `apps/<tutor>/contract.fixture.yaml`, which lists how to launch the adapter, safe calls, invalid calls and expected entity kinds.
3. THE Kit SHALL check the requirements of this document that can be observed from outside: handshake, manifest validity, observation invariants, action catalog validity, execution, postconditions, undo, error codes, event ordering and origin tagging, and time budgets.
4. WHEN run with `--offline`, THE Kit SHALL validate the fixture and re-validate the recorded exchanges in `apps/<tutor>/contract-recordings/` against the current schemas, without launching the application.
5. THE Kit SHALL produce a JUnit XML report and a readable summary listing each check and its result.

### Requirement 12: Mock adapter

**User Story:** As a Core developer, I want a reference adapter that runs without any real application, so that I can develop and test the Core from day one.

#### Acceptance Criteria

1. THE mock adapter SHALL implement every capability of the contract for a fictional Kanban application (boards, columns, cards, labels).
2. THE mock adapter SHALL pass the Kit.
3. THE mock adapter SHALL support fault injection (latency, errors, disconnections) through command-line options.
