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

No action runs code, run configurations, scripts or arbitrary IDE action ids. Ctrl+Z also undoes Wysp's rename, like any refactoring.

## Pointing at the IDE

The highlight tool (and narration cues) accept any ref above, plus:

- `intellij://ui/toolwindow/<id>` opens a tool window and frames it;
- `intellij://ui/label/<text>` finds a visible button, tab, menu or label by its text or accessible name and frames it with a balloon. Positions come from Swing itself (native integration, no screenshots). When the label is not visible, the error lists the labels that are, so the tutor can adapt.

## Privacy

- Wysp reads the project structure, the open files' code structure and the IDE's problems. **Code text** is sent only for your selection (at most 1,500 characters) and the function or class at the caret (at most 3,000 characters), to the local Core, which forwards it to the LLM provider you configured (for example Groq). Use `--llm scripted` or a local provider (Ollama) to keep everything on your machine.
- Nothing is ever read from sensitive files: `.env*`, keys and certificates (`*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.jks`, `*.keystore`...), `id_rsa*`, files or folders named like `*credential*` or `*secret*`, `.netrc`, `.npmrc`, `.pypirc`, `.pgpass`.
- The rule goes by file name: a secret pasted into an ordinary source file is code like any other, so keep secrets out of code (environment variables or a git-ignored `.env`).
- The plugin only connects to a Core on this machine (`127.0.0.1` or `localhost`; any other host is refused, since the pairing token travels in the handshake), never stores the token, and never logs code.

## Development

| Goal | Command (in `apps/intellij-tutor/plugin`) |
|---|---|
| Build the ZIP | `.\gradlew.bat buildPlugin` |
| Unit and platform tests (23, incl. IJ-P1..P4) | `.\gradlew.bat test` |
| Sandbox IDE with the demo project | `.\gradlew.bat runIde -PopenProject=<repo>\apps\intellij-tutor\demo\sample-project` |

The sandbox keeps its own settings in `.intellijPlatform/sandbox/.../config_runIde`. To check the adapter against the contract in a real IDE, point the sandbox's Wysp settings at port 8799 and run the live harness (it validates every reply with the Core's own contract models, runs `contract.fixture.yaml`, undoes what it changed):

```powershell
uv run --no-sync python apps/intellij-tutor/tests/live_harness.py --port 8799 --token-file <token file>
```

`tests/probe.py` sends single requests to a connected plugin, and `tests/window_shot.ps1` captures only the IDE's window.

Threading: observation and target resolution run in non-blocking read actions on pooled threads; changes and UI (refactorings, editors, balloons) run on the EDT; the WebSocket uses `java.net.http` with no third-party dependency.
