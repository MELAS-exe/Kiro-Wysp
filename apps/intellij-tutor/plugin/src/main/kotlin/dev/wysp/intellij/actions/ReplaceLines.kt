package dev.wysp.intellij.actions

import com.intellij.openapi.editor.Document
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.Refs
import dev.wysp.intellij.WyspError

/** replace_lines: change (or delete) whole lines of a file, as one IDE command. */
class ReplaceLines : WyspAction {
    override val spec = actionSpec(
        "replace_lines",
        "Replace lines of code",
        "Replace lines from_line..to_line (1-based, inclusive) of a project file with new_text. old_text must be " +
            "the current text of those lines exactly as read with read_code (without the line numbers): if it does " +
            "not match, nothing changes. An empty new_text deletes the lines. Keep the file's indentation in " +
            "new_text. The user sees a diff and must approve; the change can be undone.",
        mapOf(
            "target" to FILE_REF,
            "from_line" to mapOf("type" to "integer", "minimum" to 1, "description" to "First line to replace, 1-based"),
            "to_line" to mapOf("type" to "integer", "minimum" to 1, "description" to "Last line to replace, inclusive"),
            "old_text" to mapOf("type" to "string", "minLength" to 1, "maxLength" to CodeAccess.MAX_EDIT_CHARS, "description" to "The current text of the lines"),
            "new_text" to mapOf("type" to "string", "maxLength" to CodeAccess.MAX_EDIT_CHARS, "description" to "The replacement lines; empty deletes"),
        ),
        listOf("target", "from_line", "to_line", "old_text", "new_text"),
        "reversible",
        CodeAccess.fileObserved(),
        listOf(
            step("Open “\${label:params.target}”", "\${params.target}"),
            step("Select lines \${params.from_line} to \${params.to_line} and type the new code"),
        ),
    )

    private class Plan(val path: String, val vf: VirtualFile, val from: Int, val to: Int, val oldText: String, val newText: String)

    override fun resolve(project: Project, params: Map<String, Any?>): Any {
        val (path, vf, doc) = CodeAccess.readable(project, params["target"] as String)
        CodeAccess.writable(path, vf)
        val from = CodeAccess.intParam(params, "from_line")!!
        val to = CodeAccess.intParam(params, "to_line")!!
        if (to < from) throw WyspError(ErrorCode.INVALID_PARAMS, "to_line ($to) is before from_line ($from)")
        val old = params["old_text"] as String
        CodeAccess.requireCurrent(doc, path, from, to, old)
        return Plan(path, vf, from, to, old, CodeAccess.cleanNew(params["new_text"] as String))
    }

    override fun run(project: Project, params: Map<String, Any?>, resolved: Any?, dryRun: Boolean): ActionOutcome {
        val p = resolved as Plan
        val doc = FileDocumentManager.getInstance().getDocument(p.vf)
            ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "cannot read ${p.path}")
        CodeAccess.requireCurrent(doc, p.path, p.from, p.to, p.oldText) // the file may have changed since resolve
        val removed = (p.from..p.to).map { CodeAccess.lineText(doc, it) }
        val added = if (p.newText.isEmpty()) emptyList() else p.newText.split("\n")
        if (dryRun) {
            return ActionOutcome(
                preview = mapOf(
                    "file" to p.path,
                    "lines" to "${p.from}-${p.to}",
                    "diff" to CodeAccess.diff(CodeAccess.contextBefore(doc, p.from), removed, added, CodeAccess.contextAfter(doc, p.to)),
                ),
            )
        }
        val (start, end) = range(doc, p.from, p.to, p.newText)
        val undo = TextEdits.replace(project, doc, start, end, p.newText, "Wysp: replace lines ${p.from}-${p.to}")
        CodeAccess.reveal(project, p.vf, p.from)
        val last = p.from + maxOf(added.size, 1) - 1
        return ActionOutcome(
            changed = listOf(Refs.file(p.path), CodeAccess.ref(p.path, p.from, last)),
            undo = {
                undo()
                listOf(Refs.file(p.path))
            },
            message = if (added.isEmpty()) "Deleted lines ${p.from}-${p.to} of ${p.path}"
            else "Replaced lines ${p.from}-${p.to} of ${p.path} with ${added.size} line(s)",
        )
    }

    /** The character range to replace: the lines' text, or the lines and one line break when deleting. */
    private fun range(doc: Document, from: Int, to: Int, newText: String): Pair<Int, Int> {
        val lineStart = doc.getLineStartOffset(from - 1)
        val lineEnd = doc.getLineEndOffset(to - 1)
        if (newText.isNotEmpty()) return lineStart to lineEnd
        return when {
            to < doc.lineCount -> lineStart to doc.getLineStartOffset(to)
            from > 1 -> doc.getLineEndOffset(from - 2) to lineEnd
            else -> 0 to lineEnd
        }
    }
}
