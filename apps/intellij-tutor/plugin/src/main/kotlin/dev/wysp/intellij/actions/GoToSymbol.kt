package dev.wysp.intellij.actions

import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.OpenFileDescriptor
import com.intellij.openapi.project.DumbService
import com.intellij.openapi.project.Project
import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.Refs
import dev.wysp.intellij.WyspError

/** go_to_symbol: open the symbol's file with the caret on its name. UI state only. */
class GoToSymbol : WyspAction {
    override val spec = actionSpec(
        "go_to_symbol",
        "Go to a symbol",
        "Open the file of a class, function or field and put the caret on its name, so the user sees its code.",
        mapOf("target" to SYMBOL_REF),
        listOf("target"),
        "ui_state",
        listOf(mapOf("path" to "focus", "op" to "contains", "value" to "\${params.target}")),
        listOf(
            step("Press Ctrl+N (classes) or Ctrl+Alt+Shift+N (symbols) — Navigate > Symbol…"),
            step("Type “\${label:params.target}” and press Enter"),
        ),
    )

    private class Target(val path: String, val vf: com.intellij.openapi.vfs.VirtualFile, val exact: String, val offset: Int, val line: Int, val name: String)

    /** Background read action: find the symbol and where its name is. */
    override fun resolve(project: Project, params: Map<String, Any?>): Any {
        if (DumbService.isDumb(project)) throw WyspError(ErrorCode.BUSY, "the IDE is indexing; try again in a moment")
        val (path, vf, symbol) = resolveSymbol(project, params["target"] as String)
        return Target(path, vf, Refs.symbol(path, symbol.parts), symbol.element.textOffset, symbol.line, symbol.parts.joinToString("."))
    }

    override fun run(project: Project, params: Map<String, Any?>, resolved: Any?, dryRun: Boolean): ActionOutcome {
        val t = resolved as Target
        if (dryRun) return ActionOutcome(preview = mapOf("would_go_to" to t.exact, "line" to t.line))
        FileEditorManager.getInstance(project).openTextEditor(OpenFileDescriptor(project, t.vf, t.offset), true)
            ?: throw WyspError(ErrorCode.EXECUTION_FAILED, "the IDE could not open ${t.path}")
        return ActionOutcome(changed = listOf(t.exact), message = "Showing ${t.name} in ${t.path}, line ${t.line}")
    }
}
