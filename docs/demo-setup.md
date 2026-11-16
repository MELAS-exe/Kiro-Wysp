# Demo setup (video under 3 minutes)

Goal of the video (from `.kiro/steering/product.md`): **Blender** explain an object and its modifiers while the board builds up, interrupt, authorize a guided change, verify it. **IntelliJ** the same Core explores the student's project, explains the function under the caret, points at the IDE control, guides a rename and verifies it. **End** only the adapter and the profile changed.

## 1. Screen and windows

| Item | Setting |
|---|---|
| Resolution / scale | 1920 x 1080 at 100 % (or 2560 x 1440 at 125 %). Record at 1080p. At 150 % or more the Panel's side mode gets cramped. |
| Theme | Windows dark mode, notifications off (Focus assist), taskbar auto-hidden. |
| Blender | Left, about 1440 px wide (x 0 to 1440), full height. Scene `apps/blender-tutor/demo/pumpkin.blend`, 3D viewport + Properties editor visible. |
| IntelliJ | Left, 1440 px wide, project `apps/intellij-tutor/demo/sample-project`. The Wysp tool window is hidden: the Panel is the separate window on the right. |
| Chrome (optional web tutor) | Left, 1440 px wide, the demo dashboard. Not in the 3-minute path. |
| Panel | Chrome app window on the right edge, **side mode, 480 x full height** (`open_panel.py --mode side`). Compact (360 x 200, bottom right) only for shots where the app needs the whole screen. |
| Audio | Speakers or headset output on, microphone selected as default input. Browser allows the microphone for `127.0.0.1:8765`. |

Panel modes: `side` is the default. Switch with the menu (three dots, Layout) or by URL: `http://127.0.0.1:8765/?mode=compact`. The last mode is remembered.

## 2. Start commands

Everything below runs from the repository root in PowerShell.

One command that starts what a script can start (idempotent, never restarts a running Core):

```powershell
scripts\demo_up.ps1 -Mode side            # Core (--llm external), tutor loop window, Panel window
scripts\demo_up.ps1 -Llm scripted -Scenario apps\blender-tutor\demo\scenario.yaml   # offline fallback, no model
```

Or step by step:

1. **Core.** `uv run wysp serve --llm external` (Kiro is the model). Check `http://127.0.0.1:8765/api/health`.
2. **Tutor loop** (second window): `powershell -ExecutionPolicy Bypass -File scripts\kiro_tutor.ps1`. It restarts the agent turn by itself; Ctrl+C stops it.
3. **Panel:** `uv run --no-project python scripts\open_panel.py --mode side` (use `--print` to see the Chrome command; `--x/--y/--width/--height` override the placement).
4. **Blender.** First time: `uv run python scripts\build_blender_extension.py --install`, enable the extension, open `pumpkin.blend` (rebuild it with `blender -b --python apps\blender-tutor\demo\build_scene.py -- --out apps\blender-tutor\demo\pumpkin.blend`). The adapter connects by itself; the Panel's menu shows "Blender".
5. **IntelliJ.** First time: `cd apps\intellij-tutor\plugin; .\gradlew.bat buildPlugin`, install the ZIP from disk, restart. Open the sample project; **Tools > Wysp > Connect to Wysp Core** if it does not connect. See `apps/intellij-tutor/README.md`.
6. **Chrome extension (optional).** `chrome://extensions`, developer mode, load unpacked `apps\web-tutor\extension\dist`, allow the demo dashboard origin in its options.

Switch tutors in the Panel menu ("Looking at"). Only the adapter and the profile change; the Panel and Core stay the same, which is the closing shot.

## 3. Script (2 min 50 s)

| Time | Shot | Say / do | Shows |
|---|---|---|---|
| 0:00 to 0:10 | Title | "Wysp is a tutor for any software. One Core, one Panel, one adapter per app." | Mascot on the empty chat |
| 0:10 to 0:45 | Blender, pumpkin selected | Hold Space: "What is this object and how is it built?" | Board builds: object, modifier stack, observed nodes with the eye, captions follow the voice |
| 0:45 to 1:00 | Interrupt | While it speaks, press Esc or say "wait, what does Subdivision do?" | Narration stops at once, short answer, labelled "for example" where illustrative |
| 1:00 to 1:25 | Guided change | "Add a Subdivision for me." | Permission dialog: reversible, preview, Approve. Click Approve. Result checked: "Verified in the application" |
| 1:25 to 1:35 | Undo (optional) | Menu > Undo Wysp's last change | Shows reversibility; skip if short on time |
| 1:35 to 1:45 | Switch | Menu > Looking at > IntelliJ | Same Panel, different app |
| 1:45 to 2:15 | IntelliJ explore and explain | "Explore this project", then caret in a function: "Explain this function." | Exploration card, board with the structure, highlight in the IDE |
| 2:15 to 2:40 | Rename refactoring | "Guide me to rename it." Do the rename yourself with the IDE's refactoring | Pointer at the IDE control, exercise card, "Verified in the application" |
| 2:40 to 2:50 | Close | "Two apps, same Core and Panel. Only the adapter and the profile changed." | Side-by-side of the two `apps/` folders (optional) |

Keep one retake budget per scene. If the model is slow, record the Blender part with `-Llm scripted -Scenario apps\blender-tutor\demo\scenario.yaml` and say so in the notes.

## 4. Checklist before recording

- [ ] `scripts\demo_up.ps1` ran; `/api/health` lists the Blender and IntelliJ adapters.
- [ ] Panel dot is lilac (connected), no red "Cannot reach the Wysp Core" banner.
- [ ] Voice on (menu > Voice), one test sentence spoken aloud and heard; one spoken question understood.
- [ ] Microphone level fine, no echo (use a headset if the speakers feed the mic).
- [ ] Blender scene reset (`pumpkin.blend` reopened, no leftover Subdivision); IntelliJ sample project reset (`git checkout` of the sample, function not renamed).
- [ ] Session logs set to what you want to show (menu > Logs); no token or API key visible on screen (`.env`, `~/.wysp/token`).
- [ ] Notifications off, no other windows, clock not showing private data, scale 100 %.
- [ ] A dry run of the whole script under 3 minutes.

## 5. When something fails

| Symptom | Fix |
|---|---|
| Panel banner "Cannot reach the Wysp Core" | `scripts\demo_up.ps1`; check `$env:TEMP\wysp_core.err`. Port busy: `scripts\dev_down.ps1` then start again. |
| Panel connected but Wysp never answers | The tutor loop window is closed or stuck: rerun `scripts\kiro_tutor.ps1`. Otherwise restart the Core with `-Llm scripted` and a scenario. |
| An app is missing from "Looking at" | Reconnect the adapter (Blender: re-enable the extension; IntelliJ: Tools > Wysp > Connect; Chrome: reload the page). Token in `~/.wysp/token` must match. |
| No sound | Menu > Voice on; check the Windows output device; the Panel falls back to browser voices when `/api/tts` is unavailable. |
| Mic does nothing | Allow the microphone for `127.0.0.1:8765` in Chrome; hold Space with the Panel focused, or the mic button. Typing always works. |
| Permission dialog hides the app | It is modal by design: answer it (Esc denies). It denies itself after its timeout. |
| Board stale or wrong | The application disconnected; reconnect the adapter, the board refreshes. |
| Model too slow or rate limited | Switch to the scripted scenario (section 2), or another provider key in `.env`. |
| Panel shows an old version | Rebuild: `cd panel; npm.cmd run build` (the Core serves `panel/dist` live), hard refresh. |
