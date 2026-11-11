package dev.wysp.intellij.actions

import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.OpenFileDescriptor
import com.intellij.openapi.project.Project
import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.WyspError

/** open_file: open a project file in the editor, optionally at a line. UI state only. */
class OpenFile : WyspAction {
    override val spec = actionSpec(
        "open_file",
        "Open a file",
        "Open a project file in the editor and focus it, optionally with the caret at a line (1-based).",
        mapOf(
            "target" to FILE_REF,
            "line" to mapOf("type" to "integer", "minimum" to 1, "description" to "Optional line, 1-based"),
        ),
        listOf("target"),
        "ui_state",
        listOf(mapOf("path" to "focus", "op" to "contains", "value" to "\${params.target}")),
        listOf(
            step("Open the Project tool window (Alt+1)", "intellij://ui/toolwindow/Project"),
            step("Double-click “\${label:params.target}”, or press Ctrl+Shift+N (Navigate > File) and type its name"),
        ),
    )

    override fun run(project: Project, params: Map<String, Any?>, resolved: Any?, dryRun: Boolean): ActionOutcome {
        val ref = params["target"] as String
        val (path, vf) = resolveFile(project, ref)
        val line = (params["line"] as? Number)?.toInt()
        if (dryRun) return ActionOutcome(preview = mapOf("would_open" to path, "line" to line))
        val descriptor = if (line != null) OpenFileDescriptor(project, vf, line - 1, 0) else OpenFileDescriptor(project, vf)
        FileEditorManager.getInstance(project).openTextEditor(descriptor, true)
            ?: FileEditorManager.getInstance(project).openFile(vf, true).firstOrNull()
            ?: throw WyspError(ErrorCode.EXECUTION_FAILED, "the IDE could not open $path")
        return ActionOutcome(changed = listOf(ref), message = "Opened $path" + (line?.let { " at line $it" } ?: ""))
    }
}
