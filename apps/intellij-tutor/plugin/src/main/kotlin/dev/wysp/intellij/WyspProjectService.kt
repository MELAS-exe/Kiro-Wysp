package dev.wysp.intellij

import com.intellij.openapi.Disposable
import com.intellij.openapi.components.Service
import com.intellij.openapi.project.Project

/** Per-project parts of the adapter: listeners and the highlighter, disposed with the project. */
@Service(Service.Level.PROJECT)
class WyspProjectService(private val project: Project) : Disposable {
    @Volatile private var events: Events? = null
    val highlighter = Highlighter(project, this)

    @Synchronized
    fun start() {
        if (events == null) events = Events(project, WyspService.get(), this)
    }

    override fun dispose() {
        events = null
    }
}
