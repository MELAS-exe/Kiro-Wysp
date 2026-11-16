package dev.wysp.intellij.actions

import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.guessProjectDir
import com.intellij.openapi.vfs.VfsUtil
import com.intellij.openapi.vfs.VfsUtilCore
import com.intellij.openapi.vfs.VirtualFile
import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.Observer
import dev.wysp.intellij.Ref
import dev.wysp.intellij.Refs
import dev.wysp.intellij.WyspError

/** create_file: a new text file inside the project. It never overwrites; undo deletes it (only while untouched). */
class CreateFile : WyspAction {
    override val spec = actionSpec(
        "create_file",
        "Create a file",
        "Create a new text file in the project with the given text (missing folders are created). Fails when the " +
            "file already exists. Not for sensitive files or IDE or build folders. The user sees the text and must " +
            "approve; the change can be undone. In a Git project the IDE then asks the student whether to add the " +
            "file to Git: tell them to answer it, other actions wait until they do.",
        mapOf(
            "target" to mapOf(
                "type" to "string",
                "pattern" to Refs.FILE_PATTERN,
                "description" to "Ref of the new file, e.g. intellij://file/src/main/java/dev/app/Util.java",
            ),
            "text" to mapOf("type" to "string", "maxLength" to CodeAccess.MAX_EDIT_CHARS, "description" to "The content"),
        ),
        listOf("target", "text"),
        "reversible",
        CodeAccess.fileObserved(),
        listOf(
            step("Right-click the folder in the Project view and choose New > File (Alt+Insert)", "intellij://ui/toolwindow/Project"),
            step("Name it “\${params.target}” and type its content"),
        ),
    )

    private class Plan(val path: String, val text: String)

    override fun resolve(project: Project, params: Map<String, Any?>): Any {
        val ref = Refs.parse(params["target"] as String) as? Ref.File
            ?: throw WyspError(ErrorCode.INVALID_PARAMS, "target must be an intellij://file/<path> ref")
        CodeAccess.refuse(ref.path)
        if (Observer(project).resolve(ref.path) != null) {
            throw WyspError(ErrorCode.PRECONDITION_FAILED, "${ref.path} already exists; use replace_lines or insert_lines")
        }
        return Plan(ref.path, (params["text"] as String).replace("\r\n", "\n"))
    }

    override fun run(project: Project, params: Map<String, Any?>, resolved: Any?, dryRun: Boolean): ActionOutcome {
        val p = resolved as Plan
        val base = project.guessProjectDir() ?: throw WyspError(ErrorCode.PRECONDITION_FAILED, "the project has no base directory")
        if (base.findFileByRelativePath(p.path) != null) {
            throw WyspError(ErrorCode.PRECONDITION_FAILED, "${p.path} already exists")
        }
        val lines = if (p.text.isEmpty()) emptyList() else p.text.removeSuffix("\n").split("\n")
        if (dryRun) {
            return ActionOutcome(preview = mapOf("file" to p.path, "lines" to "new file, ${lines.size} line(s)", "diff" to CodeAccess.diff(emptyList(), emptyList(), lines, emptyList())))
        }
        val segments = p.path.split('/')
        val createdDirs = mutableListOf<VirtualFile>()
        var created: VirtualFile? = null
        WriteCommandAction.writeCommandAction(project).withName("Wysp: create ${p.path}").run<RuntimeException> {
            var dir = base
            for (seg in segments.dropLast(1)) {
                dir = dir.findChild(seg) ?: dir.createChildDirectory(this@CreateFile, seg).also { createdDirs += it }
                if (!dir.isDirectory) throw WyspError(ErrorCode.PRECONDITION_FAILED, "$seg is a file, not a folder")
            }
            val file = dir.createChildData(this@CreateFile, segments.last())
            VfsUtil.saveText(file, p.text)
            created = file
        }
        val file = created ?: throw WyspError(ErrorCode.EXECUTION_FAILED, "the file was not created")
        val written = VfsUtilCore.loadText(file)
        if (!CodeAccess.same(written, p.text)) {
            WriteCommandAction.writeCommandAction(project).withName("Wysp: undo create ${p.path}").run<RuntimeException> { file.delete(this@CreateFile) }
            throw WyspError(ErrorCode.EXECUTION_FAILED, "the file did not end up with the requested text; it was removed")
        }
        CodeAccess.reveal(project, file, 1)
        return ActionOutcome(
            changed = listOf(Refs.file(p.path)),
            undo = {
                if (!file.isValid) throw WyspError(ErrorCode.UNDO_UNAVAILABLE, "${p.path} no longer exists")
                val doc = FileDocumentManager.getInstance().getDocument(file)
                if (doc == null || !CodeAccess.same(doc.text, p.text)) {
                    throw WyspError(ErrorCode.UNDO_UNAVAILABLE, "${p.path} was edited since; it was not deleted")
                }
                WriteCommandAction.writeCommandAction(project).withName("Wysp: undo create ${p.path}").run<RuntimeException> {
                    file.delete(this@CreateFile)
                    for (d in createdDirs.asReversed()) if (d.isValid && d.children.isEmpty()) d.delete(this@CreateFile)
                }
                listOf(Refs.file(p.path))
            },
            message = "Created ${p.path} (${lines.size} line(s)). If the IDE asks whether to add it to Git, that question is the student's to answer in the IDE; other actions wait until it is answered.",
        )
    }
}
