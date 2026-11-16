# Web tutor (browser connector)

An optional third tutor. A Chrome Manifest V3 extension implements the Wysp adapter contract (integration level `interface`) from the DOM and the accessibility tree of the pages you allow. It uses the same Core, Panel and protocol as the Blender and IntelliJ tutors; the Core has no web-specific code. Spec: `.kiro/specs/web-tutor/`.

```
Core  <-- WebSocket JSON-RPC -->  service worker  <-- chrome.tabs messages -->  content script  -->  DOM
                                  (heartbeat, reconnect,                          (snapshot, locators,
                                   undo tokens in storage.session)                 actions, events, overlay)
```

## Install

1. Build: `npm.cmd install` then `npm.cmd run build -w apps/web-tutor/extension`. The output is `apps/web-tutor/extension/dist`.
2. Chrome 116 or later: `chrome://extensions`, turn on Developer mode, **Load unpacked**, choose `dist`. The manifest carries a public key, so the id is always `cnmikeniefgoeibijogfncggjkafakhk` (the matching private key does not exist; it is only used to pin the id).
3. Start the Core so that it accepts your extension's origin (the Core refuses browser origins that are not allowlisted):
   `$env:WYSP_ALLOWED_ORIGINS = "chrome-extension://cnmikeniefgoeibijogfncggjkafakhk"; uv run wysp serve`
4. Options page (opens on install, or right-click the Wysp icon > Options). It shows the connection state, what to do when it is not connected, and an **Open Wysp** button:
   - **Core address**: `ws://127.0.0.1:8765/ws/adapter` (only loopback addresses are accepted).
   - **Pairing token**: the contents of `~/.wysp/token` (`uv run wysp token` prints the path). Treat it like a password.
   - **Sites**: the demo dashboard origin `http://localhost:5180` is listed by default. Press **Grant** to give the extension access to it. Add other origins with **Add and allow**; Chrome asks for each one.
5. Demo page: `npm.cmd run preview -w apps/web-tutor/demo-dashboard`, then open `http://localhost:5180`. Keep that tab active: the adapter observes the active tab of the last focused window among allowed tabs.

**Open the tutor**: click the Wysp icon in the toolbar (Chrome 114+ side panel), or the floating Wysp button at the bottom right of an allowed page, or **Open Wysp** in the options page. The side panel loads the Core's Panel (`<core>/#wysp_token=...`, the token is read from the extension settings and removed from the address by the Panel). When no token is set or the Core is not running, it shows a short explanation with a button to the settings instead of a blank page. If Chrome refuses to open the side panel from the page button, a tooltip says to click the toolbar icon. With another tutor also connected (for example IntelliJ), choose **Chrome** under the Panel menu (**...**) > **Looking at**.

The options page shows the connection state (`connected`, `no_token`, `refused`, ...). If Chrome is managed by an administrator that blocks unpacked extensions, use a Chromium build (see "Live checks").

## What it does

- **Snapshot**: entities of kind `page`, `region`, `heading`, `form`, `control`, `dialog`, `table`, `list`, `chart`, `status`, with role, accessible name (`dom-accessibility-api`), description and states. At most 500 entities, 20 options per list, 10 table rows. Open shadow roots are traversed.
- **Refs**: `web://<host[:port]>/<region>/<role>~<name>`, e.g. `web://localhost:5180/region~filters/combobox~region`. A `#2` suffix tells apart repeated role + name inside a region. Refs are rebuilt from the live DOM at execution time; an ambiguous or missing target fails with `-32012 TARGET_NOT_FOUND` and up to 5 candidates.
- **Events**: `event.state_changed` (at most one per 300 ms), `event.user_action`, `event.selection_changed`, `event.navigation`, `event.highlight_dismissed`. Origin is `wysp` for synthetic events and for changes inside the execution window of a Wysp action, `user` otherwise.
- **Highlight**: a lilac glow (`#CA84FC`) with a step label on the Wysp surface colour (pink accent bar, no animation under `prefers-reduced-motion`), in a closed Shadow DOM overlay that does not intercept clicks. `duration_ms: 0` keeps it until `adapter.clear_highlight` or until the user clicks or types in the element (then `event.highlight_dismissed`).

## Actions

The catalog is closed and declarative. No action evaluates code or injects a page script.

| Action | Risk | Reversible | What it does |
|---|---|---|---|
| `scroll_into_view` | ui_state | no | Scrolls to the element |
| `focus_element` | ui_state | no | Moves keyboard focus |
| `fill_field` | reversible | yes (undo restores the old text) | Replaces the text of a text field. Refuses password, card, one-time-code and hidden fields |
| `select_option` | reversible | yes | Chooses an option of a native `<select>` by label or value |
| `set_checked` | reversible | yes | Ticks or unticks a checkbox, switch or radio |
| `follow_link` | ui_state | no | Opens a link to the same allowlisted site only |
| `click_element` | irreversible | no | Clicks a control. The dry run returns a preview (target, whether it would submit a form). Refuses links that leave the allowlisted sites |

Values are set through the native value setter of the element's prototype, then `input` and `change` are dispatched, so React-controlled inputs update. Custom (div-based) drop-downs are not supported by `select_option`.

## Privacy and permissions

- The extension reads a page only when its origin is in the allowlist **and** the host permission was granted. The content script is registered for those origins only and checks the allowlist again before anything leaves it.
- Never sent: values of password, credit-card, one-time-code and hidden fields, and of anything inside `[data-wysp-sensitive]` (shown as `[redacted]`); cookies, storage, request headers. Texts are cut to 200 characters. Page URLs are sent without query string and fragment.
- The WebSocket goes to the Core on this computer only, authenticated with the pairing token (stored in `chrome.storage.local`, never logged).
- Page content is data, not instructions. The permission gate of the Core is the barrier for any action.
- Permissions and why: `storage` (settings, undo tokens, state version), `scripting` (register the content script for allowed origins), `webNavigation` (`event.navigation`, including single-page apps), `alarms` (a 30 s wake-up revives a stopped service worker so it reconnects), and **optional** host permissions requested per origin from the options page.

## Tests

| Command | What |
|---|---|
| `npm.cmd test -w apps/web-tutor/extension` | Vitest + happy-dom: snapshot, redaction, locators, actions, events, overlay, fixture replay, properties WEB-P1, P2, P3, P4, P6 (and P5 at unit level) |
| `npm.cmd test -w sdk/ts` | TypeScript SDK client |
| `npm.cmd run typecheck -w apps/web-tutor/extension` | Type check |
| `uv run wysp-contract --tutor web-tutor --offline` | Contract fixture check |
| `uv run wysp validate-profile apps/web-tutor/profile` | Profile check |

Live checks (need a Chromium and a running Core; not run by `npm test`):

```
$env:CHROME = "<path to a Chromium chrome.exe>"   # branded Chrome may block unpacked extensions by policy
node apps/web-tutor/extension/tests/live/live_check.mjs --core ws://127.0.0.1:8765/ws/adapter --token-file ~/.wysp/token --hold 60
$env:WYSP_MCP_URL = "http://127.0.0.1:8765/mcp"   # while the extension is held connected (Core needs --mcp or --llm external)
uv run --no-sync python apps/web-tutor/extension/tests/live/mcp_probe.py --token-file ~/.wysp/token
```

Live pedagogy and origin-tagging checks (second Core, Chromium through Playwright, real mouse and keyboard input; build the extension first):

```
uv run --no-sync pytest -m live -o addopts="" -p no:cacheprovider apps/web-tutor/extension/tests/live/test_pedagogy_live.py
uv run --no-sync python contract-tests/launchers/playwright_launcher.py --tutor web-tutor   # online contract run
```

Both start their own Core and dashboard on free ports (the Core accepts the extension through `WYSP_ALLOWED_ORIGINS=chrome-extension://cnmikeniefgoeibijogfncggjkafakhk`) and close everything they start. The lessons name the dashboard as `localhost:5180`; the live test rewrites that in a temp copy of the profile.

`live_check.mjs` loads the built extension through the DevTools pipe in a throw-away profile, adds the page origin as a host permission in a copy of the manifest (the optional-permission prompt cannot be answered without a user), and prints whether the adapter connected. It never prints the token.

## Known limits

- The online harness exists: `uv run --no-sync wysp-contract --tutor web-tutor`. `launch.kind: playwright` is run by `contract-tests/launchers/playwright_launcher.py` (see Tests). The fixture is also replayed against the extension logic in `tests/fixture.test.ts`.
- Only the top frame is read. Closed shadow roots and cross-origin iframes are not.
- `select_option` supports native selects only.
- The optional host permission prompt was not exercised by an automated browser test. `tests/live/panel_access_check.mjs` (Playwright Chromium, second Core) covers the launcher, options, side panel page, fallback and highlight; headless Chromium has no side panel UI, so the real side panel opening beside a page is only checked by hand. Screenshots: `docs/img/web-tutor-*.png`.

## Profile

`profile/` holds the web profile (skills `dashboard_reading`, `filtering`, `report_creation`, 13 concepts, lessons L01 dashboard tour and L02 region filter with the "show only Transylvania orders" exercise). The demo dashboard is in `demo-dashboard/` (static, seeded data, "Reset demo").

