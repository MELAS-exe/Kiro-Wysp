package dev.wysp.intellij.actions

import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.editor.Document
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.OpenFileDescriptor
import com.intellij.openapi.editor.ScrollType
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.TextRange
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.psi.PsiDocumentManager
import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.Observer
import dev.wysp.intellij.Privacy
import dev.wysp.intellij.Refs
import dev.wysp.intellij.WyspError

/**
 * What the code tools may touch (Requirement 4.5 and 5.6). Every read and every write of project text goes
 * through [readable] / [writable], so a sensitive, IDE, VCS, build or binary file is refused in one place.
 */
object CodeAccess {
    const val MAX_READ_LINES = 150
    const val MAX_READ_CHARS = 8_000
    const val MAX_EDIT_CHARS = 20_000
    const val MAX_FILE_BYTES = 1_000_000L
    const val MAX_RESULTS = 50

    /** A project text file the tutor may read. Call with read access (the EDT has it). */
    fun readable(project: Project, ref: String): Triple<String, VirtualFile, Document> {
        val (path, vf) = resolveFile(project, ref)
        refuse(path)
        if (vf.fileType.isBinary || vf.length > MAX_FILE_BYTES) {
            throw WyspError(ErrorCode.PRECONDITION_FAILED, "$path is binary or too large for Wysp's code tools")
        }
        val doc = FileDocumentManager.getInstance().getDocument(vf)
            ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "$path is not a text file")
        return Triple(path, vf, doc)
    }

    fun writable(path: String, vf: VirtualFile) {
        if (!vf.isWritable) throw WyspError(ErrorCode.PRECONDITION_FAILED, "$path is read-only")
    }

    /** Sensitive files and IDE, VCS or build output: never read, never changed. Content is not touched. */
    fun refuse(path: String) {
        if (Privacy.isSensitivePath(path)) {
            throw WyspError(ErrorCode.PRECONDITION_FAILED, "$path is a sensitive file: Wysp never reads or changes it")
        }
        if (Observer.isNoise(path)) {
            throw WyspError(ErrorCode.PRECONDITION_FAILED, "$path is IDE settings, VCS data or build output: Wysp does not read or change it")
        }
    }

    fun lineText(doc: Document, n: Int): String = doc.getText(TextRange(doc.getLineStartOffset(n - 1), doc.getLineEndOffset(n - 1)))

    /** Lines `from..to` (1-based, inclusive) as "  12| code". */
    fun numbered(doc: Document, from: Int, to: Int): String =
        (from..to).joinToString("\n") { "%4d| %s".format(it, lineText(doc, it)) }

    fun checkLines(doc: Document, path: String, from: Int, to: Int) {
        if (doc.textLength == 0 || from < 1 || to < from || to > doc.lineCount) {
            throw WyspError(
                ErrorCode.TARGET_NOT_FOUND,
                "$path has ${doc.lineCount} lines; there are no lines $from-$to",
                mapOf("lines" to doc.lineCount),
            )
        }
    }

    /** Same text, ignoring line-ending style and trailing spaces (what a model reproduces reliably). */
    fun same(a: String, b: String): Boolean = norm(a) == norm(b)
    fun norm(s: String): String = s.replace("\r\n", "\n").split("\n").joinToString("\n") { it.trimEnd() }.trimEnd('\n')

    /** The text of lines `from..to`, which must still be what the caller saw (a stale edit changes nothing). */
    fun requireCurrent(doc: Document, path: String, from: Int, to: Int, expected: String) {
        checkLines(doc, path, from, to)
        val current = doc.getText(TextRange(doc.getLineStartOffset(from - 1), doc.getLineEndOffset(to - 1)))
        if (!same(current, expected)) {
            throw WyspError(
                ErrorCode.PRECONDITION_FAILED,
                "lines $from-$to of $path are not what old_text says (the file changed, or the line numbers are off). " +
                    "Nothing was changed. Current text:\n" + Privacy.bound(numbered(doc, from, to), 2_000),
            )
        }
    }

    /** A unified-diff-like text: " context", "-removed", "+added" (at most 60 lines). */
    fun diff(before: List<String>, removed: List<String>, added: List<String>, after: List<String>): String {
        val lines = before.takeLast(2).map { " $it" } + removed.map { "-$it" } + added.map { "+$it" } + after.take(2).map { " $it" }
        return if (lines.size <= 60) lines.joinToString("\n") else lines.take(60).joinToString("\n") + "\n …(${lines.size - 60} more lines)"
    }

    fun contextBefore(doc: Document, firstLine: Int): List<String> =
        ((maxOf(1, firstLine - 2)) until firstLine).map { lineText(doc, it) }

    fun contextAfter(doc: Document, lastLine: Int): List<String> =
        ((lastLine + 1)..minOf(doc.lineCount, lastLine + 2)).map { lineText(doc, it) }

    /** Shows the changed code to the student: opens the file with the caret at `line`. EDT. */
    fun reveal(project: Project, vf: VirtualFile, line: Int) {
        val editor = FileEditorManager.getInstance(project)
            .openTextEditor(OpenFileDescriptor(project, vf, maxOf(0, line - 1), 0), false) ?: return
        editor.scrollingModel.scrollToCaret(ScrollType.CENTER)
    }

    fun fileObserved() = listOf(
        mapOf("path" to "entities[?ref=='\${params.target}'] | length(@)", "op" to "gte", "value" to 1),
    )

    fun ref(path: String, from: Int, to: Int) = Refs.lines(path, from, to)

    /** New text as the document stores it: `\n` line ends, no single trailing newline (the lines replace whole lines). */
    fun cleanNew(s: String): String = s.replace("\r\n", "\n").removeSuffix("\n")

    fun intParam(params: Map<String, Any?>, key: String): Int? = (params[key] as? Number)?.toInt()
}

/** Text edits as one IDE command each (so Ctrl+Z works too), read back, with an undo that never overwrites newer work. */
object TextEdits {
    /** Runs `block` as one named command and commits the document so the PSI matches. EDT. */
    fun write(project: Project, doc: Document, name: String, block: () -> Unit) {
        WriteCommandAction.writeCommandAction(project).withName(name).run<RuntimeException> {
            PsiDocumentManager.getInstance(project).commitDocument(doc)
            block()
            PsiDocumentManager.getInstance(project).commitDocument(doc)
        }
    }

    /**
     * Replaces `[start, end)` with `newText`, reads the whole document back and restores it if it differs from
     * what was asked. Returns the undo: it puts the old text back only while the range still holds `newText`.
     */
    fun replace(project: Project, doc: Document, start: Int, end: Int, newText: String, name: String): () -> Unit {
        val before = doc.text
        val old = before.substring(start, end)
        val expected = before.substring(0, start) + newText + before.substring(end)
        write(project, doc, name) { doc.replaceString(start, end, newText) }
        if (doc.text != expected) {
            write(project, doc, "$name (restore)") { doc.setText(before) }
            throw WyspError(ErrorCode.EXECUTION_FAILED, "the editor did not end up with the requested text; the file was restored")
        }
        val marker = doc.createRangeMarker(start, start + newText.length)
        val after = doc.text
        return {
            // Undone in reverse order the document is exactly as this edit left it: the recorded range is exact.
            // Otherwise (the user kept typing) follow the range marker, and refuse if the code there changed.
            val range = if (doc.text == after) {
                start to start + newText.length
            } else if (marker.isValid && doc.getText(TextRange(marker.startOffset, marker.endOffset)) == newText) {
                marker.startOffset to marker.endOffset
            } else {
                throw WyspError(ErrorCode.UNDO_UNAVAILABLE, "the code changed since; nothing was overwritten (use Ctrl+Z in the editor)")
            }
            write(project, doc, "$name (undo)") { doc.replaceString(range.first, range.second, old) }
            marker.dispose()
        }
    }

    /** For tools that rewrite a document in place (reformat, imports). Returns null when nothing changed. */
    fun rewrite(project: Project, doc: Document, name: String, op: () -> Unit): (() -> Unit)? {
        val before = doc.text
        write(project, doc, name) { op() }
        val after = doc.text
        if (after == before) return null
        return {
            if (doc.text != after) {
                throw WyspError(ErrorCode.UNDO_UNAVAILABLE, "the file changed since; nothing was overwritten (use Ctrl+Z in the editor)")
            }
            write(project, doc, "$name (undo)") { doc.setText(before) }
        }
    }
}
