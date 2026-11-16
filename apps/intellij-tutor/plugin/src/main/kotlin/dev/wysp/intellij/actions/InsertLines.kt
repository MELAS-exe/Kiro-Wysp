package dev.wysp.intellij.actions

import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.Refs
import dev.wysp.intellij.WyspError

/** insert_lines: add new lines after a given line, as one IDE command. */
class InsertLines : WyspAction {
    override val spec = actionSpec(
        "insert_lines",
        "Insert lines of code",
        "Insert new_text as new lines after line after_line (0 = at the top of the file). When after_line is above " +
            "0, anchor_text must be the current text of that line exactly as read with read_code (without the line " +
            "number): if it does not match, nothing changes. Keep the file's indentation in new_text. The user sees " +
            "a diff and must approve; the change can be undone.",
        mapOf(
            "target" to FILE_REF,
            "after_line" to mapOf("type" to "integer", "minimum" to 0, "description" to "Insert after this line; 0 = top of the file"),
            "anchor_text" to mapOf("type" to "string", "maxLength" to 2_000, "description" to "Current text of line after_line (required when after_line > 0)"),
            "new_text" to mapOf("type" to "string", "minLength" to 1, "maxLength" to CodeAccess.MAX_EDIT_CHARS, "description" to "The lines to insert"),
        ),
        listOf("target", "after_line", "new_text"),
        "reversible",
        CodeAccess.fileObserved(),
        listOf(
            step("Open “\${label:params.target}”", "\${params.target}"),
            step("Put the caret at the end of line \${params.after_line}, press Enter and type the new code"),
        ),
    )

    private class Plan(val path: String, val vf: VirtualFile, val after: Int, val anchor: String?, val newText: String)

    override fun resolve(project: Project, params: Map<String, Any?>): Any {
        val (path, vf, doc) = CodeAccess.readable(project, params["target"] as String)
        CodeAccess.writable(path, vf)
        val after = CodeAccess.intParam(params, "after_line")!!
        val anchor = params["anchor_text"] as? String
        val text = CodeAccess.cleanNew(params["new_text"] as String)
        if (text.isEmpty()) throw WyspError(ErrorCode.INVALID_PARAMS, "new_text is empty")
        if (after > 0 && anchor == null) throw WyspError(ErrorCode.INVALID_PARAMS, "anchor_text is required when after_line is above 0")
        check(doc, path, after, anchor)
        return Plan(path, vf, after, anchor, text)
    }

    private fun check(doc: com.intellij.openapi.editor.Document, path: String, after: Int, anchor: String?) {
        if (after == 0) return
        CodeAccess.requireCurrent(doc, path, after, after, anchor ?: "")
    }

    override fun run(project: Project, params: Map<String, Any?>, resolved: Any?, dryRun: Boolean): ActionOutcome {
        val p = resolved as Plan
        val doc = FileDocumentManager.getInstance().getDocument(p.vf)
            ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "cannot read ${p.path}")
        check(doc, p.path, p.after, p.anchor)
        val added = p.newText.split("\n")
        if (dryRun) {
            val before = if (p.after == 0) emptyList() else CodeAccess.contextBefore(doc, p.after + 1)
            val rest = if (p.after >= doc.lineCount || doc.textLength == 0) emptyList() else CodeAccess.contextAfter(doc, p.after)
            return ActionOutcome(
                preview = mapOf("file" to p.path, "lines" to "after ${p.after}", "diff" to CodeAccess.diff(before, emptyList(), added, rest)),
            )
        }
        val (offset, text) = when {
            doc.textLength == 0 -> 0 to p.newText + "\n"
            p.after == 0 -> 0 to p.newText + "\n"
            else -> doc.getLineEndOffset(p.after - 1) to "\n" + p.newText
        }
        val undo = TextEdits.replace(project, doc, offset, offset, text, "Wysp: insert lines after ${p.after}")
        CodeAccess.reveal(project, p.vf, p.after + 1)
        return ActionOutcome(
            changed = listOf(Refs.file(p.path), CodeAccess.ref(p.path, p.after + 1, p.after + added.size)),
            undo = {
                undo()
                listOf(Refs.file(p.path))
            },
            message = "Inserted ${added.size} line(s) after line ${p.after} of ${p.path}",
        )
    }
}
