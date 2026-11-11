package dev.wysp.intellij.actions

import com.intellij.lang.LanguageNamesValidation
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.OpenFileDescriptor
import com.intellij.openapi.project.DumbService
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.text.StringUtil
import com.intellij.psi.PsiElement
import com.intellij.psi.PsiNamedElement
import com.intellij.psi.SmartPointerManager
import com.intellij.psi.SmartPsiElementPointer
import com.intellij.refactoring.BaseRefactoringProcessor
import com.intellij.refactoring.rename.RenameProcessor
import com.intellij.refactoring.ui.ConflictsDialog
import com.intellij.usageView.UsageInfo
import com.intellij.util.containers.MultiMap
import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.Observer
import dev.wysp.intellij.Refs
import dev.wysp.intellij.Symbols
import dev.wysp.intellij.WyspError

/**
 * rename_symbol: the IDE's Rename refactoring (declaration and every usage) in one command. Reversible:
 * the undo renames the same element back with the same refactoring (a compensation, like Ctrl+Z would).
 */
class RenameSymbol : WyspAction {
    override val spec = actionSpec(
        "rename_symbol",
        "Rename a symbol",
        "Rename a class, function, field or variable with the IDE's Rename refactoring, which also updates " +
            "every usage in the project. Fails with a description when the new name conflicts.",
        mapOf(
            "target" to SYMBOL_REF,
            "new_name" to mapOf(
                "type" to "string",
                "minLength" to 1,
                "maxLength" to 80,
                "pattern" to "^[A-Za-z_$][A-Za-z0-9_$]*$",
                "description" to "The new identifier",
            ),
        ),
        listOf("target", "new_name"),
        "reversible",
        listOf(
            mapOf(
                "path" to "entities[?kind=='symbol' && label=='\${params.new_name}'] | length(@)",
                "op" to "gte",
                "value" to 1,
            ),
        ),
        listOf(
            step("Put the caret on “\${label:params.target}” in the editor", "\${params.target}"),
            step("Press Shift+F6, or right-click and choose Refactor > Rename…"),
            step("Type \${params.new_name} and press Enter"),
        ),
    )

    private class Target(
        val path: String,
        val pointer: SmartPsiElementPointer<PsiElement>,
        val oldName: String,
        val language: String,
        val writable: Boolean,
    )

    /** Background read action: find the symbol, check the new name, keep a pointer that survives the rename. */
    override fun resolve(project: Project, params: Map<String, Any?>): Any {
        if (DumbService.isDumb(project)) throw WyspError(ErrorCode.BUSY, "the IDE is indexing; try again in a moment")
        val newName = params["new_name"] as String
        val (path, vf, symbol) = resolveSymbol(project, params["target"] as String)
        val element = symbol.element
        val named = element as? PsiNamedElement
            ?: throw WyspError(ErrorCode.PRECONDITION_FAILED, "${symbol.name} cannot be renamed")
        val validator = LanguageNamesValidation.INSTANCE.forLanguage(element.language)
        if (!validator.isIdentifier(newName, project) || validator.isKeyword(newName, project)) {
            throw WyspError(ErrorCode.INVALID_PARAMS, "'$newName' is not a valid identifier in ${element.language.displayName}")
        }
        val oldName = named.name ?: symbol.name
        if (newName == oldName) throw WyspError(ErrorCode.PRECONDITION_FAILED, "${symbol.name} is already called $newName")
        return Target(path, SmartPointerManager.createPointer(element), oldName, element.language.displayName, vf.isWritable)
    }

    override fun run(project: Project, params: Map<String, Any?>, resolved: Any?, dryRun: Boolean): ActionOutcome {
        val t = resolved as Target
        val newName = params["new_name"] as String
        if (!t.writable) throw WyspError(ErrorCode.PRECONDITION_FAILED, "${t.path} is read-only")
        if (dryRun) return ActionOutcome(preview = mapOf("would_rename" to t.oldName, "to" to newName, "in" to t.path))
        if (DumbService.isDumb(project)) throw WyspError(ErrorCode.BUSY, "the IDE is indexing; try again in a moment")
        val element = t.pointer.element ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "${t.oldName} changed before the rename")
        rename(project, element, newName)
        reveal(project, t.pointer)

        val undo = {
            val current = t.pointer.element
                ?: throw WyspError(ErrorCode.UNDO_UNAVAILABLE, "the renamed symbol no longer exists")
            if (DumbService.isDumb(project)) throw WyspError(ErrorCode.BUSY, "the IDE is indexing; try again in a moment")
            rename(project, current, t.oldName)
            reveal(project, t.pointer)
            listOf(Refs.file(t.path))
        }
        return ActionOutcome(
            changed = listOf(Refs.file(t.path)),
            undo = undo,
            message = "Renamed ${t.oldName} to $newName (declaration and usages)",
            after = { listOfNotNull(refOf(project, t.pointer), fileRefOf(project, t.pointer)) }, // a class rename may rename its file
        )
    }
    private class Conflicts(val messages: List<String>) : RuntimeException(messages.joinToString("; "))

    /** Runs the refactoring without dialogs; conflicts become a PRECONDITION_FAILED error. Call on the EDT. */
    private fun rename(project: Project, element: PsiElement, newName: String) {
        val processor = object : RenameProcessor(project, element, newName, false, false) {
            override fun showConflicts(conflicts: MultiMap<PsiElement, String>, usages: Array<out UsageInfo>?): Boolean {
                if (!conflicts.isEmpty) throw Conflicts(conflicts.values().map { StringUtil.removeHtmlTags(it) }.distinct())
                return true
            }

            // The IDE would open a modal Conflicts dialog here: report the conflicts to the tutor instead.
            override fun prepareConflictsDialog(conflicts: MultiMap<PsiElement, String>, usages: Array<out UsageInfo>?): ConflictsDialog =
                throw Conflicts(conflicts.values().map { StringUtil.removeHtmlTags(it) }.distinct())
        }
        processor.setPreviewUsages(false)
        try {
            processor.run()
        } catch (e: RuntimeException) {
            // The platform may wrap exceptions thrown from inside the refactoring (progress, write action);
            // in unit-test mode it throws its own ConflictsInTestsException before any dialog.
            val chain = generateSequence<Throwable>(e) { it.cause.takeIf { cause -> cause !== it } }.toList()
            val messages = chain.filterIsInstance<Conflicts>().firstOrNull()?.messages
                ?: chain.filterIsInstance<BaseRefactoringProcessor.ConflictsInTestsException>().firstOrNull()
                    ?.messages?.map { StringUtil.removeHtmlTags(it) }?.distinct()
                ?: throw e
            throw WyspError(ErrorCode.PRECONDITION_FAILED, "rename conflicts: ${messages.joinToString("; ")}", mapOf("conflicts" to messages))
        }
    }

    /** Puts the caret on the symbol so the user sees the result (EDT; the file's PSI is loaded by the rename). */
    private fun reveal(project: Project, pointer: SmartPsiElementPointer<PsiElement>) {
        val vf = pointer.virtualFile ?: return
        val offset = pointer.element?.textOffset ?: 0
        FileEditorManager.getInstance(project).openTextEditor(OpenFileDescriptor(project, vf, offset), false)
    }

    private fun fileRefOf(project: Project, pointer: SmartPsiElementPointer<PsiElement>): String? =
        pointer.virtualFile?.let { Observer(project).relPath(it) }?.let { Refs.file(it) }

    /** The symbol's ref after the rename (background read action: the structure view is a slow operation). */
    private fun refOf(project: Project, pointer: SmartPsiElementPointer<PsiElement>): String? {
        val element = pointer.element ?: return null
        val file = element.containingFile ?: return null
        val path = file.virtualFile?.let { Observer(project).relPath(it) } ?: return null
        val parts = Symbols.collect(file).firstOrNull { it.element == element }?.parts
        return parts?.let { Refs.symbol(path, it) } ?: Refs.file(path)
    }
}