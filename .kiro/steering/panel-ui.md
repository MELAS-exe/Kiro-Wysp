---
inclusion: fileMatch
fileMatchPattern: ["panel/**", "apps/web-tutor/demo-dashboard/**"]
---

# Panel and UI Design System

## Layout modes
- `compact` (about 360 x 200 px): mic button, live caption, current step, permission prompts.
- `side` (420 to 560 px wide, full height): board, captions and exercise card. Default mode, docked next to Blender or the browser.
- `full`: large board workspace with a details pane and lesson progress.

## Visual identity (the mascot's colours)
The brand palette is measured from the mascot (a violet flame with glasses); the full table, files and rules are in `docs/brand/README.md`.
- Night background `#120532`, surface `#1D0E4A`, surface 2 `#2A1766`, lines `#3B2A80` and `#5440A6`.
- Text lavender `#F4E5FD`, muted text `#B9A3E3`.
- Lilac glow (focus, active narration, links, primary buttons) `#CA84FC`. Brand violet `#6503FC` for fills and borders only (2.7:1 on night, never text). Cheek-pink accent (speaking, markers, notes) `#FE7C9C`. Ink `#0D012F` for text on lilac. Success `#22C55E`. Danger `#EF4444`.
- System UI sans-serif font; monospace for refs and values. Corner radius 10 px. One glow effect at a time.
- The mascot (`panel/public/wysp-mark.png`) greets the user on the empty chat; the favicon is the mascot.

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
- "Haunted Shop Analytics" in the Wysp palette: KPIs, sales chart, filters (date range, region, category), orders table, "Create report" dialog, saved reports list.
- Accessible by design (labels, roles, landmarks), because it showcases the interface integration level. Deterministic seeded data and a reset button.

