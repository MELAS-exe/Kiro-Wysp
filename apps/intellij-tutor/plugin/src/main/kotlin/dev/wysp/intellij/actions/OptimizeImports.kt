package dev.wysp.intellij.actions

import com.intellij.lang.LanguageImportStatements
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.project.DumbService
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.psi.PsiManager
import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.Refs
import dev.wysp.intellij.WyspError

/** optimize_imports: remove unused imports and sort the rest, with the IDE's own import optimizer. */
class OptimizeImports : WyspAction {
    override val spec = actionSpec(
        "optimize_imports",
        "Optimize imports",
        "Remove the unused imports of a file and sort the others, with the IDE's import optimizer (for languages " +
            "that have one). The user must approve; the change can be undone.",
        mapOf("target" to FILE_REF),
        listOf("target"),
        "reversible",
        CodeAccess.fileObserved(),
        listOf(
            step("Open “\${label:params.target}”", "\${params.target}"),
            step("Press Ctrl+Alt+O (Code > Optimize Imports)"),
        ),
    )

    private class Plan(val path: String, val vf: VirtualFile, val steps: List<Runnable>)

    /** Background read action: the optimizer computes what to remove (slow PSI work); the EDT only applies it. */
    override fun resolve(project: Project, params: Map<String, Any?>): Any {
        if (DumbService.isDumb(project)) throw WyspError(ErrorCode.BUSY, "the IDE is indexing; try again in a moment")
        val (path, vf, _) = CodeAccess.readable(project, params["target"] as String)
        CodeAccess.writable(path, vf)
        val psi = PsiManager.getInstance(project).findFile(vf) ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "cannot read $path")
        val optimizers = LanguageImportStatements.INSTANCE.forFile(psi).filter { it.supports(psi) }
        if (optimizers.isEmpty()) throw WyspError(ErrorCode.PRECONDITION_FAILED, "$path (${psi.language.displayName}) has no import optimizer")
        return Plan(path, vf, optimizers.map { it.processFile(psi) })
    }

    override fun run(project: Project, params: Map<String, Any?>, resolved: Any?, dryRun: Boolean): ActionOutcome {
        val p = resolved as Plan
        if (dryRun) {
            return ActionOutcome(preview = mapOf("file" to p.path, "lines" to "imports", "diff" to " Unused imports will be removed and the rest sorted."))
        }
        val doc = FileDocumentManager.getInstance().getDocument(p.vf)
            ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "cannot read ${p.path}")
        val undo = TextEdits.rewrite(project, doc, "Wysp: optimize imports of ${p.path}") { p.steps.forEach { it.run() } }
        CodeAccess.reveal(project, p.vf, 1)
        return ActionOutcome(
            changed = listOf(Refs.file(p.path)),
            undo = {
                undo?.invoke()
                listOf(Refs.file(p.path))
            },
            message = if (undo == null) "The imports of ${p.path} were already tidy" else "Optimized the imports of ${p.path}",
        )
    }
}
