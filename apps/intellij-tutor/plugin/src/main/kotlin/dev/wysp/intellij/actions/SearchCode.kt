package dev.wysp.intellij.actions

import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.roots.ProjectFileIndex
import dev.wysp.intellij.Observer
import dev.wysp.intellij.Privacy

/** search_code: plain-text search (not a regex) in the project's text files. */
class SearchCode : WyspAction {
    override val spec = actionSpec(
        "search_code",
        "Search the code",
        "Find a text in the project's source files (case-insensitive, plain text, not a regex). Returns up to " +
            "${CodeAccess.MAX_RESULTS} matches as path:line: text. Sensitive files, IDE settings and build output are " +
            "never searched. Use mode 'do': nothing changes and no approval is asked.",
        mapOf("query" to mapOf("type" to "string", "minLength" to 2, "maxLength" to 100, "description" to "Text to look for")),
        listOf("query"),
        "read_only",
        emptyList(),
        emptyList(),
    )

    override fun resolve(project: Project, params: Map<String, Any?>): Any {
        val query = (params["query"] as String).lowercase()
        val observer = Observer(project)
        val deadline = System.nanoTime() + 3_000_000_000L
        val hits = mutableListOf<String>()
        var scanned = 0
        var complete = true
        ProjectFileIndex.getInstance(project).iterateContent { vf ->
            if (vf.isDirectory) return@iterateContent true
            if (hits.size >= CodeAccess.MAX_RESULTS || scanned >= MAX_FILES || System.nanoTime() > deadline) {
                complete = false
                return@iterateContent false
            }
            val path = observer.relPath(vf) ?: return@iterateContent true
            if (Observer.isNoise(path) || Privacy.isSensitivePath(path)) return@iterateContent true
            if (vf.fileType.isBinary || vf.length > CodeAccess.MAX_FILE_BYTES) return@iterateContent true
            scanned++
            val doc = FileDocumentManager.getInstance().getCachedDocument(vf)
            val text: CharSequence = doc?.charsSequence ?: runCatching { String(vf.contentsToByteArray(), vf.charset) }.getOrNull() ?: return@iterateContent true
            var from = 0
            while (hits.size < CodeAccess.MAX_RESULTS) {
                val at = text.indexOf(query, from, ignoreCase = true)
                if (at < 0) break
                val start = text.lastIndexOf('\n', at).let { if (it < 0) 0 else it + 1 }
                val end = text.indexOf('\n', at).let { if (it < 0) text.length else it }
                val line = text.subSequence(0, at).count { it == '\n' } + 1
                hits += "$path:$line: ${Privacy.oneLine(text.substring(start, end), 160)}"
                from = end + 1
                if (from >= text.length) break
            }
            true
        }
        val head = "${hits.size} match(es) for '${params["query"]}' in $scanned files" +
            if (!complete) " (stopped early: narrow the query)" else ""
        return Privacy.bound((listOf(head) + hits).joinToString("\n"), CodeAccess.MAX_READ_CHARS)
    }

    override fun run(project: Project, params: Map<String, Any?>, resolved: Any?, dryRun: Boolean) =
        ActionOutcome(message = resolved as String)

    private companion object {
        const val MAX_FILES = 2_500
    }
}
