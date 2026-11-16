# Requirements Document: IntelliJ Tutor

Lead: Person C (plugin). Person B owns the IntelliJ profile (concepts, lessons). Reviewer: Person A (contract).

## Introduction

The IntelliJ tutor is the second application built on Wysp (decision of 2026-11-11: it replaces the web tutor as
application 2). A plugin for IntelliJ IDEA 2026.2 implements the adapter contract at the **native** integration
level, through the IntelliJ Platform API: the project model, PSI (the IDE's parsed view of code), editors,
inspections and the Swing component tree of the IDE window. The tutor helps a student with anything about the
IDE and the code: exploring a project, understanding a piece of code, learning IDE features (navigation, run and
debug, refactoring, inspections, version control), with **exactly the same Core and Panel** as the Blender tutor.

## Glossary

- **PSI**: Program Structure Interface, the IDE's syntax tree of a file (classes, functions, fields).
- **Project view**: the tool window listing the project's files.
- **Tool window**: a docked IDE panel (Project, Run, Debug, Problems, Git, Terminal...).
- **Inspection problem**: an error or warning the IDE reports on code.
- **EDT**: the Swing event dispatch thread; UI work must run there. Reads of the project model need a read action.
- **Sensitive file**: a file whose content must never leave the IDE (see Requirement 4.4).

## Requirements

### Requirement 1: Installation and connection

**User Story:** As a student, I want to install the plugin and connect it to my local Core in one click.

#### Acceptance Criteria

1. THE plugin SHALL build with Gradle (`./gradlew buildPlugin`) into an installable ZIP for IntelliJ IDEA 2026.2 (build 262) and later 262.x builds.
2. THE plugin SHALL offer settings for the Core address and the pairing token file (default `~/.wysp/token`), and actions to connect and disconnect.
3. WHEN connected, THE plugin SHALL send `wysp.hello` with its manifest and a heartbeat at least every 20 seconds, and reconnect with backoff when the Core goes away.
4. THE plugin SHALL serve one open project at a time: the most recently focused project window.

### Requirement 2: Threading

**User Story:** As a student, I want the IDE to stay responsive while Wysp works.

#### Acceptance Criteria

1. THE plugin SHALL read the project model and PSI only inside read actions, change code only inside write commands on the EDT, and touch Swing only on the EDT.
2. THE network thread SHALL never block the EDT for more than the request's own work; observation SHALL be computed in a non-blocking read action.
3. WHILE the IDE is indexing (dumb mode), THE plugin SHALL still answer observe and context requests with what is available and set a `dumb_mode` fact.

### Requirement 3: Observation

**User Story:** As a tutor, I want to see the project the way the student sees it, without reading the whole disk.

#### Acceptance Criteria

1. THE observation SHALL contain the entity kinds `project`, `module`, `directory`, `file`, `symbol`, `problem` and `run_config`, with refs of the scheme `intellij://`.
2. THE observation SHALL include the open files, the files of the current file's directory, top-level directories, the PSI structure (classes, functions, fields with line ranges) of the open files, the problems of the current file, and the run configurations, within the contract size limits, setting `truncated` and `counts` otherwise.
3. THE focus SHALL be the current file and the symbol at the caret.
4. `adapter.get_context` SHALL summarise the project, the current file and caret, and give the selected text and the code of the symbol at the caret (bounded in size).

### Requirement 4: Privacy

**User Story:** As a student, I want to know what of my code leaves the IDE.

#### Acceptance Criteria

1. THE plugin SHALL send code text only for the selection and the symbol at the caret of the current file (Requirement 3.4), and, since the decision of 2026-11-12, for the line ranges the tutor asks for through the read-only code tools of Requirement 5.5, never whole files in one piece and never in bulk.
2. THE plugin SHALL never read or write files outside the project content roots.
3. THE settings page SHALL state that this code goes to the configured LLM provider through the Core.
4. THE plugin SHALL never send the content of sensitive files: names matching `.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`, `*credentials*`, `*secret*`, `*.keystore`, `*.jks`; they appear as entities without content. The code tools refuse them, for reading and for writing.
5. (Decision of 2026-11-12, weakens 4.1 on purpose, at the user's request.) Reading other code is allowed only through `read_code`, `search_code`, `find_usages` and `list_files`: project files only, never sensitive files, never `.idea`, VCS data or build output, at most 150 lines or 8,000 characters per call, results bounded (50 matches). Every call is a `read_only` action, so it runs without a dialog but is written to the audit log with its parameters. `--llm scripted` or a local provider keeps all of it on the machine.

### Requirement 5: Actions

**User Story:** As a student, I want Wysp to show me where things are, and to do a step for me when I ask.

#### Acceptance Criteria

1. THE catalog SHALL be closed and declarative, one file per action. UI: `open_file`, `go_to_symbol`, `show_tool_window` (ui_state). Reading: `read_code`, `search_code`, `find_usages`, `list_files` (read_only). Changing code: `rename_symbol`, `replace_lines`, `insert_lines`, `create_file`, `reformat_code`, `optimize_imports` (reversible).
2. `rename_symbol` SHALL use the IDE's refactoring (all usages updated), run as one undoable command, return an undo token, and its undo SHALL restore the previous names.
3. No action SHALL run code, a run configuration, a shell command or an arbitrary IDE action id. Each IDE tool is a specific platform API call (for example the code style manager for `reformat_code`).
4. Each action SHALL declare postconditions that the Core verifies on a fresh observation, and a `guide.ui_path` with targets the tutor can highlight.
5. (Decision of 2026-11-12.) Read-only actions return their text in `ActionResult.message`, which the Core hands to the caller (bounded). The contract does not change.
6. (Decision of 2026-11-12.) Every action that changes code SHALL be `reversible`: it runs as one IDE command (so Ctrl+Z works too), refuses sensitive, read-only, noise (`.idea`, `build`...) and out-of-project files, checks the text it is about to replace (`old_text`) so that a stale edit changes nothing, reads the result back and fails (and restores the text) when it differs from what was asked, and returns an undo token. The approval dialog SHALL show the change as a diff (the Core asks the adapter for a dry-run preview of every reversible action). Writing code is never `irreversible`.

### Requirement 6: Highlight

**User Story:** As a student lost in the IDE, I want Wysp to point at the exact place.

#### Acceptance Criteria

1. `adapter.highlight` SHALL accept file, symbol and problem refs (open the file, scroll, and mark the range in the editor) and interface refs `intellij://ui/toolwindow/<id>` and `intellij://ui/label/<text>` (find the component by its text or accessible name in the IDE window and point at it with a balloon).
2. IF an interface element is not visible, THEN THE plugin SHALL return `-32012 TARGET_NOT_FOUND` with the visible labels of the IDE frame's toolbars and tool window stripes.
3. Highlighting SHALL never change code or project settings.

### Requirement 7: Events

**User Story:** As a tutor, I want to notice what the student does, so a guided step can be verified.

#### Acceptance Criteria

1. WHEN the current editor or the caret's symbol changes, THE plugin SHALL send `event.selection_changed`.
2. WHEN documents or files change, THE plugin SHALL send `event.state_changed` at most every 300 ms, tagged `wysp` for changes made by its own actions and `user` otherwise.

### Requirement 8: Wysp inside the IDE

**User Story:** As a student, I want to talk to Wysp without leaving the IDE.

#### Acceptance Criteria

1. THE plugin SHALL provide a "Wysp" tool window showing the shared Panel (chat, board, approvals) from the Core, embedded with the IDE's browser component.
2. IF the embedded browser is not available, THEN THE tool window SHALL say so and offer to open the Panel in the system browser.

### Requirement 9: Profile

**User Story:** As a student, I want the tutor to know the IDE's vocabulary and good habits.

#### Acceptance Criteria

1. THE profile SHALL describe the IDE (primer), give a glossary of at least 12 concepts with links to the IntelliJ IDEA documentation, skills for navigation, editing, running and debugging, refactoring and inspections, and speech hints.
2. THE profile SHALL pass `wysp validate-profile`.

### Requirement 10: Tests

1. Pure logic (JSON-RPC codec, refs, sensitive-file filter, label matching) SHALL have unit tests without the IDE.
2. Observation, actions and undo SHALL have tests on the IntelliJ test framework against a fixture project.
3. A sample project SHALL exist for demos and end-to-end checks with the plugin running in a sandbox IDE.

### Requirement 12: Subtree observation for project exploration

**User Story:** As the Core, I want to read the structure of one folder or file at a time, so that I can map a whole project in many small, fast calls.

#### Acceptance Criteria

1. WHEN the Core calls `adapter.observe {level: "full", root: <intellij://dir/...|intellij://file/...|intellij://project/...>}`, THE adapter SHALL return that subtree only: the project entity, the directories from the project root down to the root, the root's direct children, and (for files) their symbols, instead of the usual whole-project observation.
2. EACH file entity SHALL carry `language`, `size_bytes`, `symbols` (`done`, `pending` or `skipped`) and, when its symbols were read, `depends_on`: the refs of the project files it imports (Java, Kotlin and Python imports, resolved through the IDE's file index; nothing while the IDE is indexing).
3. THE adapter SHALL stop reading symbols after about 600 ms or when the observation nears 500 entities, and mark the remaining files `pending`; the Core then asks for them one by one.
4. SENSITIVE files, IDE settings, VCS data and build output SHALL NOT appear. No code body is sent: only names, signatures, sizes and dependency refs.

### Requirement 13: Pointing is always visible

**User Story:** As a student following the tutor through my project, I want to see what it is talking about, not only to hear it.

#### Acceptance Criteria

1. WHEN the tutor points at a folder or a module, THE adapter SHALL open the Project tool window, select the item and frame its row (the frame follows the row when the tree scrolls). IF the tree does not answer within 2.5 s, THE adapter SHALL frame the whole tool window instead.
2. WHEN the tutor points at a file as a whole, THE adapter SHALL open it and frame the editor.
3. WHEN the `show_tool_window` action opens a tool window, THE adapter SHALL frame that window for a few seconds.
4. A highlight from a narration cue SHALL last about as long as the sentence takes to say (2.5 s at least, 10 s at most), and a failed highlight SHALL be recorded in the session log (`highlight.failed`).
