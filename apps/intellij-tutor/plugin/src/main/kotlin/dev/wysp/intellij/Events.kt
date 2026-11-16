package dev.wysp.intellij

import com.intellij.codeInsight.daemon.DaemonCodeAnalyzer
import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ReadAction
import com.intellij.openapi.fileEditor.FileEditor
import com.intellij.util.concurrency.AppExecutorUtil
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.editor.EditorFactory
import com.intellij.openapi.editor.event.CaretEvent
import com.intellij.openapi.editor.event.CaretListener
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.editor.event.SelectionEvent
import com.intellij.openapi.editor.event.SelectionListener
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.FileEditorManagerEvent
import com.intellij.openapi.fileEditor.FileEditorManagerListener
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.DumbService
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileManager
import com.intellij.openapi.vfs.newvfs.BulkFileListener
import com.intellij.openapi.vfs.newvfs.events.VFileEvent
import com.intellij.util.Alarm

/**
 * Editor, caret and file listeners for one project. Selection changes are debounced (300 ms) into
 * `event.selection_changed`; document and file changes are debounced (300 ms) into `event.state_changed`,
 * tagged `wysp` when they happen within the origin window after a Wysp action.
 */
class Events(private val project: Project, private val service: WyspService, private val parent: Disposable) {
    private val selectionAlarm = Alarm(Alarm.ThreadToUse.SWING_THREAD, parent)
    private val stateAlarm = Alarm(Alarm.ThreadToUse.POOLED_THREAD, parent)
    private val batch = ChangeBatch()
    private val selection = SelectionTracker()
    private val problemTracker = ProblemTracker()
    @Volatile private var wyspMoved = false

    init {
        project.messageBus.connect(parent).subscribe(
            FileEditorManagerListener.FILE_EDITOR_MANAGER,
            object : FileEditorManagerListener {
                override fun selectionChanged(event: FileEditorManagerEvent) = selectionChanged()
            },
        )
        val multicaster = EditorFactory.getInstance().eventMulticaster
        multicaster.addCaretListener(object : CaretListener {
            override fun caretPositionChanged(event: CaretEvent) {
                if (event.editor.project == project) selectionChanged()
            }
        }, parent)
        multicaster.addSelectionListener(object : SelectionListener {
            override fun selectionChanged(e: SelectionEvent) {
                if (e.editor.project == project) this@Events.selectionChanged()
            }
        }, parent)
        multicaster.addDocumentListener(object : DocumentListener {
            override fun documentChanged(event: DocumentEvent) {
                val vf = FileDocumentManager.getInstance().getFile(event.document) ?: return
                changed(vf)
            }
        }, parent)
        project.messageBus.connect(parent).subscribe(
            DaemonCodeAnalyzer.DAEMON_EVENT_TOPIC,
            object : DaemonCodeAnalyzer.DaemonListener {
                override fun daemonFinished(fileEditors: Collection<FileEditor>) = analysisFinished(fileEditors)
            },
        )
        // Indexing finished: symbols are skipped while the IDE indexes, so a survey taken then is incomplete.
        project.messageBus.connect(parent).subscribe(
            DumbService.DUMB_MODE,
            object : DumbService.DumbModeListener {
                override fun exitDumbMode() {
                    if (!service.connected || project.isDisposed) return
                    service.notify(
                        "event.state_changed",
                        mapOf("state_version" to service.bump(), "changed" to listOf(Refs.project(project.name)), "origin" to "unknown"),
                    )
                }
            },
        )
        ApplicationManager.getApplication().messageBus.connect(parent).subscribe(
            VirtualFileManager.VFS_CHANGES,
            object : BulkFileListener {
                override fun after(events: List<VFileEvent>) {
                    for (e in events) e.file?.let { changed(it) }
                }
            },
        )
    }

    private fun selectionChanged() {
        if (!service.connected || project.isDisposed) return
        // The caret moved because Wysp opened or renamed something: not the user's selection. The contract's
        // selection event has no origin, so the adapter keeps it to itself (the focus is still refreshed).
        if (service.origin.current() == "wysp") wyspMoved = true
        selectionAlarm.cancelAllRequests()
        selectionAlarm.addRequest({
            val ours = wyspMoved
            wyspMoved = false
            service.focusOf(project).thenAccept { focus ->
                if (selection.onFocus(focus, ours)) {
                    // A caret move is a change of state: advance the version, or "select X" exercises never pass.
                    service.bump()
                    service.notify("event.selection_changed", mapOf("focus" to focus))
                }
            }
        }, DEBOUNCE_MS)
    }

    private fun changed(vf: VirtualFile) {
        if (!service.connected || project.isDisposed) return
        val path = Observer(project).relPath(vf) ?: return // outside the project: not our state
        if (Observer.isNoise(path)) return // IDE settings and build output change on their own
        val origin = service.origin.current()
        markChanged(if (vf.isDirectory) Refs.dir(path) else Refs.file(path), origin)
    }

    private fun markChanged(ref: String, origin: String) {
        batch.add(ref, origin)?.let { send(it) } // another origin: the pending batch goes out on its own
        stateAlarm.cancelAllRequests()
        stateAlarm.addRequest({ batch.take()?.let { send(it) } }, DEBOUNCE_MS)
    }

    private fun send(b: ChangeBatch.Batch) {
        service.notify("event.state_changed", mapOf("state_version" to service.bump(), "changed" to b.changed, "origin" to b.origin))
    }

    /** The IDE finished analysing: if the problems of a file changed, say so (the edit event came before the analysis). */
    private fun analysisFinished(editors: Collection<FileEditor>) {
        if (!service.connected || project.isDisposed) return
        val files = editors.mapNotNull { it.file }.distinct()
        if (files.isEmpty()) return
        ReadAction.nonBlocking<Unit> {
            val observer = Observer(project)
            for (vf in files) {
                val path = observer.relPath(vf) ?: continue
                if (Observer.isNoise(path) || Privacy.isSensitivePath(path)) continue
                val doc = FileDocumentManager.getInstance().getCachedDocument(vf) ?: continue
                if (problemTracker.changed(path, observer.problemSignature(doc))) {
                    markChanged(Refs.file(path), service.origin.current())
                }
            }
        }.expireWith(parent).submit(AppExecutorUtil.getAppExecutorService())
    }

    companion object {
        const val DEBOUNCE_MS = 300
    }
}
