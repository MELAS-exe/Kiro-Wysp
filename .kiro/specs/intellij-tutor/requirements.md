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

1. THE plugin SHALL send code text only for the selection and the symbol at the caret of the current file (Requirement 3.4), never whole files or other files' contents.
2. THE plugin SHALL never read files outside the project content roots.
3. THE settings page SHALL state that this code goes to the configured LLM provider through the Core.
4. THE plugin SHALL never send the content of sensitive files: names matching `.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `id_ed25519*`, `*credentials*`, `*secret*`, `*.keystore`, `*.jks`; they appear as entities without content.

### Requirement 5: Actions

**User Story:** As a student, I want Wysp to show me where things are, and to do a step for me when I ask.

#### Acceptance Criteria

1. THE catalog SHALL be closed and declarative, one file per action: `open_file` (ui_state), `go_to_symbol` (ui_state), `show_tool_window` (ui_state) and `rename_symbol` (reversible).
2. `rename_symbol` SHALL use the IDE's refactoring (all usages updated), run as one undoable command, return an undo token, and its undo SHALL restore the previous names.
3. No action SHALL run code, a run configuration, a shell command or an arbitrary IDE action id.
4. Each action SHALL declare postconditions that the Core verifies on a fresh observation, and a `guide.ui_path` with targets the tutor can highlight.

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
