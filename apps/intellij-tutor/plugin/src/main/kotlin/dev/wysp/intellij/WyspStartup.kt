package dev.wysp.intellij

import com.intellij.openapi.components.service
import com.intellij.openapi.project.Project
import com.intellij.openapi.startup.ProjectActivity
import dev.wysp.intellij.ui.WyspSettings

/** Starts the project listeners and, if enabled, the connection to the Core. */
class WyspStartup : ProjectActivity {
    override suspend fun execute(project: Project) {
        project.service<WyspProjectService>().start()
        if (WyspSettings.get().state.autoConnect) WyspService.get().connect()
    }
}
