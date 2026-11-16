package dev.wysp.intellij.actions

import com.intellij.openapi.project.Project
import com.intellij.openapi.project.guessProjectDir
import com.intellij.openapi.vfs.VirtualFile
import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.Observer
import dev.wysp.intellij.Privacy
import dev.wysp.intellij.Ref
import dev.wysp.intellij.Refs
import dev.wysp.intellij.WyspError

/** list_files: the entries of one project directory (names only: sensitive files are listed but never read). */
class ListFiles : WyspAction {
    override val spec = actionSpec(
        "list_files",
        "List files",
        "List the files and folders of a project directory (the project root when 'target' is omitted). Shows " +
            "names only; IDE settings, VCS data and build output are left out. Use mode 'do': nothing changes and no " +
            "approval is asked.",
        mapOf(
            "target" to mapOf(
                "type" to "string",
                "pattern" to "^intellij://dir/.+$",
                "description" to "Ref of a directory, e.g. intellij://dir/src/main/java. Omit for the project root.",
            ),
        ),
        emptyList(),
        "read_only",
        emptyList(),
        emptyList(),
    )

    override fun resolve(project: Project, params: Map<String, Any?>): Any {
        val observer = Observer(project)
        val ref = params["target"] as? String
        val dir: VirtualFile
        val shown: String
        if (ref == null) {
            dir = project.guessProjectDir() ?: throw WyspError(ErrorCode.PRECONDITION_FAILED, "the project has no base directory")
            shown = "."
        } else {
            val parsed = Refs.parse(ref) as? Ref.Dir ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "not a directory ref: $ref")
            dir = observer.resolve(parsed.path)?.takeIf { it.isDirectory }
                ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "no directory ${parsed.path} in the project")
            shown = parsed.path
            if (Observer.isNoise(shown)) throw WyspError(ErrorCode.PRECONDITION_FAILED, "$shown is IDE settings, VCS data or build output")
        }
        val children = dir.children.filter { !Observer.isNoise(it.name) }.sortedWith(compareBy({ !it.isDirectory }, { it.name.lowercase() }))
        val rows = children.take(100).map { c ->
            val rel = observer.relPath(c) ?: c.name
            when {
                c.isDirectory -> "dir   ${Refs.dir(rel)}"
                Privacy.isSensitivePath(rel) -> "file  ${Refs.file(rel)}  (sensitive: never read)"
                else -> "file  ${Refs.file(rel)}  ${c.length} bytes"
            }
        }
        val head = "$shown: ${children.size} entr${if (children.size == 1) "y" else "ies"}" + if (children.size > 100) ", first 100 shown" else ""
        return Privacy.bound((listOf(head) + rows).joinToString("\n"), CodeAccess.MAX_READ_CHARS)
    }

    override fun run(project: Project, params: Map<String, Any?>, resolved: Any?, dryRun: Boolean) =
        ActionOutcome(message = resolved as String)
}
