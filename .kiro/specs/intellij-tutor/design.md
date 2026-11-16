# Design Document: IntelliJ Tutor

## Overview

```
apps/intellij-tutor/
  plugin/                         Gradle project (Kotlin 2.4, IntelliJ Platform Gradle Plugin 2.20, Gradle 9.9)
    build.gradle.kts              targets the local IntelliJ IDEA 2026.2 install (no SDK download)
    src/main/resources/META-INF/plugin.xml
    src/main/kotlin/dev/wysp/intellij/
      json/Json.kt                tiny JSON codec (no third-party dependency)
      rpc/RpcClient.kt            JSON-RPC 2.0 over java.net.http.WebSocket, hello, heartbeat, reconnect
      WyspService.kt              application service: connection, settings, request routing, threading
      Refs.kt                     intellij:// refs <-> project elements
      Observe.kt                  entities (project, modules, dirs, files, symbols, problems, run configs), context
      Privacy.kt                  sensitive-file rules, content bounds
      actions/                    one file per action: OpenFile, GoToSymbol, ShowToolWindow, RenameSymbol
      Highlight.kt                editor range markers, tool window activation, Swing component search + balloon
      Events.kt                   editor/caret/document listeners, debounce, origin tagging
      ui/WyspToolWindowFactory.kt JCEF browser showing the Panel (ui/PanelBrowser.kt; JCEF is the optional bundled
                                  plugin com.intellij.modules.jcef, a link to the Panel otherwise)
      ui/WyspSettings.kt          settings page (Core URL, token file), connect actions
    src/test/kotlin/              unit tests (pure) and platform tests (BasePlatformTestCase)
  profile/                        profile.yaml, concepts.yaml
  demo/sample-project/            a small Kotlin/Java project for demos and end-to-end checks
  contract.fixture.yaml
```

The Core and the Panel do not change. The plugin is one more adapter speaking the contract, and the tool window
is one more Panel client (the same React Panel, embedded).

## Threading

```
WebSocket thread (java.net.http)          IDE threads
  text frame ─▶ RpcClient.onRequest ─▶ WyspService.handle(method, params)
     observe / get_context ─▶ EDT: capture editor state ─▶ ReadAction.nonBlocking (pooled) ─▶ reply
     execute    ─▶ 1. resolve targets: ReadAction.nonBlocking (PSI, structure view: slow operations,
                      forbidden on the EDT)
                   2. change the IDE: invokeLater on the EDT (refactoring, editors)
                   3. refs of what changed: ReadAction.nonBlocking ─▶ reply
     highlight  ─▶ resolve in a read action, then show on the EDT (any modality) ─▶ reply
     undo       ─▶ EDT ─▶ reply
  heartbeat every 15 s (scheduled executor, no IDE access)
```

Expected failures (unknown target, invalid name) complete the reply future inside the read action: a rejected
platform promise would be logged as an IDE error blamed on the plugin.

Budgets: reads (observe, context, target resolution) answer `-32017 BUSY` after 4 s (the IDE is syncing or
indexing). EDT work that cannot *start* within 4 s (a modal dialog, a long task) is cancelled before it starts and
answered BUSY, so an action never runs after the Core was told it failed; once started it runs to completion.

Replies are sent from whichever thread finishes the work (`WebSocket.sendText` is serialised by the client).

## Refs

| Ref | Element |
|---|---|
| `intellij://project/<name>` | the project |
| `intellij://module/<name>` | a module |
| `intellij://dir/<path>` | a directory, path relative to the project base, `/` separators, percent-encoded parts |
| `intellij://file/<path>` | a file |
| `intellij://file/<path>#<Qualified.Name>` | a symbol (class, function, field) in that file |
| `intellij://problem/<path>:<line>:<n>` | the n-th problem on that line |
| `intellij://run/<name>` | a run configuration |
| `intellij://ui/toolwindow/<id>` | a tool window (`Project`, `Run`, `Debug`, `Problems View`, `Git`/`Commit`, `Terminal`...) |
| `intellij://ui/label/<text>` | a visible component with that text or accessible name |

## Observation

- Order: project, modules, top-level directories, the current file's directory, open files, symbols of open files,
  problems of the current file, run configurations. Limit 500 entities; `truncated` and `counts` otherwise.
- Props: file `{language, lines, open, modified, sensitive}`; symbol `{type: class|interface|function|field,
  line, end_line, signature}` (signature bounded to 120 characters); problem `{severity, message, line}`;
  run_config `{type}`; module `{type}`.
- Symbols come from the generic PSI structure view (`StructureViewBuilder`), so any language with a structure
  view works (Java, Kotlin, Python, JS/TS...), not only one language.
- Problems come from the highlighting already computed for open files (`DaemonCodeAnalyzerImpl`
  highlights with severity WARNING or more); no extra analysis is triggered.
- Context facts: project, current file, language, caret line/column, `selection` (at most 1500 characters),
  `code_at_caret` (text of the innermost function or class at the caret, at most 3000 characters), problem count,
  `dumb_mode`. Nothing from sensitive files.

## Actions

| id | risk | what | postcondition |
|---|---|---|---|
| `open_file` | ui_state | open a file, optionally at a line | the file is in `focus` |
| `go_to_symbol` | ui_state | open the symbol's file and put the caret on it | the symbol is in `focus` |
| `show_tool_window` | ui_state | open and focus a tool window | none (UI) |
| `rename_symbol` | reversible | IDE rename refactoring (updates usages) in one command | a symbol with the new name exists in the file |
| `read_code` | read_only | numbered lines `from..to` of a project file (≤150 lines, ≤8,000 chars) | none (read) |
| `search_code` | read_only | text search in project files, ≤50 matches with line numbers | none (read) |
| `find_usages` | read_only | usages of a symbol (file, line, line text), ≤50 | none (read) |
| `list_files` | read_only | children of a directory (names, kinds, line counts) | none (read) |
| `replace_lines` | reversible | replace lines `from..to` (checked against `old_text`) with `new_text`; empty `new_text` deletes | the file is observed; the adapter reads the text back |
| `insert_lines` | reversible | insert `new_text` after line `after_line` (0 = top) | the file is observed; the adapter reads the text back |
| `create_file` | reversible | new project file with `text`; undo deletes it | the file is observed |
| `reformat_code` | reversible | the IDE's code style on a file or a line range | the file is observed |
| `optimize_imports` | reversible | the IDE's import optimization on a file | the file is observed |

Text edits share one helper: one `WriteCommandAction` (named "Wysp: …", so Ctrl+Z works), commit of the document,
read-back of the edited range, and an undo closure that puts the previous text back only if the range still holds
what Wysp wrote (otherwise `UNDO_UNAVAILABLE`, nothing is overwritten). The Core asks every reversible action for a
dry-run preview (`{file, lines, diff}`), and the Panel shows `diff` as text. Read-only results travel in `message`.

Undo of `rename_symbol`: the token maps to the document(s) touched; undo runs `UndoManager.undo` for the
editor of that file while the last command is still ours, otherwise renames back with the same refactoring.

## Highlight

- Code refs: open the file in an editor, scroll to the range, add a `RangeHighlighter` with a Wysp-coloured
  background and border for the duration, then remove it.
- `intellij://ui/toolwindow/<id>`: show the tool window (UI state only) and put a balloon on its stripe button.
- `intellij://ui/label/<text>`: breadth-first search of the frame's Swing tree for showing components whose text
  (`AbstractButton.text`, `JLabel.text`, action presentation text) or accessible name matches (same matching
  rules as the Blender label matcher: exact, truncated, case-insensitive); point at the first match with a
  balloon. No screenshots are needed: positions come from Swing itself (native integration).

## Events

- `FileEditorManagerListener.selectionChanged` and a caret listener (throttled to 300 ms) send selection changes.
- `DocumentListener` / `BulkFileListener` mark the state dirty; a 300 ms debounce sends `event.state_changed`.
- Origin: the SDK rule, in Kotlin: changes during a Wysp action and within 600 ms after it are tagged `wysp`.
- Caret moves caused by Wysp's own navigation are not sent as `selection_changed` (the contract's selection event
  has no origin, and the Core treats selection changes as the user's). The Core also attributes every event in a
  short window after its own actions to Wysp (core-orchestrator).
- IDE settings (`.idea`), VCS data and build output are neither observed nor reported.

## Correctness Properties

**IJ-P1: Codec round trip.** *For any* JSON value built from objects, arrays, strings (any Unicode), numbers,
booleans and null, `parse(write(v)) == v`. **Validates: Requirement 10.1**

**IJ-P2: Refs round trip.** *For any* relative path and qualified name, parsing a built ref gives them back.
**Validates: Requirement 3.1**

**IJ-P3: Sensitive files never leak.** *For any* file name matching the sensitive patterns, the context never
contains its text. **Validates: Requirement 4.4**

**IJ-P4: Rename is undoable.** Renaming a symbol and undoing restores the original file text.
**Validates: Requirement 5.2**

## Error Handling

- Unknown ref: `-32012 TARGET_NOT_FOUND`. Invalid params: `-32602`. Refactoring conflicts: `-32013
  PRECONDITION_FAILED` with the conflict descriptions. Dumb mode for rename: `-32017 BUSY`.

## Testing Strategy

- Unit tests (JUnit 4, which the IntelliJ test framework runs on; no IDE): codec (IJ-P1, property-style random values), refs (IJ-P2), privacy (IJ-P3),
  label matching.
- Platform tests (`BasePlatformTestCase`, light fixture): observation of a small fixture, `rename_symbol` and its
  undo (IJ-P4), context bounds.
- End-to-end: `runIde` sandbox with `demo/sample-project` (`-PopenProject`; first-run dialogs disabled), connected
  to `tests/live_harness.py` (contract fixture, every reply validated with the Core's contract models) and to a
  test Core with the ScriptedLLM (`demo/scenario.yaml`); `tests/window_shot.ps1` captures only the IDE window.
