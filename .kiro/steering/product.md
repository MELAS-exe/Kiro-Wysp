---
inclusion: always
---

# Wysp — Product Overview

Wysp is an open-source framework for building **AI tutors for software applications**. A Wysp tutor observes the real state of an application, explains its concepts, builds an interactive visual board, guides the user through actions and verifies what the user has learned. It works by voice, with a board, and through one adapter per application.

Wysp is our entry for **Kiroween 2026, category Skeleton Crew**: a lean, reusable skeleton (Wysp Core) proven by two very different applications built on it:

- `apps/blender-tutor`: tutoring on a Blender 3D scene (native integration through the Python API).
- `apps/web-tutor`: tutoring on a web dashboard (interface integration through the DOM and the accessibility tree, via a Chrome extension).

The name evokes the will-o'-the-wisp: a small light that guides you through unfamiliar software.

## Vocabulary (use these exact terms in code, docs and commits)

| Term | Meaning |
|---|---|
| Wysp Core | Shared Python engine: orchestration, reasoning, board, narration, pedagogy, verification, permissions, events. Knows no application. |
| Adapter | App-specific component implementing the adapter contract (`observe`, `get_context`, `get_actions`, `execute`, `undo`, `highlight`, events). |
| Profile | App-specific **data** (YAML): skills, concepts, lessons, exercises, success criteria. |
| Tutor | Adapter + Profile plugged into the Core. One folder per tutor under `apps/`. |
| Panel | The single React UI (board, captions, voice, permission dialogs) shared by all tutors. |
| Board | The interactive visual view rendered from the Visual Model (nodes, edges, steps, annotations). |
| Provenance | Epistemic status of every displayed or spoken fact: `observed`, `inferred`, `illustrative`. |
| Integration level | `native` (API), `interface` (DOM/accessibility), `visual` (screenshots/vision). |
| Permission gate | Core component that decides whether a proposed action may run, and asks the user when needed. |
| Evidence | Record proving a verification: query, actual value, expected value, observation id, timestamp. |

## Product promise

See the context, understand the concept, try the action, verify the result. Wysp aims at the user's **autonomy**: it prefers to *guide* the user ("guide" mode: the user acts, Wysp watches and verifies) rather than acting for the user ("do" mode), unless the user explicitly asks.

## Non-negotiable rules

1. Wysp Core contains no application-specific code or vocabulary. Everything app-specific lives in an adapter or a profile.
2. Nothing is presented as observed unless it comes from an adapter observation. Inferences and pedagogical examples are labelled as such.
3. No action with an impact runs without the user's authorization. Every executed action is verified afterwards, and reversible actions can be undone.
4. Both tutors use exactly the same Core, Panel and protocol. Proving it is part of the demo.

## Demo target (video under 3 minutes)

Blender: explain an object and its modifiers while the board builds up, interrupt the explanation, authorize a guided change, verify it. Browser: the same Core explains a dashboard filter and guides the creation of a report. End: show that only the adapter and the profile changed.
