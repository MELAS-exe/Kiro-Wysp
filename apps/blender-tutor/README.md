# Blender tutor

The first application built on Wysp: a tutor that sees your Blender scene, explains objects and their modifier stack on an interactive board, guides you step by step, and verifies in Blender what you did. Integration level: **native** (Blender 5.2 LTS Python API).

> Status: prototype. Spec: `.kiro/specs/blender-tutor/`. Licence of the extension: GPL-3.0-or-later.

## Quick start (development)

1. Start the Core: `uv run wysp serve` (see the root README). Open http://127.0.0.1:8765.
2. Build the demo scene once: `blender -b --python apps/blender-tutor/demo/build_scene.py`.
3. Connect Blender:
   - headless (tests, contract kit): `scripts/run_blender_headless.ps1`, or the kit does it for you;
   - with the interface: build and install the extension (`uv run python scripts/build_blender_extension.py`), then open the **Wysp** tab in the 3D viewport sidebar and click **Connect**.

## The Wysp tab (what the panel looks like)

The sidebar tab is a native Blender panel that mirrors the browser Panel: chat first, one slim top row, nothing else. It only renders `UiState` (`adapter/ui_state.py`) and sends UI-protocol messages; there is no tutoring logic in it.

| Area | What it shows |
|---|---|
| Top row | The Wysp mascot, a status (Ready, Thinking, Acting, Speaking, Offline) with an icon, a Chat / Diagram switch (only when the board has nodes) and a `⋮` menu. No title bar. |
| `⋮` menu | Which application Wysp looks at (several can be connected), Logs level (off, basic, full, synced with the Core), Voice on/off, Undo Wysp's last change, open the diagram editor, Connect / Disconnect. |
| Chat | Your messages in boxes, Wysp's sentences as plain text (they appear as they are spoken), checks as small dim lines, a dim "Thinking…" line while busy. **Stop** shows while Wysp works, **Continue** only when something was cancelled. Composer at the bottom: text field, mic (hold Alt+Space), send. Empty chat: the mascot and "Ask about your scene". |
| Approval | A card with the risk, the action, the reason and a preview, then Deny / Approve (and "Allow for this lesson" for reversible actions). The card replaces the conversation until you answer. A banner also appears in the viewport. |
| Diagram | The board as a compact list with the same provenance language as the node tree: observed (eye), likely, example (dim). Show highlights the element in Blender, `?` asks why. The full node view opens with **Open in editor**. |

Limits of a native panel: Blender draws sidebar panels with your theme, so brand colour only comes from the mascot icon, the viewport banner (ink, lilac, lavender) and the board nodes. Scripts cannot scroll a sidebar, so the chat shows the newest messages that fit ("N earlier messages" above) and keeps the composer in view. Messages of unknown type from the Core (for example `explore.state`) are ignored.

Screenshots: `docs/img/blender-panel-*.png`. Regenerate them (separate Blender with its own temporary profile, no Core, no network):

```powershell
apps\blender-tutor\tests\shoot_panel.ps1 -Out $env:TEMP\wysp-shots
uv run --with pillow --no-project python apps\blender-tutor\tests\crop_shots.py $env:TEMP\wysp-shots docs\img --wide menu
```

Icons: `adapter/icons/mark-color-64.png` (top row) and `mark-color-256.png` (empty chat), copies of `docs/brand/`. They are loaded with `bpy.utils.previews` in `adapter/ui_icons.py` (registered and released with the add-on, built-in icon as fallback) and packaged automatically by the extension build.

## Actions

Every action is declared in `adapter/actions/<id>.py`. The LLM can only *propose* them; the Core asks you before running anything that changes the scene, then verifies the result.

| id | risk | reversible | description |
|---|---|---|---|
| `select_object` | ui_state | no (UI only) | Select an object and make it active |
| `show_properties_tab` | ui_state | no (UI only) | Switch the Properties editor to MODIFIER, MATERIAL, OBJECT or DATA (needs a window) |
| `set_object_transform` | reversible | yes | Set an object's location, rotation (degrees) or scale to exact values; verified on the observation |
| `add_modifier` | reversible | yes | Add a modifier (any type of the running Blender) to an object |
| `set_modifier_property` | reversible | yes | Set one scalar property of a modifier (generic RNA, no per-type code) |
| `move_modifier` | reversible | yes | Reorder a modifier in the stack (evaluation order) |
| `remove_modifier` | reversible | yes | Delete a modifier; undo recreates it with its settings and position |
| `apply_modifier` | irreversible | no | Bake a modifier into the mesh; needs an explicit click and shows a preview |

## Entities

`scene`, `collection`, `object`, `modifier`, `material`, with refs such as `blender://object/Pumpkin` and `blender://object/Pumpkin/modifier/Subdivision` (names are percent-encoded).

## Safety

- Blender's API is only used on the main thread: the network thread only queues requests, a timer pump runs them.
- Every Wysp change pushes a native undo step, so Ctrl+Z also works.
- No action runs arbitrary Python: the catalog is closed and declarative.

## Pointing at the interface

`adapter.highlight` also accepts interface refs (see `adapter/ui_targets.py`):

| Ref | What is drawn |
|---|---|
| `blender://ui/area/<VIEW_3D\|OUTLINER\|PROPERTIES\|TIMELINE>` | a glowing frame around the editor and a label |
| `blender://ui/region/VIEW_3D/<HEADER\|TOOLBAR\|SIDEBAR\|GIZMO>` | a frame around that part of the viewport and a label |
| `blender://ui/properties/tab/<TAB>` | opens the tab, frames the tab column and marks the tab |

| `blender://ui/label/<EDITOR>/<text>` | frames the button, menu or field showing that text (hybrid, below) |

**Hybrid native + visual.** Blender's Python API knows where each editor and region is, but not where its
buttons are (checked on 5.2: regions and areas have rectangles, panels and layouts have none). So for labels the
extension screenshots that one editor (`screen.screenshot_area`), sends the PNG to the local Core's
`POST /api/ocr` (Windows' built-in OCR, offline), and frames the words that match: exact text, Blender's
truncated labels (`Level…` for Levels), RNA identifiers (`segments` → "Segments"), and the right word among
menus that OCR reads as one line ("Add Object Global"). The whole round trip takes about 100 to 150 ms. For
Properties tabs, which are icons, the same screenshot is scanned for the icons of the tab column, so the marker
follows any UI scale, DPI or theme (checked at Resolution Scale 0.85, 1.0 and 1.25); a fitted estimate is used
only if that fails. If a label is not visible, the tool tells the tutor which labels are, or that the editor is
too narrow to read; if a tab is scrolled out of the column, it says so.

Privacy: only the editor being pointed at is captured, only the local Core receives it, nothing is stored (the
file is deleted at once; `WYSP_DEBUG_SHOTS=<dir>` keeps copies for debugging) and the image is never logged.
Icons without text, the top bar and the status bar cannot be targeted. Guided steps carry these refs, so
starting a guide walks through each step's target in turn (object, tab, then the button).

## Highlights (contract 1.1.0)

The manifest declares `contract_version` 1.1.0, so the Core uses persistent highlights.

- `adapter.highlight` with `duration_ms: 0` stays until it is cleared, replaced, the Core connection drops or the
  add-on is disconnected. A positive duration still expires by itself. A new highlight replaces the previous one.
- `adapter.clear_highlight` returns `{"cleared": true}` when something was shown and `{"cleared": false}` when not
  (never an error).
- **Object highlights** (`blender://object/...`, including modifier refs, which outline their object) report
  `event.highlight_dismissed {ref, reason: "user"}` and disappear when the user newly selects or activates the
  highlighted object. Selection changes made by Wysp, and changes in the first 1.5 s after the highlight appears,
  are ignored.
- **Interface highlights** (`blender://ui/...`, including labels) are **not** dismissed by a click. Blender's Python
  API has no cheap click detection for them (it would need a modal operator, which this adapter does not add).
  They stay until cleared, replaced or disconnected; the Core also expires them after 10 minutes.

## Inside Blender: chat and board

The extension opens a second connection to the Core's UI protocol (`/ws/ui`), so Blender is just another
Panel: same messages as the browser Panel, no tutoring logic. The **Wysp** sidebar tab shows the conversation,
permission prompts (always a click; irreversible actions show their preview), clarification choices and guided
steps. **Open Board** shows the board as a node tree (`.Wysp Board`) in a new window; observed nodes are teal,
inferred ones say "likely", examples are grey. Clicking a node highlights it in the scene; **Why?** asks Wysp.
The board tree is a view: it is rebuilt from the Core's board and removed before the file is saved.

Wysp speaks inside Blender: the Core synthesises each segment with the voices installed in Windows
(`POST /api/tts`, offline, no key) and the extension plays it with Blender's `aud` module; cues fire in step
with the audio. Without a voice on the Core, narration falls back to captions paced at reading speed. If the
browser Panel is open with its voice on, turn one of them off ("Speak in Blender" in the extension
preferences) to avoid hearing Wysp twice.

The chat puts what needs an answer first: approval requests (Approve / Deny / Allow for this lesson), then the
message box, the guided steps, and the conversation newest first (Blender panels cannot be scrolled by a
script). While an approval is pending, the sidebar is opened and a banner at the bottom of the viewport
points to the Wysp tab.

## Speaking to Wysp

Hold **Alt+Space** over the 3D Viewport (or the board) and speak, then release; or click **Talk**, speak, and
click the red button. Talking stops Wysp's narration. While an approval is pending, "yes" / "go ahead" approves and
"no" denies (irreversible actions still need a click). The shortcut can be changed in Blender's Keymap preferences
("wysp.talk").

Blender's Python API cannot capture audio, so the local Core records the default microphone (`POST /api/listen`,
with the pairing token), only while you hold the key, at most 30 s, and transcribes the clip with Whisper on
Groq by default (about 0.5 s). **The audio clip is sent to Groq**, like the conversation text when Groq is the
LLM. Silence is detected locally and never sent; audio is never stored or logged. Turn it off with
`WYSP_STT_PROVIDER=none` or the "Talk to Wysp in Blender" preference.

## Logs

The extension writes `~/.wysp/logs/blender-<date>-<pid>.jsonl`: per-request main-thread queue wait and run
time, slow ticks (> 50 ms), observation build time, and `wysp.*` log lines. `uv run wysp logs summary` merges
it with the Core log of the same period. The level is the extension preference "Blender-side logs" or
`WYSP_LOG`. Request parameters and typed values are never recorded.

## Developer checks with a window

```powershell
# Highlight screenshots in a separate Blender (does not touch a running one):
blender --factory-startup --python-use-system-env apps\blender-tutor\demo\pumpkin.blend --python apps\blender-tutor\tests\gui_shot.py -- OUTDIR blender://ui/properties/tab/MODIFIER
# Chat + board against a Core on another port (WYSP_HOME keeps its token and logs apart):
blender --factory-startup --python-use-system-env apps\blender-tutor\demo\pumpkin.blend --python apps\blender-tutor\tests\gui_panel_check.py -- OUTDIR ws://127.0.0.1:8799/ws/adapter TOKEN_FILE "Explain the pumpkin's modifiers"
```
