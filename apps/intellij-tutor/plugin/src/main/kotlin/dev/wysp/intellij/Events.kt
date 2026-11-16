package dev.wysp.intellij

import com.intellij.openapi.Disposable
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
class Events(private val project: Project, private val service: WyspService, parent: Disposable) {
    private val selectionAlarm = Alarm(Alarm.ThreadToUse.SWING_THREAD, parent)
    private val stateAlarm = Alarm(Alarm.ThreadToUse.POOLED_THREAD, parent)
    private val dirty = LinkedHashSet<String>()
    private var batchOrigin = "user"
    private var lastFocus: List<String> = emptyList()
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
                if (focus != lastFocus) {
                    lastFocus = focus
                    if (!ours) service.notify("event.selection_changed", mapOf("focus" to focus))
                }
            }
        }, DEBOUNCE_MS)
    }

    private fun changed(vf: VirtualFile) {
        if (!service.connected || project.isDisposed) return
        val path = Observer(project).relPath(vf) ?: return // outside the project: not our state
        if (Observer.isNoise(path)) return // IDE settings and build output change on their own
        val origin = service.origin.current()
        synchronized(dirty) {
            dirty += if (vf.isDirectory) Refs.dir(path) else Refs.file(path)
            if (origin == "wysp") batchOrigin = "wysp"
        }
        stateAlarm.cancelAllRequests()
        stateAlarm.addRequest({ flush() }, DEBOUNCE_MS)
    }

    private fun flush() {
        val (changed, origin) = synchronized(dirty) {
            val c = dirty.take(50)
            val o = batchOrigin
            dirty.clear()
            batchOrigin = "user"
            c to o
        }
        if (changed.isEmpty()) return
        service.notify("event.state_changed", mapOf("state_version" to service.bump(), "changed" to changed, "origin" to origin))
    }

    companion object {
        const val DEBOUNCE_MS = 300
    }
}
