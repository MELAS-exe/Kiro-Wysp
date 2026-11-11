package dev.wysp.intellij

import com.intellij.codeInsight.daemon.impl.DaemonCodeAnalyzerEx
import com.intellij.codeInsight.daemon.impl.HighlightInfo
import com.intellij.execution.RunManager
import com.intellij.lang.annotation.HighlightSeverity
import com.intellij.openapi.editor.Document
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.module.ModuleManager
import com.intellij.openapi.module.ModuleType
import com.intellij.openapi.project.DumbService
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.guessProjectDir
import com.intellij.openapi.vfs.VfsUtilCore
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.wm.ToolWindowManager
import com.intellij.psi.PsiManager
import dev.wysp.intellij.json.Json
import java.time.Instant
import java.util.UUID

/** What the user is looking at, captured on the EDT (editor state is UI state). */
class EditorSnapshot(
    val file: VirtualFile?,
    val caret: Int,
    val selectionStart: Int,
    val selectionEnd: Int,
    val openFiles: List<VirtualFile>,
    val activeToolWindow: String?,
) {
    companion object {
        /** Call on the EDT. */
        fun capture(project: Project): EditorSnapshot {
            val fem = FileEditorManager.getInstance(project)
            val editor = fem.selectedTextEditor
            val file = editor?.virtualFile ?: fem.selectedFiles.firstOrNull()
            val sel = editor?.selectionModel
            return EditorSnapshot(
                file = file,
                caret = editor?.caretModel?.offset ?: -1,
                selectionStart = if (sel?.hasSelection() == true) sel.selectionStart else -1,
                selectionEnd = if (sel?.hasSelection() == true) sel.selectionEnd else -1,
                openFiles = fem.openFiles.toList(),
                activeToolWindow = ToolWindowManager.getInstance(project).activeToolWindowId,
            )
        }
    }
}

/** Builds observations and context. Every method runs inside a read action. */
class Observer(private val project: Project) {
    private val base: VirtualFile? = project.guessProjectDir()

    fun relPath(file: VirtualFile): String? {
        val b = base ?: return null
        return VfsUtilCore.getRelativePath(file, b, '/')?.takeIf { it.isNotEmpty() }
    }

    fun resolve(path: String): VirtualFile? = base?.findFileByRelativePath(path)

    private class Collector(val limit: Int) {
        val entities = ArrayList<Map<String, Any?>>()
        val refs = HashSet<String>()
        val counts = LinkedHashMap<String, Int>()
        var truncated = false

        fun add(ref: String, kind: String, label: String, parent: String?, props: Map<String, Any?>): Boolean {
            counts.merge(kind, 1, Int::plus)
            if (ref in refs) return true
            if (entities.size >= limit || (parent != null && parent !in refs)) {
                truncated = true
                return false
            }
            refs += ref
            entities += buildMap {
                put("ref", ref)
                put("kind", kind)
                put("label", label)
                if (parent != null) put("parent", parent)
                put("props", props)
            }
            return true
        }
    }

    fun observe(scope: Map<String, Any?>, snap: EditorSnapshot, stateVersion: Long): Map<String, Any?> {
        val level = scope["level"] as? String ?: "focus"
        val root = scope["root"] as? String
        val c = Collector(MAX_ENTITIES)
        val projectRef = Refs.project(project.name)
        val dumb = DumbService.isDumb(project)
        val modules = ModuleManager.getInstance(project).modules
        c.add(projectRef, "project", project.name, null, mapOf("modules" to modules.size, "dumb_mode" to dumb))
        for (m in modules.sortedBy { it.name }) {
            c.add(Refs.module(m.name), "module", m.name, projectRef, mapOf("type" to ModuleType.get(m).id))
        }
        base?.children?.filter { it.isDirectory && !hidden(it.name) }?.sortedBy { it.name }?.forEach { dir ->
            addDir(c, dir, projectRef)
        }

        // Files: the current one first, then the other open ones, then the root of the scope.
        val files = LinkedHashSet<VirtualFile>()
        snap.file?.let { files += it }
        files += snap.openFiles
        val rootFile = root?.let { Refs.parse(it) }?.let { r ->
            when (r) {
                is Ref.File -> resolve(r.path)
                is Ref.Symbol -> resolve(r.path)
                is Ref.Problem -> resolve(r.path)
                else -> null
            }
        }
        rootFile?.let { files += it }
        val focus = mutableListOf<String>()
        val symbolFiles = when (level) {
            "summary" -> emptySet()
            "full" -> files
            else -> setOfNotNull(snap.file, rootFile)
        }
        for (vf in files) {
            val path = relPath(vf) ?: continue
            if (vf.isDirectory) continue
            val parentRef = dirChain(c, vf.parent, projectRef)
            val doc = FileDocumentManager.getInstance().getCachedDocument(vf) ?: FileDocumentManager.getInstance().getDocument(vf)
            val sensitive = Privacy.isSensitivePath(path)
            val fileRef = Refs.file(path)
            c.add(fileRef, "file", vf.name, parentRef, mapOf(
                "language" to vf.fileType.name,
                "lines" to (doc?.lineCount ?: 0),
                "open" to (vf in snap.openFiles),
                "modified" to FileDocumentManager.getInstance().isFileModified(vf),
                "sensitive" to sensitive,
            ))
            if (vf == snap.file) focus += fileRef
            if (vf !in symbolFiles || sensitive) continue
            val psi = PsiManager.getInstance(project).findFile(vf) ?: continue
            val symbols = if (dumb) emptyList() else runCatching { Symbols.collect(psi) }.getOrDefault(emptyList())
            for (s in symbols) {
                val parent = s.parentParts?.let { Refs.symbol(path, it) } ?: fileRef
                c.add(Refs.symbol(path, s.parts), "symbol", s.name, parent, mapOf(
                    "type" to s.type, "line" to s.line, "end_line" to s.endLine, "signature" to s.signature,
                ))
            }
            if (vf == snap.file && snap.caret >= 0) {
                Symbols.at(symbols, snap.caret)?.let { focus += Refs.symbol(path, it.parts) }
            }
            if (doc != null) addProblems(c, doc, path, fileRef)
        }

        if (level != "summary") {
            val rm = RunManager.getInstance(project)
            val selected = rm.selectedConfiguration
            for (s in rm.allSettings) {
                c.add(Refs.run(s.name), "run_config", s.name, projectRef, mapOf(
                    "type" to s.type.displayName, "selected" to (s == selected),
                ))
            }
        }

        val obs = linkedMapOf<String, Any?>(
            "observation_id" to "obs-" + UUID.randomUUID().toString().substring(0, 8),
            "state_version" to stateVersion,
            "captured_at" to Instant.now().toString(),
            "scope" to buildMap {
                put("level", level)
                if (root != null) put("root", root)
            },
            "entities" to c.entities,
            "links" to emptyList<Any>(),
            "focus" to focus.filter { it in c.refs },
            "truncated" to c.truncated,
            "counts" to c.counts,
        )
        // Stay under the contract's 256 KB: drop trailing entities (symbols and problems come last).
        while (Json.write(obs).length > MAX_BYTES && c.entities.size > 1) {
            val dropped = c.entities.removeAt(c.entities.size - 1)
            c.refs -= dropped["ref"] as String
            obs["truncated"] = true
            obs["focus"] = focus.filter { it in c.refs }
        }
        return obs
    }

    private fun hidden(name: String) = isNoise(name)

    private fun addDir(c: Collector, dir: VirtualFile, parentRef: String): String? {
        val path = relPath(dir) ?: return null
        val ref = Refs.dir(path)
        return if (c.add(ref, "directory", dir.name, parentRef, emptyMap())) ref else null
    }

    /** Adds the directories from the project root down to `dir`; returns the ref the file hangs on. */
    private fun dirChain(c: Collector, dir: VirtualFile?, projectRef: String): String {
        val b = base ?: return projectRef
        if (dir == null || dir == b) return projectRef
        val chain = generateSequence(dir) { it.parent }.takeWhile { it != b }.toList().asReversed()
        if (chain.isEmpty() || chain.first().parent != b) return projectRef // outside the project
        var parent = projectRef
        for (d in chain) parent = addDir(c, d, parent) ?: return parent
        return parent
    }

    private fun problems(doc: Document): List<HighlightInfo> {
        val out = mutableListOf<HighlightInfo>()
        DaemonCodeAnalyzerEx.processHighlights(doc, project, HighlightSeverity.WARNING, 0, doc.textLength) { info ->
            if (info.description != null) out += info
            out.size < MAX_PROBLEMS_PER_FILE
        }
        return out.distinctBy { it.startOffset to it.description }
    }

    private fun addProblems(c: Collector, doc: Document, path: String, fileRef: String) {
        val perLine = HashMap<Int, Int>()
        for (info in problems(doc)) {
            val line = doc.getLineNumber(info.startOffset.coerceIn(0, doc.textLength)) + 1
            val n = perLine.merge(line, 1, Int::plus)!!
            val message = Privacy.oneLine(info.description.orEmpty(), Privacy.MAX_MESSAGE)
            c.add(Refs.problem(path, line, n), "problem", Privacy.oneLine(message, 80), fileRef, mapOf(
                "severity" to info.severity.name, "message" to message, "line" to line,
            ))
        }
    }

    /** Problem ranges, for highlighting a problem ref. */
    fun problemRange(doc: Document, line: Int, n: Int): IntRange? {
        var k = 0
        for (info in problems(doc)) {
            if (doc.getLineNumber(info.startOffset.coerceIn(0, doc.textLength)) + 1 != line) continue
            if (++k == n) return info.startOffset until maxOf(info.endOffset, info.startOffset + 1)
        }
        return null
    }

    // ------------------------------------------------------------------------------------------- context
    fun context(snap: EditorSnapshot): Map<String, Any?> {
        val dumb = DumbService.isDumb(project)
        val facts = linkedMapOf<String, Any?>("project" to project.name, "dumb_mode" to dumb)
        val focus = mutableListOf<String>()
        val vf = snap.file
        val path = vf?.let { relPath(it) }
        var where = "no file open"
        if (vf != null && path == null) {
            facts["file"] = vf.name
            facts["outside_project"] = true
            where = "viewing ${vf.name} (outside the project)"
        }
        if (vf != null && path != null) {
            val fileRef = Refs.file(path)
            focus += fileRef
            facts["file"] = path
            facts["language"] = vf.fileType.name
            val sensitive = Privacy.isSensitivePath(path)
            facts["sensitive_file"] = sensitive
            val doc = FileDocumentManager.getInstance().getDocument(vf)
            where = "editing $path"
            if (doc != null && snap.caret >= 0) {
                val caret = snap.caret.coerceIn(0, doc.textLength)
                val line = doc.getLineNumber(caret)
                facts["caret"] = mapOf("line" to line + 1, "column" to caret - doc.getLineStartOffset(line) + 1)
                where += " at line ${line + 1}"
                if (!sensitive) {
                    if (snap.selectionStart in 0 until snap.selectionEnd && snap.selectionEnd <= doc.textLength) {
                        facts["selection"] = Privacy.bound(doc.getText(com.intellij.openapi.util.TextRange(snap.selectionStart, snap.selectionEnd)), Privacy.MAX_SELECTION)
                    }
                    val psi = PsiManager.getInstance(project).findFile(vf)
                    val symbols = if (psi == null || dumb) emptyList() else runCatching { Symbols.collect(psi) }.getOrDefault(emptyList())
                    val at = Symbols.at(symbols, caret, setOf("function", "class", "interface")) ?: Symbols.at(symbols, caret)
                    if (at != null) {
                        val symRef = Refs.symbol(path, at.parts)
                        focus += symRef
                        facts["symbol_at_caret"] = mapOf("ref" to symRef, "name" to at.parts.joinToString("."), "type" to at.type)
                        where += ", in ${at.parts.joinToString(".")}"
                        facts["code_at_caret"] = Privacy.bound(
                            doc.getText(com.intellij.openapi.util.TextRange(at.startOffset, at.endOffset.coerceAtMost(doc.textLength))),
                            Privacy.MAX_CODE_AT_CARET,
                        )
                    } else {
                        val from = doc.getLineStartOffset(maxOf(0, line - 12))
                        val to = doc.getLineEndOffset(minOf(doc.lineCount - 1, line + 12))
                        facts["code_near_caret"] = Privacy.bound(doc.getText(com.intellij.openapi.util.TextRange(from, to)), Privacy.MAX_CODE_AT_CARET)
                    }
                    facts["problems_in_file"] = problems(doc).size
                }
            }
        }
        facts["open_files"] = snap.openFiles.mapNotNull { relPath(it) }.take(20)
        snap.activeToolWindow?.let { facts["active_tool_window"] = it }
        val summary = "IntelliJ project ${project.name}: $where" + if (dumb) " (the IDE is indexing)" else ""
        return mapOf(
            "summary" to summary,
            "mode" to if (dumb) "indexing" else if (vf != null) "editing" else "browsing",
            "focus" to focus,
            "facts" to facts,
        )
    }

    companion object {
        const val MAX_ENTITIES = 500
        const val MAX_BYTES = 250_000
        const val MAX_PROBLEMS_PER_FILE = 40
        private val NOISE = setOf("build", "out", "target", "node_modules", "__pycache__")

        /** IDE settings (.idea), VCS data and build output: not the student's code, never observed or reported. */
        fun isNoise(pathOrName: String): Boolean = pathOrName.split('/').any { it.startsWith(".") || it in NOISE }
    }
}
