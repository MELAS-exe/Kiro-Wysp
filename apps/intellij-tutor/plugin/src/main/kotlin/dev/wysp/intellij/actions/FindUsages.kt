package dev.wysp.intellij.actions

import com.intellij.openapi.project.DumbService
import com.intellij.openapi.project.Project
import com.intellij.psi.search.GlobalSearchScope
import com.intellij.psi.search.searches.ReferencesSearch
import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.Observer
import dev.wysp.intellij.Privacy
import dev.wysp.intellij.WyspError

/** find_usages: where a symbol is used, from the IDE's own reference search. */
class FindUsages : WyspAction {
    override val spec = actionSpec(
        "find_usages",
        "Find usages of a symbol",
        "List where a class, function or field is used in the project (file, line and the line's text), with the " +
            "IDE's reference search. At most ${CodeAccess.MAX_RESULTS} usages. Use mode 'do': nothing changes and no " +
            "approval is asked.",
        mapOf("target" to SYMBOL_REF),
        listOf("target"),
        "read_only",
        emptyList(),
        emptyList(),
    )

    override fun resolve(project: Project, params: Map<String, Any?>): Any {
        if (DumbService.isDumb(project)) throw WyspError(ErrorCode.BUSY, "the IDE is indexing; try again in a moment")
        val (path, _, symbol) = resolveSymbol(project, params["target"] as String)
        val observer = Observer(project)
        val rows = mutableListOf<String>()
        var more = 0
        for (ref in ReferencesSearch.search(symbol.element, GlobalSearchScope.projectScope(project)).findAll()) {
            val file = ref.element.containingFile?.virtualFile ?: continue
            val rel = observer.relPath(file) ?: continue
            if (Observer.isNoise(rel) || Privacy.isSensitivePath(rel)) continue
            if (rows.size >= CodeAccess.MAX_RESULTS) {
                more++
                continue
            }
            val doc = com.intellij.openapi.fileEditor.FileDocumentManager.getInstance().getDocument(file) ?: continue
            val line = doc.getLineNumber(ref.element.textOffset) + 1
            rows += "$rel:$line: ${Privacy.oneLine(CodeAccess.lineText(doc, line), 160)}"
        }
        val head = "${symbol.parts.joinToString(".")} (declared in $path:${symbol.line}) is used ${rows.size + more} time(s)" +
            if (more > 0) ", first ${rows.size} shown" else ""
        return Privacy.bound((listOf(head) + rows).joinToString("\n"), CodeAccess.MAX_READ_CHARS)
    }

    override fun run(project: Project, params: Map<String, Any?>, resolved: Any?, dryRun: Boolean) =
        ActionOutcome(message = resolved as String)
}
