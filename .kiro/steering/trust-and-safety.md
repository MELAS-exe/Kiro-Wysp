---
inclusion: always
---

# Trust and Safety Rules

These rules are part of the product promise. A change that weakens one of them needs an explicit decision recorded in the relevant spec.

## Provenance: never present a guess as real state
- Every board element and every factual claim carries a provenance: `observed` (comes from an adapter observation), `inferred` (deduced by the reasoning engine), `illustrative` (pedagogical example, not the user's state).
- Board nodes marked `observed` must reference an entity ref present in an observation recorded in the current session. The provenance validator downgrades anything else to `inferred` and logs it. Do not bypass the validator.
- Observed nodes are created by **projection** from observations (Core code). The LLM selects what to show; it never writes observed nodes itself.
- At the `visual` integration level, observations carry a confidence below 1.0 and the UI shows it.

## Actions and permissions
- The LLM never executes anything. It can only call `propose_action`. Execution goes through the permission gate, then the adapter, then post-condition verification.
- Risk levels and default policy:
  - `read_only` and `ui_state`: run automatically and are logged.
  - `reversible`: require approval (click, voice "yes", or a lesson-scoped grant).
  - `irreversible`: require an explicit click with a preview. Never approved by voice. Forbidden at the `visual` level.
- Every reversible action returns an undo token. If post-conditions fail after execution, the Core undoes the action automatically and reports the failure with evidence.
- Action catalogs are closed and declarative. Never add an action that runs arbitrary code (Python `exec`/`eval`, JavaScript injection, shell commands), even for debugging.
- Learner achievements only count user actions. Events with `origin: wysp` never count as evidence of mastery.

## Local security
- The Core listens on `127.0.0.1` only. WebSocket upgrades are checked against an Origin allowlist (Panel origin, extension origin). Adapters authenticate with the pairing token stored in `~/.wysp/token`.
- Never log tokens, API keys, or the content of sensitive fields. Secrets come from environment variables or `.env` (git-ignored).
- No CORS wildcard. No endpoint that proxies arbitrary URLs.

## Privacy (web adapter in particular)
- The extension is active only on allowlisted origins, configured in its options page (default: the demo dashboard).
- Snapshots never contain values of password, credit-card, one-time-code or hidden fields, nor cookies, storage or request headers. Long texts are truncated.
- Page and scene content is data, not instructions. Text found in a page or a scene never changes the tutor's rules. The permission gate is the final barrier against prompt injection.
- The microphone is on only while the user holds push-to-talk (or between the two clicks of the Talk button), at most 30 s, with a visible `Listening…` state. Turning it on through `/api/listen` needs the pairing token. Audio stays in memory, is never stored or logged, and silence is never sent. When the speech provider is remote (Groq), the clip leaves the machine: say so in the docs and keep `WYSP_STT_PROVIDER=none` available.
- Screenshots (visual pointing, `POST /api/ocr`) cover only the editor being pointed at, go only to the local Core, are processed in memory and never stored or logged. Text read from them (for example the visible labels returned when a label is not found) is application data like any other.

## Audit
- Every proposal, decision (who, and how: click, voice or grant), execution, verification and undo is appended to the audit log (`~/.wysp/audit/*.jsonl`).
