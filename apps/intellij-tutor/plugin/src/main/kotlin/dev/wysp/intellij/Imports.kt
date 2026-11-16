package dev.wysp.intellij

import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.psi.search.FilenameIndex
import com.intellij.psi.search.GlobalSearchScope

/**
 * Which project files does a file import? Read from the import lines (Java, Kotlin, Python) and resolved to files
 * through the IDE's file-name index, so the project's own dependencies appear and libraries do not. Pure text work
 * ([names]) is separate from the index lookup ([resolve]) so it can be tested without an IDE.
 */
object Imports {
    const val MAX_PER_FILE = 40
    private const val MAX_SCANNED_CHARS = 20_000

    private val JVM = Regex("""^\s*import\s+(?:static\s+)?([A-Za-z_][\w.]*?)(?:\.\*)?(?:\s+as\s+\w+)?\s*;?\s*$""", RegexOption.MULTILINE)
    private val PY_FROM = Regex("""^\s*from\s+(\.*[\w.]*)\s+import\s""", RegexOption.MULTILINE)
    private val PY_IMPORT = Regex("""^\s*import\s+([\w.]+)""", RegexOption.MULTILINE)

    /** Dotted names imported by `text`, in order, without duplicates. `extension` is the file's, lower case. */
    fun names(extension: String, text: String): List<String> {
        val head = text.take(MAX_SCANNED_CHARS)
        val found = when (extension) {
            "java", "kt", "kts", "groovy", "scala" -> JVM.findAll(head).map { it.groupValues[1] }
            "py" -> PY_FROM.findAll(head).map { it.groupValues[1].trimStart('.') } + PY_IMPORT.findAll(head).map { it.groupValues[1] }
            else -> emptySequence()
        }
        return found.filter { it.isNotBlank() }.distinct().take(MAX_PER_FILE * 3).toList()
    }

    /** Candidate (path suffix, file name) pairs for a dotted name: the name itself, then without its last part (a member). */
    fun candidates(extension: String, dotted: String): List<Pair<String, String>> {
        val parts = listOf(dotted, dotted.substringBeforeLast('.', "")).filter { it.isNotEmpty() }.distinct()
        val exts = if (extension == "py") listOf("py") else listOf("java", "kt")
        return parts.flatMap { name ->
            val path = name.replace('.', '/')
            exts.map { e -> "$path.$e" to "${name.substringAfterLast('.')}.$e" } +
                if (extension == "py") listOf("$path/__init__.py" to "__init__.py") else emptyList()
        }
    }

    /** Project files imported by `file` (needs smart mode: the caller checks). */
    fun resolve(project: Project, file: VirtualFile, text: String): List<VirtualFile> {
        val ext = file.extension?.lowercase() ?: return emptyList()
        val scope = GlobalSearchScope.projectScope(project)
        val out = LinkedHashSet<VirtualFile>()
        for (name in names(ext, text)) {
            if (out.size >= MAX_PER_FILE) break
            for ((suffix, simple) in candidates(ext, name)) {
                val hit = FilenameIndex.getVirtualFilesByName(simple, scope).firstOrNull { it.path.endsWith("/$suffix") }
                if (hit != null) {
                    if (hit != file) out += hit
                    break
                }
            }
        }
        return out.toList()
    }
}
