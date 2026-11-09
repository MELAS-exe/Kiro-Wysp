# Design Document: Web Tutor

## Overview

```
apps/web-tutor/
  extension/                       Chrome MV3 extension (MIT), built with Vite
    public/manifest.json           MV3, permissions: storage, tabs, scripting, webNavigation; optional_host_permissions
    src/sw/                        service worker: AdapterClient (TS SDK), tab tracking, request routing to content scripts
    src/cs/                        content script: snapshot.ts, a11y.ts, locators.ts, events.ts, overlay.ts, redact.ts
    src/actions/                   one file per action (id = file name), run in the content script
    src/options/                   options page: Core URL, token, allowlist
    tests/                         Vitest + happy-dom (snapshot, locators, redaction), Playwright (extension + dashboard)
  demo-dashboard/                  "Haunted Shop Analytics", React + Vite, seeded data       (owner: B)
  profile/                         profile.yaml, concepts.yaml, lessons/L01..L03             (owner: B)
  contract.fixture.yaml
```

## Message flow

```
Core ◀──WebSocket (JSON-RPC)──▶ service worker ◀──chrome.tabs.sendMessage / runtime.Port──▶ content script ──▶ DOM
```

- The SW owns the socket (heartbeat every 20 s keeps it alive since Chrome 116), tracks the active allowlisted tab (`tabs.onActivated`, `windows.onFocusChanged`) and forwards `adapter.*` requests to the content script of that tab through a long-lived `runtime.Port`.
- The content script is injected with `chrome.scripting.registerContentScripts` for allowlisted origins only.
- SW state (session id, active tab, undo records) is mirrored in `chrome.storage.session` so that a restarted worker can resume.

## Snapshot

1. Walk the DOM from `document.body` (and open shadow roots), skipping `aria-hidden="true"`, `hidden`, `display: none` and the overlay host.
2. For each element, compute the role (explicit `role`, else implicit HTML role) and the accessible name and description with `dom-accessibility-api`.
3. Keep elements whose role maps to a kind: landmarks (`banner`, `navigation`, `main`, `region` with a name, `complementary`, `contentinfo`, `search`, `form` with a name) → `region`/`form`; `heading`; interactive roles (`button`, `link`, `textbox`, `searchbox`, `combobox`, `listbox`, `option`, `checkbox`, `radio`, `switch`, `slider`, `spinbutton`, `tab`, `menuitem`) → `control`; `dialog`/`alertdialog`; `table`/`grid`; `list`; `img` or `figure` with a name inside a chart container → `chart`; `status`/`alert`/`log` live regions → `status`.
4. Props: `role`, `name`, `description`, `value` (after redaction), `states`, `options` (≤ 20), `level` (headings), `columns` and `rows` (tables, ≤ 10 rows), `href_path` (links, same origin only), `bbox` (volatile).
5. Parent: nearest kept ancestor. Focus: the focused element and the open dialog.

Redaction (`redact.ts`) runs before anything leaves the content script: `type=password`, `autocomplete` values starting with `cc-` or equal to `one-time-code`, `type=hidden`, `[data-wysp-sensitive]` → `value` replaced by `"[redacted]"`; text truncated to 200 characters.

## Locators and refs

```ts
type Locator = { role: string; name: string; nth?: number; within?: Locator; testId?: string; css?: string };
// ref = "web://" + originKey + "/" + encodeLocator(locator)
// encodeLocator: within chain + role + "~" + slug(name) + (nth ? "#" + nth : "")
```

- `within` is the nearest named landmark or dialog. `nth` is added only when role and name are not unique within that scope.
- Resolution order: role + name within scope → `nth` → `data-testid` → CSS path. Zero or several matches → `TARGET_NOT_FOUND` with candidates.

## Actions

| id | risk | params | postcondition | guide step (templated) |
|---|---|---|---|---|
| `scroll_into_view` | ui_state | `target` | — | "Scroll to ${label:params.target}" |
| `focus_element` | ui_state | `target` | target in focus | "Go to ${label:params.target}" |
| `fill_field` | reversible | `target`, `value` | `props.value == value` (unless redacted) | "Type ${params.value} in ${label:params.target}" |
| `select_option` | reversible | `target`, `option` | `props.value == option` | "Open ${label:params.target} and choose ${params.option}" |
| `set_checked` | reversible | `target`, `checked` | `props.states.checked == checked` | "Tick ${label:params.target}" |
| `follow_link` | ui_state | `target` | navigation event to the link path | "Click the link ${label:params.target}" |
| `click_element` | irreversible | `target` | — (verification by lesson predicates) | "Click ${label:params.target}" |

- Guide step texts use the contract's templating (`${params.*}`, `${label:params.<ref param>}`), rendered by the Core.
- Value setting for React-controlled inputs: `Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(el, v)`, then `el.dispatchEvent(new Event("input", {bubbles: true}))` and `change`. Selects use `HTMLSelectElement`; custom comboboxes are opened by click then the option is clicked.
- Undo records keep the previous value and are applied with the same setter.

## Events and origin

- `MutationObserver` on `document` (subtree, attributes, childList, characterData), ignoring the overlay host; flush every 300 ms: re-snapshot the affected regions, diff per-entity digests, send `state_changed`.
- Capture-phase listeners for `click`, `input`, `change`, `submit` produce `user_action`. `event.isTrusted === false` means our synthetic events → `origin: wysp`. DOM mutations are tagged `wysp` during the execution window of an action (until the next flush), otherwise `user`.
- Navigation: `chrome.webNavigation.onHistoryStateUpdated` and `onCommitted` in the SW for the tracked tab.

## Overlay

A host `<div>` appended to `document.documentElement` with a closed Shadow DOM, `position: fixed; inset: 0; pointer-events: none; z-index: 2147483647`. It draws an outline (`#2DD4BF` glow, 6 px padding) around the target's `getBoundingClientRect()`, updated with `requestAnimationFrame` while visible, and an optional label with the guide step text.

## Demo dashboard ("Haunted Shop Analytics", owner B)

- React + Vite, routes `/` (dashboard) and `/reports`; deterministic seeded data (orders of potions, pumpkins and candles across regions "Transylvania", "Salem", "Sleepy Hollow", "Bayou").
- Landmarks: banner, navigation, main with named regions "Filters", "KPIs", "Sales chart", "Orders"; dialog "Create report" with textbox "Report name", checkboxes for metrics, radio group "Format", buttons "Save" and "Cancel"; status region "Report saved".
- "Reset demo" clears saved reports (localStorage of the dashboard itself) and resets filters.
- Served on `http://localhost:5180` (`npm run preview -w apps/web-tutor/demo-dashboard`), the default allowlisted origin.

## Correctness Properties

**WEB-P1: Redaction.** *For any* generated DOM containing sensitive fields with random values, the serialized snapshot and every user-action event contain none of those values. **Validates: Requirements 3.3, 5.2**

**WEB-P2: Locator round trip.** *For any* generated accessible DOM, resolving the locator of every snapshot entity returns exactly that element; ambiguous locators fail with `TARGET_NOT_FOUND`. **Validates: Requirements 4.1, 4.2**

**WEB-P3: Ref stability.** *For any* generated DOM and any unrelated insertion in another region, the refs of elements with a unique role and name in their region do not change. **Validates: Requirement 3.6**

**WEB-P4: Overlay invisibility.** *For any* page and highlight sequence, snapshots and mutation diffs taken with the overlay visible equal those taken without it. **Validates: Requirements 3.5, 6.2**

**WEB-P5: Origin tagging.** *For any* interleaving of synthetic Wysp actions and trusted user events (simulated in Playwright), Wysp-caused events are tagged `wysp` and user events `user`. **Validates: Requirement 5.3**

**WEB-P6: Allowlist enforcement.** *For any* origin not in the allowlist, no snapshot content and no event leave the content script. **Validates: Requirements 1.4, 3.3**

## Testing Strategy

- Vitest + happy-dom + fast-check (DOM generators of landmarks, forms and controls) for WEB-P1 to P4 and P6.
- Playwright with the unpacked extension and the demo dashboard for WEB-P5, value setting on React inputs, navigation events and the contract kit launcher (`launch.kind: playwright`).
- Contract kit through Playwright in CI.
