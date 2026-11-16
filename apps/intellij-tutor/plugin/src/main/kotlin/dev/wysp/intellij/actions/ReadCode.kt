package dev.wysp.intellij.actions

import com.intellij.openapi.project.Project
import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.Privacy
import dev.wysp.intellij.WyspError

/** read_code: numbered lines of a project file. The text comes back in the action's message. */
class ReadCode : WyspAction {
    override val spec = actionSpec(
        "read_code",
        "Read code",
        "Read lines of a project file (not sensitive files, not IDE or build output). Returns the lines numbered " +
            "like in the editor. At most ${CodeAccess.MAX_READ_LINES} lines per call. Use mode 'do': nothing changes " +
            "and no approval is asked.",
        mapOf(
            "target" to FILE_REF,
            "from_line" to mapOf("type" to "integer", "minimum" to 1, "description" to "First line, 1-based"),
            "to_line" to mapOf("type" to "integer", "minimum" to 1, "description" to "Last line, inclusive"),
        ),
        listOf("target", "from_line", "to_line"),
        "read_only",
        emptyList(),
        emptyList(),
    )

    override fun resolve(project: Project, params: Map<String, Any?>): Any {
        val (path, _, doc) = CodeAccess.readable(project, params["target"] as String)
        val from = (params["from_line"] as Number).toInt()
        val requestedTo = (params["to_line"] as Number).toInt()
        if (requestedTo < from) throw WyspError(ErrorCode.INVALID_PARAMS, "to_line ($requestedTo) is before from_line ($from)")
        CodeAccess.checkLines(doc, path, from, from)
        val to = minOf(requestedTo, doc.lineCount, from + CodeAccess.MAX_READ_LINES - 1)
        val body = Privacy.bound(CodeAccess.numbered(doc, from, to), CodeAccess.MAX_READ_CHARS)
        val note = if (to < requestedTo) " (cut at $to: ask again from line ${to + 1} for more)" else ""
        return "$path, lines $from-$to of ${doc.lineCount}$note\n$body"
    }

    override fun run(project: Project, params: Map<String, Any?>, resolved: Any?, dryRun: Boolean) =
        ActionOutcome(message = resolved as String)
}
