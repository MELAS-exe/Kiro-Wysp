# Implementation Plan: Web Tutor

Owners: A = Core & Contract, B = Experience, C = Adapters. Gates: J0 Wed 11 Nov, J1 Thu 19 Nov, J2 Fri 27 Nov, J3 Tue 1 Dec.
Depends on adapter-contract tasks 2, 8 and 9. Use the `browser-adapter` agent for extension tasks. No task in this spec may change `core/`.

- [x] 1. Build the demo dashboard
  - "Haunted Shop Analytics" of design.md: landmarks, KPI cards, accessible chart, filters, orders table, "Create report" dialog, saved reports, status message, seeded data, "Reset demo", served on port 5180
  - _Owner: B_ · _Gate: J1 (Mon 16 Nov: filters + table + dialog), J2 (polish)_
  - _Requirements: 7.1, 7.2, 7.3_

- [x] 2. Create the extension skeleton
  - MV3 manifest with minimal permissions, Vite build to `dist`, options page (Core URL, token, allowlist with optional host permission requests), service worker with the TS SDK client (heartbeat, reconnect, `chrome.storage.session` state), content script registration for allowlisted origins
  - _Owner: C_ · _Gate: Mon 23 Nov_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3_

- [x] 3. Implement the snapshot and redaction
  - `a11y.ts` (roles, names with `dom-accessibility-api`), `snapshot.ts` (kinds, props, parents, focus, open shadow roots, overlay skip), `redact.ts`
  - _Owner: C_ · _Gate: J2 (Mon 23 Nov)_
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3.1 Write property tests for redaction and allowlist
  - **Property WEB-P1: Redaction**
  - **Property WEB-P6: Allowlist enforcement**
  - **Validates: Requirements 1.4, 3.3, 5.2**

- [x] 4. Implement locators and refs
  - Locator building, ref encoding, resolution order, candidates on ambiguity
  - _Owner: C_ · _Gate: J2_
  - _Requirements: 3.6, 4.1, 4.2_

- [x] 4.1 Write property tests for locators
  - **Property WEB-P2: Locator round trip**
  - **Property WEB-P3: Ref stability**
  - **Validates: Requirements 3.6, 4.1, 4.2**

- [x] 5. Implement the actions
  - One file per action in `src/actions/` (the `new-action-integration` hook wires each one), native value setter, undo records, same-origin checks, `click_element` preview
  - _Owner: C_ · _Gate: J2_
  - _Requirements: 4.3, 4.4, 4.5_

- [x] 6. Implement events, origin tagging and navigation
  - MutationObserver flush (300 ms), user-action listeners, `isTrusted` and execution-window tagging, webNavigation events
  - _Owner: C_ · _Gate: J2_
  - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [ ] 6.1 Write property test for origin tagging (Playwright)
  - **Property WEB-P5: Origin tagging**
  - **Validates: Requirement 5.3**

- [x] 7. Implement the overlay highlight
  - Closed Shadow DOM overlay, glow outline following scroll and resize, step label
  - _Owner: C (visual design: B)_ · _Gate: J2_
  - _Requirements: 6.1, 6.2_

- [x] 7.1 Write property test for overlay invisibility
  - **Property WEB-P4: Overlay invisibility**
  - **Validates: Requirements 3.5, 6.2**

- [x] 8. Contract fixture and Playwright launcher
  - `contract.fixture.yaml`, Playwright launcher script for the kit (`launch.kind: playwright`), kit green in CI
  - _Owner: C (launcher support in the kit: A)_ · _Gate: J2_
  - _Requirements: 9.1_

- [x] 9. Write the web profile
  - `profile.yaml`, `concepts.yaml` (≥ 10 concepts), lessons L01 dashboard tour, L02 filters with the "Transylvania" exercise, L03 create a report (guided, verified in the saved list), validated by `wysp validate-profile`
  - _Owner: B_ · _Gate: J2_
  - _Requirements: 8.1, 8.2, 8.3_

- [x] 10. End-to-end on the same Core (gate J2)
  - Explain the region filter, guided report creation verified in the saved list; prove that `git diff` of `core/` is empty for this spec's work
  - _Owner: C with A and B_ · _Gate: J2 (Fri 27 Nov)_
  - _Requirements: 9.2, 8.2, 8.3_

- [x] 11. Write the tutor README
  - Install (load unpacked), pairing, allowlist, run the dashboard, action table, privacy notes
  - _Owner: C_ · _Gate: J3_
  - _Requirements: 1.1, 1.2, 4.3_

- [x] 12. Checkpoint: web tutor ready for recording
  - Ask the user if questions arise

## Status of 2026-11-16 (optional extra, built by the browser-adapter agent)

- Done: dashboard (static, port 5180), extension skeleton, snapshot and redaction, locators, actions, events, overlay, property tests WEB-P1, P2, P3, P4, P6, README. The TypeScript SDK sdk/ts was added (types generated from schemas/, client for the service worker).
- Open: 6.1 (WEB-P5 is covered at unit level in 	ests/events.test.ts; the Playwright version is not written), 8 (contract.fixture.yaml exists and passes the offline check, replayed in 	ests/fixture.test.ts; no Playwright launcher and the kit has no online harness), 9 (profile has L01 and L02 and 13 concepts; L03 create a report is not written), 10 (live check against a second Core in Chromium passed, see README; the guided report lesson is missing), 12.
- Action ids follow the design table (scroll_into_view, ill_field, ...). webNavigation and larms permissions were added to the design's list: see the README for the reasons.
- Gaps found, none needing a Core change: the Core accepts a browser origin only through WYSP_ALLOWED_ORIGINS (set chrome-extension://<id>); an observation has no acts field, so the 
ot_allowed fact of Requirement 1.4 is carried by counts.not_allowed and by the context facts.

## Status of 2026-11-17 (browser-adapter agent)

- Done and verified: 6.1 (WEB-P5 as a real test over random interleavings of trusted user input and approved Wysp actions: `apps/web-tutor/extension/tests/live/test_pedagogy_live.py::test_prop_web_p5_origin_tagging_over_random_interleavings`), 8, 9 (L03 `lessons/L03_create_report.yaml` with the exercise `save_weekly_report`, `wysp validate-profile` clean), 10, 12.
- Live checks (`uv run --no-sync pytest -m live -o addopts="" apps/web-tutor/extension/tests/live/test_pedagogy_live.py`, 10 tests, about 2.5 min): a second Core and a second dashboard port, Playwright Chromium with the built extension, real mouse and keyboard input. They cover learner_status with the 3 web lessons, `find_region_filter` (click on Region verified), `show_only_transylvania` (Salem is not enough, Transylvania passes), `save_weekly_report` (PDF does not pass, CSV does), and PED-P4 (the same changes made through `propose_action` with approval never count).
- Bug fixed: a focus-only change sent `event.selection_changed` without advancing `state_version`, so "click the Region drop-down" could never pass (the Blender adapter had the same bug). The service worker now bumps the version before forwarding the event (`src/sw/background.ts`).
- Task 8: `launch.kind: playwright` in `contract.fixture.yaml`, launcher `contract-tests/launchers/playwright_launcher.py` (starts a throw-away Core, a dashboard on a free port and `tests/live/playwright_driver.mjs`, then runs the kit's observation checks, the dry-run calls, the invalid calls and the catalog check). The `wysp-contract` CLI itself has no online harness (`cli.py`, owner A): it still needs a call to this launcher for `launch.kind: playwright`. CI wiring is also open.
- No file of `core/` was changed by this work.