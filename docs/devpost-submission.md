# Devpost submission kit (Kiroween 2026, Skeleton Crew)

Deadline: **4 December 2026, 2:00 PM Pacific**. Submission period 30 Oct to 4 Dec 2026; the repository's first commit is 9 Nov 2026.
Everything below is ready to paste into the Devpost form. The long description is `docs/devpost.md`.

## Before you click Submit (all must be true)

- [ ] The repository is **public** (checked on 16 Nov: `git ls-remote` works without credentials) and shows an OSI licence (MIT, `LICENSE`).
- [ ] `.kiro/` is at the repository root and is **not** ignored (it is committed; `.gitignore` says so).
- [ ] The demo video is **under 3 minutes**, public or unlisted on YouTube/Vimeo, shows the project working, and its link is in `docs/devpost.md` (Links) and in the form.
- [ ] A judge can run it: the README's "Try it in two minutes" needs no account, no key and no Blender or IntelliJ.
- [ ] The Kiro write-up below is in the description (judges score "Implementation" on how Kiro was used).
- [ ] Last `git push` done, and the tag/commit you submit is the one you recorded the video on.

## Form fields

**Project name:** Wysp

**Tagline (short):** A small light that guides you through unfamiliar software: one AI-tutor skeleton, three applications.

**Category:** Skeleton Crew

**Description:** paste `docs/devpost.md` (sections: Inspiration, What it does, How we used Kiro, How we built it, Skeleton, Challenges, Accomplishments, What we learned, What's next, Try it).

**Built with:** Python, FastAPI, Pydantic, React, TypeScript, Vite, React Flow, ELK, Kotlin, IntelliJ Platform, Blender bpy, Chrome Manifest V3, JMESPath, MCP, Kokoro (ONNX), Whisper (Groq), Kiro

**Links:**
- Code: https://github.com/MELAS-exe/Kiro-Wysp
- Video: (paste)
- Try it: README "Try it in two minutes" (mock application, scripted model, nothing to install besides uv and Node)

## Skeleton Crew: the claim in one paragraph

One Core, one Panel and one protocol (contract 1.1.0) drive two unrelated applications, Blender (Python API) and IntelliJ IDEA (Kotlin plugin), plus a Chrome extension as a third. What changes per application is one adapter and one YAML profile. The Core contains no application vocabulary: a boundary check (`scripts/kiro/hook.py boundaries`, a Kiro hook and CI) enforces it, and the Contract Test Kit (`uv run wysp-contract --tutor <name>`) tells a new adapter author whether it complies. `docs/adapter-guide.md` walks through a complete, tested example.

## Kiro write-up (paste under "How we used Kiro")

- **Specs (7):** `.kiro/specs/` holds EARS requirements, designs with numbered correctness properties (CON, CORE, PED, PAN, BLD, IJ, WEB) and owner-tagged tasks for the contract, Core, pedagogy, Panel and the three tutors. Features were specified before they were built: persistent highlights started as contract requirements 8.3 to 8.6, project exploration as Core requirement 15, then code.
- **Property-based tests from the specs:** each property became a Hypothesis or fast-check test. They found real bugs that example tests missed: exercises that could never pass because a selection or caret change did not advance the state version (Blender, IntelliJ and the extension), a user action tagged as Wysp's, Wysp's own step being credited to the learner, a Panel that sent a spoken approval for irreversible actions, narration still published after an interrupt.
- **Steering (10 files):** trust and safety (provenance, permission gate, no code-running actions), Core/adapter boundary, contract guide, testing, pedagogy and the design system, applied to every session.
- **Hooks (10 hooks in 3 files):** boundary guard, schema sync, offline contract checks, trust review, new-action integration, formatting, profile validation.
- **Custom agents:** `blender-adapter`, `browser-adapter` and a read-only `contract-guardian` did scoped adapter work and reviews; `wysp-tutor` is the tutor itself.
- **MCP, both ways:** the Core serves an authenticated MCP endpoint (`--llm external`), so the user's own Kiro does the thinking while Wysp provides live application state, board, voice and the permission gate; `wysp mcp-bridge` exposes a read-only stdio view of a running tutor; Context7 and Playwright MCP servers were used while building.
- **Live sessions fed back into specs:** the journal `docs/kiro-journal.md` records each finding (for example a UI-thread stall in the IDE, a second Panel reading every sentence twice) with the fix and the spec change.

## Image gallery (in this order, all in `docs/img/`)

1. `panel-guide.png`: the Panel guiding a change on the Blender scene
2. `panel-board.png`: the board built from real entities (provenance styles)
3. `blender-panel-exercise.png`: the exercise card inside Blender
4. `web-tutor-sidepanel.png`: the same Panel in Chrome's side panel
5. `web-tutor-highlight.png`: a persistent highlight on a page element
6. `panel-chat.png`: the minimal chat view
7. Thumbnail / cover: `docs/brand/social-1500x1000.png` (mascot)

Missing on purpose: an IntelliJ screenshot. Take one during the demo run (tool window with the Panel, a highlighted control) and add it as image 2.

## Demo video (under 3 minutes)

The shot-by-shot script with timings and the window layout are in `docs/demo-setup.md` (product demo target: explain, interrupt, guide, verify, then "only the adapter and the profile changed"). Start with the two-minute path in the README only if a live run fails; the video should use the real applications.

## Honest limits (say them if asked, they are in the repository)

- IntelliJ and Chrome were verified mostly through unit, platform and Chromium tests plus live sessions; the Blender tutor has the most live coverage.
- Speech listening uses Whisper on Groq (the only audio that leaves the machine; `WYSP_STT_PROVIDER=none` turns it off). The female voice (Kokoro) and the Windows voices are offline.
- Unpacked Chrome extension only (no store release); one Windows machine tested.