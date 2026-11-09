---
inclusion: fileMatch
fileMatchPattern: ["panel/**", "apps/web-tutor/demo-dashboard/**"]
---

# Panel and UI Design System

## Layout modes
- `compact` (about 360 x 200 px): mic button, live caption, current step, permission prompts.
- `side` (420 to 560 px wide, full height): board, captions and exercise card. Default mode, docked next to Blender or the browser.
- `full`: large board workspace with a details pane and lesson progress.

## Visual identity ("wisp")
- Night background `#0F172A`, surface `#1E293B`, text `#E2E8F0`, muted text `#94A3B8`.
- Wisp glow (focus, active narration) `#2DD4BF`. Pumpkin accent (actions, warnings) `#F97316`. Success `#22C55E`. Danger `#EF4444`.
- System UI sans-serif font; monospace for refs and values. Corner radius 10 px. One glow effect at a time.

## Provenance language (identical everywhere)

| Provenance | Node style | Caption marker |
|---|---|---|
| observed | solid 2 px border, full opacity, small "eye" icon | none |
| inferred | dashed border, 85 % opacity, optional confidence badge | "likely" / "probablement" |
| illustrative | hatched background, grey border, "example" tag | "for example" / "par exemple" |

Always show a legend in `side` and `full` modes.

## Board
- Layouts: `stack` (ordered vertical list, for example a modifier stack), `tree` (hierarchy), `graph` (ELK layered), `sequence` (horizontal steps). The layout is deterministic for a given board state.
- At most 60 visible nodes. Collapse the rest into "+N" group nodes.
- Animations last 300 ms or less, ease-out, and respect `prefers-reduced-motion`. Focus is shown with the glow and a gentle scale (1.03).
- Clicking a node selects it and asks the Core to highlight the entity in the application. Every node offers "Why?", and "Expand" when it has children.

## Interaction rules
- Captions are always visible, also during voice. The user can type instead of speaking.
- Push-to-talk: hold `Space` (when the Panel has focus) or the mic button. Speaking or pressing `Esc` interrupts the narration immediately.
- Permission dialog: action title, target, risk badge, reversible yes/no, rationale, Approve / Deny, and "Allow for this lesson" for reversible actions only. Irreversible actions cannot be approved by voice.
- No tutoring logic in components: components render store state and send UI protocol messages.

## Accessibility and i18n
- Every control has an accessible name, is reachable with the keyboard, and has a contrast ratio of at least 4.5:1.
- Strings live in `panel/src/i18n/{en,fr}.json`. Demo language: English (French supported).

## Demo dashboard (`apps/web-tutor/demo-dashboard`)
- Halloween-themed "Haunted Shop Analytics": KPIs, sales chart, filters (date range, region, category), orders table, "Create report" dialog, saved reports list.
- Accessible by design (labels, roles, landmarks), because it showcases the interface integration level. Deterministic seeded data and a reset button.
