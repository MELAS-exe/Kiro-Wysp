package dev.wysp.intellij.actions

import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.psi.PsiManager
import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.Observer
import dev.wysp.intellij.Ref
import dev.wysp.intellij.Refs
import dev.wysp.intellij.SymbolInfo
import dev.wysp.intellij.Symbols
import dev.wysp.intellij.WyspError

/** What an action returns. `undo` runs on the EDT; `after` (refs of what changed) runs in a background read action. */
class ActionOutcome(
    val changed: List<String> = emptyList(),
    val undo: (() -> List<String>)? = null,
    val message: String? = null,
    val preview: Any? = null,
    val after: (() -> List<String>)? = null,
)

/**
 * One entry of the closed action catalog, run in two phases after the parameters were validated against
 * `spec.params_schema`: [resolve] finds the targets in a background read action (PSI and indexes are slow
 * operations, forbidden on the EDT), then [run] changes the IDE on the EDT. Nothing changes when `dryRun` is true.
 */
interface WyspAction {
    val spec: Map<String, Any?>
    fun resolve(project: Project, params: Map<String, Any?>): Any? = null
    fun run(project: Project, params: Map<String, Any?>, resolved: Any?, dryRun: Boolean): ActionOutcome
}

fun actionSpec(
    id: String,
    title: String,
    description: String,
    properties: Map<String, Any?>,
    required: List<String>,
    risk: String,
    postconditions: List<Map<String, Any?>>,
    uiPath: List<Map<String, Any?>>,
): Map<String, Any?> = linkedMapOf(
    "id" to id,
    "title" to mapOf("en" to title),
    "description" to description,
    "params_schema" to mapOf(
        "type" to "object",
        "properties" to properties,
        "required" to required,
        "additionalProperties" to false,
    ),
    "risk" to risk,
    "reversible" to (risk == "reversible"),
    "preconditions" to emptyList<Any>(),
    "postconditions" to postconditions,
    "guide" to mapOf("ui_path" to uiPath),
)

val FILE_REF = mapOf(
    "type" to "string",
    "pattern" to Refs.FILE_PATTERN,
    "description" to "Ref of a project file, e.g. intellij://file/src/main/kotlin/Main.kt",
)
val SYMBOL_REF = mapOf(
    "type" to "string",
    "pattern" to Refs.SYMBOL_PATTERN,
    "description" to "Ref of a symbol from the observation, e.g. intellij://file/src/main/kotlin/Main.kt#Greeter.greet",
)

fun step(text: String, target: String? = null): Map<String, Any?> =
    if (target == null) mapOf("text" to text) else mapOf("text" to text, "target" to target)

fun resolveFile(project: Project, ref: String): Pair<String, VirtualFile> {
    val path = when (val r = Refs.parse(ref)) {
        is Ref.File -> r.path
        is Ref.Symbol -> r.path
        else -> throw WyspError(ErrorCode.TARGET_NOT_FOUND, "not a file ref: $ref")
    }
    val vf = Observer(project).resolve(path)
    if (vf == null || vf.isDirectory) throw WyspError(ErrorCode.TARGET_NOT_FOUND, "no file $path in the project")
    return path to vf
}

/** Resolves a symbol ref; call with read access (the EDT has it). */
fun resolveSymbol(project: Project, ref: String): Triple<String, VirtualFile, SymbolInfo> {
    val r = Refs.parse(ref) as? Ref.Symbol ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "not a symbol ref: $ref")
    val (path, vf) = resolveFile(project, ref)
    val psi = PsiManager.getInstance(project).findFile(vf) ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "cannot read $path")
    val symbols = Symbols.collect(psi)
    val s = Symbols.find(symbols, r.parts)
        ?: throw WyspError(
            ErrorCode.TARGET_NOT_FOUND,
            "no symbol ${r.qualifiedName} in $path",
            mapOf("symbols" to symbols.take(40).map { it.parts.joinToString(".") }),
        )
    return Triple(path, vf, s)
}
