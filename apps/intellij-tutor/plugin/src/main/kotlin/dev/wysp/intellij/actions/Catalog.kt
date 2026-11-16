package dev.wysp.intellij.actions

import com.intellij.openapi.project.Project
import dev.wysp.intellij.ErrorCode
import dev.wysp.intellij.Schema
import dev.wysp.intellij.WyspError
import java.util.concurrent.atomic.AtomicLong

/**
 * The closed, declarative catalog. Nothing here runs code, scripts, run configurations or arbitrary IDE
 * action ids. Keeps undo records for reversible actions (bounded).
 */
class Catalog {
    val actions: List<WyspAction> = listOf(
        OpenFile(), GoToSymbol(), ShowToolWindow(), RenameSymbol(),
        ReadCode(), SearchCode(), FindUsages(), ListFiles(),
        ReplaceLines(), InsertLines(), CreateFile(), ReformatCode(), OptimizeImports(),
    )
    private val byId = actions.associateBy { it.spec["id"] as String }
    private val undo = object : LinkedHashMap<String, () -> List<String>>() {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, () -> List<String>>?) = size > 100
    }
    private val counter = AtomicLong()

    fun specs(): List<Map<String, Any?>> = actions.map { it.spec }

    /** Checks the call before touching the IDE: unknown action and invalid parameters change nothing. */
    fun prepare(call: Map<String, Any?>): Pair<WyspAction, Map<String, Any?>> {
        val id = call["action_id"] as? String ?: throw WyspError(ErrorCode.INVALID_PARAMS, "missing action_id")
        val action = byId[id] ?: throw WyspError(ErrorCode.ACTION_NOT_FOUND, "unknown action '$id'")
        @Suppress("UNCHECKED_CAST")
        val params = call["params"] as? Map<String, Any?> ?: emptyMap()
        @Suppress("UNCHECKED_CAST")
        val problems = Schema.validate(params, action.spec["params_schema"] as Map<String, Any?>)
        if (problems.isNotEmpty()) throw WyspError(ErrorCode.INVALID_PARAMS, "invalid parameters", mapOf("problems" to problems))
        return action to params
    }

    /** Phase 2, on the EDT: returns the ActionResult (without state_version) and the optional phase 3. */
    fun execute(project: Project, action: WyspAction, params: Map<String, Any?>, resolved: Any?, dryRun: Boolean): Executed {
        val outcome = try {
            action.run(project, params, resolved, dryRun)
        } catch (e: WyspError) {
            throw e
        } catch (e: Exception) {
            throw WyspError(ErrorCode.EXECUTION_FAILED, "${e::class.java.simpleName}: ${e.message}")
        }
        val result = linkedMapOf<String, Any?>("status" to "ok", "changed" to if (dryRun) emptyList() else outcome.changed)
        if (!dryRun && action.spec["reversible"] == true && outcome.undo != null) {
            val token = "u-${counter.incrementAndGet()}"
            synchronized(undo) { undo[token] = outcome.undo }
            result["undo_token"] = token
        }
        outcome.message?.let { result["message"] = it }
        outcome.preview?.let { result["preview"] = it }
        return Executed(result, if (dryRun) null else outcome.after)
    }

    /** Phase 3, in a background read action: adds the refs computed after the change. */
    fun finish(executed: Executed): MutableMap<String, Any?> {
        val more = executed.after?.let { runCatching(it).getOrDefault(emptyList()) }.orEmpty()
        if (more.isNotEmpty()) {
            @Suppress("UNCHECKED_CAST")
            executed.result["changed"] = ((executed.result["changed"] as List<String>) + more).distinct()
        }
        return executed.result
    }

    class Executed(val result: MutableMap<String, Any?>, val after: (() -> List<String>)?)

    /** All three phases on the calling thread (tests, which run on the EDT with read access). */
    fun runAll(project: Project, action: WyspAction, params: Map<String, Any?>, dryRun: Boolean): MutableMap<String, Any?> =
        finish(execute(project, action, params, action.resolve(project, params), dryRun))

    /** Runs on the EDT. */
    fun undo(token: String): Map<String, Any?> {
        val fn = synchronized(undo) { undo.remove(token) } ?: throw WyspError(ErrorCode.UNDO_UNAVAILABLE, "unknown or expired undo token")
        val changed = try {
            fn()
        } catch (e: WyspError) {
            if (e.code == ErrorCode.BUSY) synchronized(undo) { undo[token] = fn } // indexing: the undo can be retried
            throw e
        } catch (e: Exception) {
            throw WyspError(ErrorCode.EXECUTION_FAILED, "undo failed: ${e.message}")
        }
        return linkedMapOf("status" to "ok", "changed" to changed)
    }
}
