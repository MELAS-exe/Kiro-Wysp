# Requirements Document: Web Tutor

> **Optional extra** (decision of 2026-11-11, updated 2026-11-16): the IntelliJ tutor (`.kiro/specs/intellij-tutor/`) replaced the web tutor as application 2. The web tutor was built afterwards as an optional third tutor; it is not on the demo path and must not destabilise the other two.

Lead: Person C (extension). Person B owns the demo dashboard and the web profile. Reviewer: Person A (contract).

## Introduction

The web tutor is the second application built on Wysp, at the **interface** integration level. A Chrome Manifest V3 extension implements the adapter contract from the DOM and the accessibility semantics of a web application. The demo target is "Haunted Shop Analytics", a dashboard built for the demo. The tutor must explain the dashboard and its filters, guide the creation of a report and verify the interface changes, using **exactly the same Core and Panel** as the Blender tutor.

## Glossary

- **Service worker (SW)**: the extension's background script, holding the WebSocket to the Core.
- **Content script (CS)**: the extension script running in the page, doing all DOM work.
- **Snapshot**: the observation built from the DOM and accessibility information.
- **Locator**: a description used to find an element again: role, accessible name, index, scope.
- **Overlay**: the extension's highlight layer, inside a Shadow DOM root.
- **Allowlist**: the origins on which the extension is active.

## Requirements

### Requirement 1: Installation, pairing and allowlist

**User Story:** As a user, I want to install the extension, pair it with my local Core and choose the sites it may read.

#### Acceptance Criteria

1. THE extension SHALL be loadable unpacked from `apps/web-tutor/extension/dist` in Chrome 116 or later.
2. THE options page SHALL let the user set the Core address, paste the pairing token and edit the allowlist of origins (default: the demo dashboard origin).
3. THE extension SHALL request host access only for allowlisted origins (optional host permissions granted from the options page).
4. WHILE the active tab's origin is not allowlisted, THE extension SHALL not read the page and SHALL report an empty observation with a `not_allowed` fact.

### Requirement 2: Connection

**User Story:** As a user, I want the browser tutor to stay connected while I work.

#### Acceptance Criteria

1. THE service worker SHALL connect to the Core, send `wysp.hello` and send a heartbeat at least every 20 seconds.
2. WHEN the service worker restarts, THE extension SHALL reconnect and send `wysp.hello` again, restoring its state from `chrome.storage.session`.
3. THE adapter SHALL observe the active tab of the last focused window among allowlisted tabs.

### Requirement 3: Snapshot

**User Story:** As the Core, I want the page as meaningful entities rather than raw HTML.

#### Acceptance Criteria

1. THE snapshot SHALL contain entities of kinds `page`, `region`, `heading`, `form`, `control`, `dialog`, `table`, `list`, `chart` and `status`, with role, accessible name, description and state (checked, expanded, disabled, selected, required, invalid) computed from ARIA and HTML semantics.
2. THE snapshot SHALL include the options of comboboxes and listboxes (at most 20), the column headers and the first 10 rows of tables, and the accessible label of charts.
3. THE snapshot SHALL never include values of password, credit-card, one-time-code or hidden fields, fields marked `data-wysp-sensitive`, cookies, storage or request headers.
4. THE snapshot SHALL truncate text values to 200 characters.
5. THE snapshot SHALL skip the extension's own overlay and traverse open shadow roots.
6. Refs SHALL be derived from locators, so that an element keeps its ref while its role, name and position in its region do not change.

### Requirement 4: Locators and actions

**User Story:** As a learner, I want the tutor to point at and, with my permission, operate the real controls of the page.

#### Acceptance Criteria

1. THE extension SHALL resolve locators at execution time by role and accessible name within a region, then by index, then by test id, then by CSS path.
2. IF a locator matches zero or several elements, THEN THE action SHALL fail with `-32012 TARGET_NOT_FOUND` and list up to 5 candidates in `error.data`.
3. THE adapter SHALL provide `scroll_into_view` and `focus_element` (ui_state), `fill_field`, `select_option` and `set_checked` (reversible, undo restores the previous value), `follow_link` (ui_state, same-origin links only) and `click_element` (irreversible, with a preview of the target).
4. WHEN setting a value, THE extension SHALL use the native value setter and dispatch `input` and `change` events, so that framework-controlled inputs update.
5. THE extension SHALL refuse `click_element` on targets that would leave the allowlisted origins.

### Requirement 5: Events

**User Story:** As a learner, I want the tutor to notice what I do on the page.

#### Acceptance Criteria

1. WHEN the DOM changes, THE content script SHALL compute the changed entities and send `event.state_changed` at most once per 300 ms.
2. WHEN the user clicks, types, changes a value or submits a form, THE content script SHALL send `event.user_action` with the target ref and without sensitive values.
3. THE adapter SHALL tag events caused by Wysp actions with `origin: wysp`, using the synthetic-event flag (`isTrusted === false`) and an execution window, and user events with `origin: user`.
4. WHEN the page URL changes (including history navigation in single-page apps), THE adapter SHALL send `event.navigation`.

### Requirement 6: Highlight

**User Story:** As a learner, I want to see the control the tutor is talking about.

#### Acceptance Criteria

1. WHEN the Core asks to highlight an element, THE overlay SHALL draw a glowing outline around it, scroll it into view if needed and follow scrolling and resizing for the requested duration.
2. THE overlay SHALL live in a Shadow DOM root, SHALL NOT intercept clicks and SHALL NOT change the page's own DOM state.

### Requirement 7: Demo dashboard

**User Story:** As the team, we want a realistic, accessible and deterministic target web application for the demo.

#### Acceptance Criteria

1. THE demo dashboard SHALL show KPI cards, a sales chart with an accessible summary, filters (date range, region combobox, category checkboxes), an orders table, a "Create report" dialog (name, metrics, format, Save) and a saved reports list with a confirmation status message.
2. THE dashboard SHALL use seeded data so that the same filters always show the same numbers, and SHALL provide a "Reset demo" button.
3. THE dashboard SHALL use proper labels, roles and landmarks.

### Requirement 8: Web profile

**User Story:** As a learner, I want a short course on reading a dashboard, filtering and creating a report.

#### Acceptance Criteria

1. THE profile SHALL define the skills `dashboard_reading`, `filtering` and `report_creation`, a glossary of at least 10 concepts, and the lessons L01 dashboard tour, L02 filters and L03 create a report.
2. Lesson L02 SHALL include the exercise "show only Transylvania orders", verified by the region combobox value and the table content.
3. Lesson L03 SHALL guide the creation of a report and verify that it appears in the saved reports list with the chosen metrics.

### Requirement 9: Contract

#### Acceptance Criteria

1. THE extension SHALL pass the contract kit through a Playwright launcher with `apps/web-tutor/contract.fixture.yaml`.
2. THE web tutor SHALL not require any change in `core/`.
