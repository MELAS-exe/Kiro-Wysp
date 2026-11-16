package dev.wysp.intellij.actions

import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.project.DumbService
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.psi.PsiDocumentManager
import com.intellij.psi.codeStyle.CodeStyleManager
import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.Refs
import dev.wysp.intellij.WyspError

/** reformat_code: the IDE's code style applied to a file or a range of lines. */
class ReformatCode : WyspAction {
    override val spec = actionSpec(
        "reformat_code",
        "Reformat code",
        "Apply the project's code style (indentation, spacing, line wrapping) to a whole file, or only to lines " +
            "from_line..to_line when both are given. The user must approve; the change can be undone.",
        mapOf(
            "target" to FILE_REF,
            "from_line" to mapOf("type" to "integer", "minimum" to 1, "description" to "Optional first line, 1-based"),
            "to_line" to mapOf("type" to "integer", "minimum" to 1, "description" to "Optional last line, inclusive"),
        ),
        listOf("target"),
        "reversible",
        CodeAccess.fileObserved(),
        listOf(
            step("Open “\${label:params.target}”", "\${params.target}"),
            step("Press Ctrl+Alt+L (Code > Reformat Code)"),
        ),
    )

    private class Plan(val path: String, val vf: VirtualFile, val from: Int?, val to: Int?)

    override fun resolve(project: Project, params: Map<String, Any?>): Any {
        if (DumbService.isDumb(project)) throw WyspError(ErrorCode.BUSY, "the IDE is indexing; try again in a moment")
        val (path, vf, doc) = CodeAccess.readable(project, params["target"] as String)
        CodeAccess.writable(path, vf)
        val from = CodeAccess.intParam(params, "from_line")
        val to = CodeAccess.intParam(params, "to_line")
        if ((from == null) != (to == null)) throw WyspError(ErrorCode.INVALID_PARAMS, "give both from_line and to_line, or neither")
        if (from != null && to != null) CodeAccess.checkLines(doc, path, from, to)
        return Plan(path, vf, from, to)
    }

    override fun run(project: Project, params: Map<String, Any?>, resolved: Any?, dryRun: Boolean): ActionOutcome {
        val p = resolved as Plan
        val doc = FileDocumentManager.getInstance().getDocument(p.vf)
            ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "cannot read ${p.path}")
        val where = if (p.from != null && p.to != null) "lines ${p.from}-${p.to}" else "the whole file"
        if (dryRun) {
            return ActionOutcome(preview = mapOf("file" to p.path, "lines" to where, "diff" to " The IDE's code style will be applied to $where."))
        }
        if (DumbService.isDumb(project)) throw WyspError(ErrorCode.BUSY, "the IDE is indexing; try again in a moment")
        val undo = TextEdits.rewrite(project, doc, "Wysp: reformat ${p.path}") {
            val psi = PsiDocumentManager.getInstance(project).getPsiFile(doc)
                ?: throw WyspError(ErrorCode.EXECUTION_FAILED, "${p.path} has no syntax tree to format")
            val (start, end) = if (p.from != null && p.to != null) {
                doc.getLineStartOffset(p.from - 1) to doc.getLineEndOffset(p.to - 1)
            } else 0 to doc.textLength
            CodeStyleManager.getInstance(project).reformatText(psi, start, end)
        }
        CodeAccess.reveal(project, p.vf, p.from ?: 1)
        return ActionOutcome(
            changed = listOf(Refs.file(p.path)),
            undo = {
                undo?.invoke() // nothing changed: the undo is a no-op, but a reversible action always has one
                listOf(Refs.file(p.path))
            },
            message = if (undo == null) "${p.path} already follows the code style ($where)" else "Reformatted $where of ${p.path}",
        )
    }
}
