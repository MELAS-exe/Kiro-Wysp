# Implementation Plan: Web Tutor

Owners: A = Core & Contract, B = Experience, C = Adapters. Gates: J0 Wed 11 Nov, J1 Thu 19 Nov, J2 Fri 27 Nov, J3 Tue 1 Dec.
Depends on adapter-contract tasks 2, 8 and 9. Use the `browser-adapter` agent for extension tasks. No task in this spec may change `core/`.

- [ ] 1. Build the demo dashboard
  - "Haunted Shop Analytics" of design.md: landmarks, KPI cards, accessible chart, filters, orders table, "Create report" dialog, saved reports, status message, seeded data, "Reset demo", served on port 5180
  - _Owner: B_ · _Gate: J1 (Mon 16 Nov: filters + table + dialog), J2 (polish)_
  - _Requirements: 7.1, 7.2, 7.3_

- [ ] 2. Create the extension skeleton
  - MV3 manifest with minimal permissions, Vite build to `dist`, options page (Core URL, token, allowlist with optional host permission requests), service worker with the TS SDK client (heartbeat, reconnect, `chrome.storage.session` state), content script registration for allowlisted origins
  - _Owner: C_ · _Gate: Mon 23 Nov_
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3_

- [ ] 3. Implement the snapshot and redaction
  - `a11y.ts` (roles, names with `dom-accessibility-api`), `snapshot.ts` (kinds, props, parents, focus, open shadow roots, overlay skip), `redact.ts`
  - _Owner: C_ · _Gate: J2 (Mon 23 Nov)_
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [ ] 3.1 Write property tests for redaction and allowlist
  - **Property WEB-P1: Redaction**
  - **Property WEB-P6: Allowlist enforcement**
  - **Validates: Requirements 1.4, 3.3, 5.2**

- [ ] 4. Implement locators and refs
  - Locator building, ref encoding, resolution order, candidates on ambiguity
  - _Owner: C_ · _Gate: J2_
  - _Requirements: 3.6, 4.1, 4.2_

- [ ] 4.1 Write property tests for locators
  - **Property WEB-P2: Locator round trip**
  - **Property WEB-P3: Ref stability**
  - **Validates: Requirements 3.6, 4.1, 4.2**

- [ ] 5. Implement the actions
  - One file per action in `src/actions/` (the `new-action-integration` hook wires each one), native value setter, undo records, same-origin checks, `click_element` preview
  - _Owner: C_ · _Gate: J2_
  - _Requirements: 4.3, 4.4, 4.5_

- [ ] 6. Implement events, origin tagging and navigation
  - MutationObserver flush (300 ms), user-action listeners, `isTrusted` and execution-window tagging, webNavigation events
  - _Owner: C_ · _Gate: J2_
  - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [ ] 6.1 Write property test for origin tagging (Playwright)
  - **Property WEB-P5: Origin tagging**
  - **Validates: Requirement 5.3**

- [ ] 7. Implement the overlay highlight
  - Closed Shadow DOM overlay, glow outline following scroll and resize, step label
  - _Owner: C (visual design: B)_ · _Gate: J2_
  - _Requirements: 6.1, 6.2_

- [ ] 7.1 Write property test for overlay invisibility
  - **Property WEB-P4: Overlay invisibility**
  - **Validates: Requirements 3.5, 6.2**

- [ ] 8. Contract fixture and Playwright launcher
  - `contract.fixture.yaml`, Playwright launcher script for the kit (`launch.kind: playwright`), kit green in CI
  - _Owner: C (launcher support in the kit: A)_ · _Gate: J2_
  - _Requirements: 9.1_

- [ ] 9. Write the web profile
  - `profile.yaml`, `concepts.yaml` (≥ 10 concepts), lessons L01 dashboard tour, L02 filters with the "Transylvania" exercise, L03 create a report (guided, verified in the saved list), validated by `wysp validate-profile`
  - _Owner: B_ · _Gate: J2_
  - _Requirements: 8.1, 8.2, 8.3_

- [ ] 10. End-to-end on the same Core (gate J2)
  - Explain the region filter, guided report creation verified in the saved list; prove that `git diff` of `core/` is empty for this spec's work
  - _Owner: C with A and B_ · _Gate: J2 (Fri 27 Nov)_
  - _Requirements: 9.2, 8.2, 8.3_

- [ ] 11. Write the tutor README
  - Install (load unpacked), pairing, allowlist, run the dashboard, action table, privacy notes
  - _Owner: C_ · _Gate: J3_
  - _Requirements: 1.1, 1.2, 4.3_

- [ ] 12. Checkpoint: web tutor ready for recording
  - Ask the user if questions arise
