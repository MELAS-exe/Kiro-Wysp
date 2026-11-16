package dev.wysp.intellij

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.Service
import com.intellij.openapi.project.Project

/** Per-project parts of the adapter: listeners and the highlighter, disposed with the project. */
@Service(Service.Level.PROJECT)
class WyspProjectService(private val project: Project) : Disposable {
    @Volatile private var events: Events? = null

    // The user used what Wysp pointed at: the highlighter took it down, tell the Core (contract 1.1).
    val highlighter = Highlighter(project, this) { ref ->
        WyspService.get().notify("event.highlight_dismissed", mapOf("ref" to ref, "reason" to "user"))
    }

    init {
        // A highlight does not outlive the connection: the Core no longer knows about it.
        WyspService.get().addStatusListener(this) { status, _ ->
            if (status != "connected") ApplicationManager.getApplication().invokeLater({ highlighter.clear() }, project.disposed)
        }
    }

    @Synchronized
    fun start() {
        if (events == null) events = Events(project, WyspService.get(), this)
    }

    override fun dispose() {
        events = null
    }
}
