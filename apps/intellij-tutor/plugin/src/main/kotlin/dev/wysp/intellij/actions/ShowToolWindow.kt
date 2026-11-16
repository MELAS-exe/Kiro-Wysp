package dev.wysp.intellij.actions

import com.intellij.openapi.components.service
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindowManager
import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.Highlighter
import dev.wysp.intellij.Refs
import dev.wysp.intellij.WyspError
import dev.wysp.intellij.WyspProjectService

/** show_tool_window: open and focus a tool window by id. UI state only. */
class ShowToolWindow : WyspAction {
    override val spec = actionSpec(
        "show_tool_window",
        "Show a tool window",
        "Open and focus an IDE tool window. Common ids: Project, Structure, Problems View, Run, Debug, Terminal, " +
            "Commit, Version Control, Find, TODO, Services, Gradle, Maven.",
        mapOf("id" to mapOf("type" to "string", "minLength" to 1, "maxLength" to 60, "description" to "Tool window id")),
        listOf("id"),
        "ui_state",
        emptyList(),
        listOf(step("Open View > Tool Windows > \${params.id}, or click its button on the side bar")),
    )

    override fun run(project: Project, params: Map<String, Any?>, resolved: Any?, dryRun: Boolean): ActionOutcome {
        val id = params["id"] as String
        val manager = ToolWindowManager.getInstance(project)
        val tw = manager.getToolWindow(id)
            ?: manager.toolWindowIds.firstOrNull { it.equals(id, ignoreCase = true) }?.let { manager.getToolWindow(it) }
            ?: throw WyspError(
                ErrorCode.TARGET_NOT_FOUND,
                "no tool window '$id'. Available: ${manager.toolWindowIds.sorted().joinToString(", ")}",
                mapOf("available" to manager.toolWindowIds.sorted()),
            )
        if (!tw.isAvailable) throw WyspError(ErrorCode.PRECONDITION_FAILED, "the ${tw.id} tool window is not available in this project")
        if (dryRun) return ActionOutcome(preview = mapOf("would_show" to tw.id))
        tw.activate(null, true)
        // Opening a panel is also pointing at it: frame it for a few seconds so the student sees which one.
        runCatching {
            val highlighter = project.service<WyspProjectService>().highlighter
            highlighter.highlight(Highlighter.Plan.ToolWindowPlan(tw.id), 4000)
        }
        return ActionOutcome(changed = listOf(Refs.toolWindow(tw.id)), message = "Opened the ${tw.id} tool window")
    }
}
