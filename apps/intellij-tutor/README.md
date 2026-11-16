# IntelliJ tutor

The second application built on Wysp: a tutor inside IntelliJ IDEA that sees your project the way the IDE does (modules, directories, files, the structure of your code, the problems the IDE found), explains the code under your caret on the board, points at the exact IDE control to use, and guides refactorings that it verifies in your code. Integration level: **native** (IntelliJ Platform API). It replaces the planned web tutor as application 2 (decision of 2026-11-11).

It uses the same Core, the same Panel and the same contract as the Blender tutor: only this folder (the plugin and the profile) is IntelliJ-specific.

> Status: prototype. Spec: `.kiro/specs/intellij-tutor/`.

## Install

Requirements: IntelliJ IDEA 2026.2 (build 262 or later), a running Wysp Core (see the root README).

1. Build the plugin (uses the IDE installed on this machine, no SDK download):
   ```powershell
   cd apps\intellij-tutor\plugin
   $env:JAVA_HOME = "$env:USERPROFILE\.jdks\ms-21.0.12"   # any JDK 17+ to run Gradle
   .\gradlew.bat buildPlugin
   ```
   The ZIP is `build\distributions\wysp-intellij-0.1.0.zip`.
2. In IntelliJ IDEA: **Settings > Plugins > ⚙ > Install Plugin from Disk…**, pick the ZIP, restart.
3. Start the Core (`uv run wysp serve`). The plugin connects by itself when a project opens (**Tools > Wysp > Connect to Wysp Core** otherwise). It reads the pairing token from `~/.wysp/token`.
4. Open the **Wysp** tool window (right side bar): it shows the Panel (chat, board, voice, approvals). If the IDE cannot embed a browser, it offers a link to open the Panel in your browser.

Settings: **Settings > Tools > Wysp Tutor** (Core URL, token file, automatic connection).

Try it on the demo project `apps/intellij-tutor/demo/sample-project` (a small Gradle Java app), offline with the scripted demo:
`uv run wysp serve --llm scripted --scenario apps/intellij-tutor/demo/scenario.yaml`, then ask "explain this function", "rename it to a clearer name", "do it for me".

## What the tutor sees

| Entity kind | Ref | Props |
|---|---|---|
| `project` | `intellij://project/<name>` | modules, dumb_mode |
| `module` | `intellij://module/<name>` | type |
| `directory` | `intellij://dir/<path>` | |
| `file` | `intellij://file/<path>` | language, lines, open, modified, sensitive |
| `symbol` | `intellij://file/<path>#<Class.member>` | type (class, interface, function, field), line, end_line, signature |
| `problem` | `intellij://problem/<path>:<line>:<n>` | severity, message, line |
| `run_config` | `intellij://run/<name>` | type, selected |

Paths are relative to the project root. Symbols come from the IDE's generic structure view, so every language with a Structure tool window works (Java, Kotlin, Python, JavaScript...). Problems are the warnings and errors the IDE already computed for open files; nothing extra is analysed. IDE settings (`.idea`), VCS data and build output are never observed.

## Actions

Every action is one file in `plugin/src/main/kotlin/dev/wysp/intellij/actions/`. The LLM can only *propose* them; the Core asks you before running anything that changes your code, then verifies the result.

| id | risk | reversible | description |
|---|---|---|---|
| `open_file` | ui_state | no (UI only) | Open a project file in the editor, optionally at a line |
| `go_to_symbol` | ui_state | no (UI only) | Open a symbol's file with the caret on its name |
| `show_tool_window` | ui_state | no (UI only) | Open and focus a tool window (Project, Structure, Problems View, Run, Terminal...) |
| `rename_symbol` | reversible | yes | The IDE's Rename refactoring: declaration and every usage. Conflicts are reported, never forced. Undo renames it back |
| `read_code` | read_only | no (reads) | Numbered lines of a project file, at most 150 lines or 8,000 characters per call |
| `search_code` | read_only | no (reads) | Plain-text search in the project's files, at most 50 matches (`path:line: text`) |
| `find_usages` | read_only | no (reads) | Where a symbol is used, from the IDE's reference search, at most 50 usages |
| `list_files` | read_only | no (reads) | The entries of a project directory (names only) |
| `replace_lines` | reversible | yes | Replace or delete whole lines. `old_text` must match the current lines, or nothing changes |
| `insert_lines` | reversible | yes | Insert lines after a line (0 = top). `anchor_text` must match that line |
| `create_file` | reversible | yes | A new file in the project (never overwrites). Undo deletes it while it is untouched |
| `reformat_code` | reversible | yes | The project's code style on a file or a line range |
| `optimize_imports` | reversible | yes | The IDE's import optimizer on a file |

No action runs code, run configurations, scripts or arbitrary IDE action ids. Each IDE tool is one specific platform API call (the code style manager, the import optimizer, the reference search).

**Writing code.**
- Every change is `reversible`. The approval dialog shows it as a diff before anything happens.
- Each change runs as one IDE command named "Wysp: …", so Ctrl+Z undoes it too.
- The result is read back. If the editor does not hold exactly the requested text, the file is restored and the action fails.
- An edit only applies when `old_text` (or `anchor_text`) still matches the file, so a stale edit changes nothing.
- Wysp's undo never overwrites newer work. If you have typed in the changed lines since, it refuses and you use Ctrl+Z.
- Sensitive files, read-only files, IDE settings, VCS data and build output are refused, for reading and for writing.
- After `create_file` in a Git project, the IDE asks whether to add the file to Git. That question is yours to answer, and other actions wait until you do.

**Reading code.** The four read tools run without a dialog, like pointing, but every call is in the audit log with its parameters. They never read sensitive files, IDE settings or build output (decision of 2026-11-12, Requirement 4.5 of the spec).

## Survey when the tutor starts

When the IDE connects, the Core first looks at the whole project, then answers. The `full` observation adds the project tree (directories and file names with language and size, from the VFS only, time-boxed to 200 ms and 2,000 nodes) after the open files, their symbols and their problems. Sensitive files, IDE settings, VCS data and build output are skipped; no file content is read for the tree. When indexing ends, the plugin sends `event.state_changed` so a survey taken during indexing is redone. Limits: at most 500 entities per observation (`truncated` and `counts` say what did not fit), and problems come only from open files. Turn the survey off with `wysp serve --no-survey` or `WYSP_SURVEY=off`.

## Voice

The IDE's embedded browser has no speech recognition and often no voices, so the Panel uses the Core for both:

- **Talking to Wysp:** hold the mic button (or `Space` when the Panel has focus). The Core records the default microphone only while you hold, then transcribes the clip (`WYSP_STT_PROVIDER`, default Whisper on Groq when `GROQ_API_KEY` is set: the audio clip leaves your machine, set `WYSP_STT_PROVIDER=none` to turn it off). Silence is never sent. Say "yes" or "no" to answer an approval (irreversible actions still need a click).
- **Wysp talking:** the voices installed in Windows (`WYSP_TTS_PROVIDER=auto`, offline, nothing leaves your machine; `WYSP_TTS_VOICE=Zira` picks one). The Panel uses the browser's own voices when it has some, otherwise the Core's. The **Voice** switch is in the Panel's menu.
- **How the Panel is allowed to use the microphone:** the Core only starts recording for a request carrying the pairing token. The plugin passes the token to its own embedded Panel in the URL fragment (`#wysp_token=...`): it is not sent to any server, not logged, kept in memory by the Panel and removed from the address at once. It is never stored.

## Exploring the project (map, then study)

Because a tutor that skims a few files and then explains the whole architecture is guessing, Wysp asks first: the Panel offers **"Explore this project?"** and nothing is read until you press **Start**.

1. **Map (no model involved).** The Core walks the project folder by folder and keeps, for every source file, its classes and method signatures, its size and the project files it imports (Java, Kotlin and Python imports). It holds names and signatures, never code bodies. While the IDE is still indexing it waits. The tutor gets a bounded overview (biggest packages, most depended-on files, entry points) and can look inside any folder or file with its `code_map` tool.
2. **Study.** The Core picks up to 30 files (entry points, the most imported files, README and docs, build and config files, at least one per package, tests skipped) and the tutor agent gets them through `study_read`, about 12 files per call (the start of each file, numbered lines; three calls for a full plan), then writes study notes per theme. The Core refuses to let the study end until at least 80% of the plan was read, so it cannot stop after a few files. The Core records which files were really read, so the tutor can say what it read and what it did not. This is where your Kiro credits are spent: about 20 to 30 file reads.

Stop at any time from the card. Decline with "Not now" (the menu has "Explore this project" if you change your mind).

What is stored: the study notes (the tutor's own short summaries of your code) are kept on this machine in `~/.wysp/projects/`, one file per project, so the next session can reuse them (marked as possibly out of date). Delete that folder to forget them. As with the other read tools, the code the tutor reads goes to the model provider you configured. Sensitive files are never mapped or read.

Profile: the `explore` section of `profile/profile.yaml` says which kinds are folders, files and symbols and which file names deserve reading first.

## Pointing at the IDE

What the tutor points at **stays highlighted** until it is done (contract 1.1). It comes down when: you click, edit or move into it (a click on the highlighted button, tool window or label; a click, caret move or edit inside the highlighted code); the tutor highlights something else or clears it (it does when you are done or the conversation moves on); a guided step is verified; the IDE disconnects from the Core; or after 10 minutes. Brief pointers (a sentence's cue, a tour of steps) fade by themselves, and the last step of a tour stays.

The highlight tool (and narration cues) accept any ref above, plus:

- `intellij://lines/<path>:<from>-<to>` (or `:<n>` for one line, 1-based) tints those whole lines in the editor and scrolls to them. Narration cues use it to follow an explanation line by line. The code facts the tutor reads carry the same line numbers (`  12| code`), and only cover the function or class at the caret and the selection;
- `intellij://ui/toolwindow/<id>` opens a tool window and frames it;
- `intellij://ui/label/<text>` finds a visible button, tab, menu or label by its text or accessible name and frames it with a balloon. Positions come from Swing itself (native integration, no screenshots). When the label is not visible, the error lists the labels that are, so the tutor can adapt.

## Privacy

- Wysp reads the project structure, the open files' code structure and the IDE's problems. **Code text** is sent for your selection (at most 1,500 characters), the function or class at the caret (at most 3,000 characters), and the line ranges, searches and usages the tutor asks for with the read tools (at most 8,000 characters per call). It goes to the local Core, which forwards it to the LLM provider you configured (for example Groq). Use `--llm scripted` or a local provider (Ollama) to keep everything on your machine.
- Nothing is ever read from sensitive files: `.env*`, keys and certificates (`*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.jks`, `*.keystore`...), `id_rsa*`, files or folders named like `*credential*` or `*secret*`, `.netrc`, `.npmrc`, `.pypirc`, `.pgpass`.
- The rule goes by file name: a secret pasted into an ordinary source file is code like any other, so keep secrets out of code (environment variables or a git-ignored `.env`).
- The plugin only connects to a Core on this machine (`127.0.0.1` or `localhost`; any other host is refused, since the pairing token travels in the handshake), never stores the token, and never logs code.

## Development

| Goal | Command (in `apps/intellij-tutor/plugin`) |
|---|---|
| Build the ZIP | `.\gradlew.bat buildPlugin` |
| Unit and platform tests (37, incl. IJ-P1..P5) | `.\gradlew.bat test` |
| Sandbox IDE with the demo project | `.\gradlew.bat runIde -PopenProject=<repo>\apps\intellij-tutor\demo\sample-project` |

The sandbox keeps its own settings in `.intellijPlatform/sandbox/.../config_runIde`. To check the adapter against the contract in a real IDE, point the sandbox's Wysp settings at port 8799 and run the live harness (it validates every reply with the Core's own contract models, runs `contract.fixture.yaml`, undoes what it changed):

```powershell
uv run --no-sync python apps/intellij-tutor/tests/live_harness.py --port 8799 --token-file <token file>
```

`tests/probe.py` sends single requests to a connected plugin, and `tests/window_shot.ps1` captures only the IDE's window.

Threading: observation and target resolution run in non-blocking read actions on pooled threads; changes and UI (refactorings, editors, balloons) run on the EDT; the WebSocket uses `java.net.http` with no third-party dependency.
