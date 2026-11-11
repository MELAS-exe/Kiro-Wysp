package dev.wysp.intellij

import com.intellij.notification.NotificationGroupManager
import com.intellij.notification.NotificationType
import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationInfo
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.application.ApplicationNamesInfo
import com.intellij.openapi.application.ModalityState
import com.intellij.openapi.application.ReadAction
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.service
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.ProjectManager
import com.intellij.openapi.wm.IdeFocusManager
import com.intellij.util.concurrency.AppExecutorUtil
import dev.wysp.intellij.actions.Catalog
import dev.wysp.intellij.json.Json
import dev.wysp.intellij.rpc.RpcClient
import dev.wysp.intellij.ui.WyspSettings
import java.util.concurrent.CompletableFuture
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

/**
 * The adapter: one connection to the Core per IDE, serving the active project.
 * Threading: observation and context run in non-blocking read actions on a pooled thread (after a short
 * EDT hop to capture the editor state); execute, undo and highlight run on the EDT; replies leave from
 * whichever thread finishes.
 */
@Service(Service.Level.APP)
class WyspService : Disposable {
    private val log = Logger.getInstance(WyspService::class.java)
    val catalog = Catalog()
    val origin = OriginTagger()
    private val stateVersion = AtomicLong(0)
    private val statusListeners = CopyOnWriteArrayList<(String, String?) -> Unit>()
    private var refusedNotified = false

    private val client = RpcClient(
        url = { WyspSettings.get().coreUrl },
        hello = { mapOf("manifest" to manifest(), "token" to (WyspSettings.get().readToken() ?: "")) },
        handler = ::handle,
        stateVersion = { stateVersion.get() },
        onStatus = ::statusChanged,
    )

    val connected: Boolean get() = client.connected
    val status: String get() = client.status
    val lastError: String? get() = client.lastError

    fun connect() {
        refusedNotified = false
        client.start()
    }

    fun disconnect() = client.stop()

    fun bump(): Long = stateVersion.incrementAndGet()

    fun notify(method: String, params: Map<String, Any?>) = client.notify(method, params)

    fun addStatusListener(parent: Disposable, listener: (String, String?) -> Unit) {
        statusListeners += listener
        com.intellij.openapi.util.Disposer.register(parent) { statusListeners -= listener }
    }

    private fun statusChanged(status: String, detail: String?) {
        log.info("Wysp adapter: $status${detail?.let { " ($it)" } ?: ""}")
        statusListeners.forEach { runCatching { it(status, detail) } }
        if (status == "refused" && !refusedNotified) {
            refusedNotified = true
            NotificationGroupManager.getInstance().getNotificationGroup(Wysp.NOTIFICATION_GROUP)
                .createNotification(
                    "Wysp Core refused the connection",
                    (detail ?: "") + "<br>Check that the token file (${WyspSettings.get().tokenPath}) belongs to the running Core.",
                    NotificationType.WARNING,
                )
                .notify(null)
        }
    }

    override fun dispose() = client.dispose()

    // ----------------------------------------------------------------------------------------- manifest
    fun manifest(): Map<String, Any?> = linkedMapOf(
        "adapter_id" to Wysp.ADAPTER_ID,
        "app" to mapOf(
            "name" to ApplicationNamesInfo.getInstance().fullProductName,
            "version" to ApplicationInfo.getInstance().fullVersion,
        ),
        "contract_version" to Wysp.CONTRACT_VERSION,
        "integration_level" to "native",
        "ref_scheme" to Wysp.REF_SCHEME,
        "capabilities" to listOf(
            "observe", "context", "actions", "execute", "undo", "highlight", "events.state", "events.selection",
        ),
        "entity_kinds" to listOf(
            kind("project", "Project", "The opened project: its modules, directories and files"),
            kind("module", "Module", "A unit of the project with its own sources, dependencies and SDK"),
            kind("directory", "Directory", "A folder of the project"),
            kind("file", "File", "A file of the project; open files are in the editor tabs"),
            kind("symbol", "Symbol", "A named element of the code: class, interface, function or field"),
            kind("problem", "Problem", "An error or warning the IDE's code analysis found in an open file"),
            kind("run_config", "Run configuration", "How the IDE runs or tests something (shown in the Run widget)"),
        ),
        "volatile_props" to listOf("lines", "modified", "line", "end_line"),
        "locales" to listOf("en"),
        "profile_id" to Wysp.ADAPTER_ID,
    )

    private fun kind(kind: String, label: String, description: String) =
        mapOf("kind" to kind, "label" to label, "description" to description)

    // ------------------------------------------------------------------------------------------ routing
    fun activeProject(): Project? {
        val focused = IdeFocusManager.getGlobalInstance().lastFocusedFrame?.project
        if (focused != null && !focused.isDisposed && !focused.isDefault) return focused
        return ProjectManager.getInstance().openProjects.firstOrNull { !it.isDisposed && !it.isDefault }
    }

    @Suppress("UNCHECKED_CAST")
    fun handle(method: String, params: Map<String, Any?>): CompletableFuture<Any?> = when (method) {
        "adapter.observe" -> observe(params["scope"] as? Map<String, Any?> ?: mapOf("level" to "focus"))
        "adapter.get_context" -> context()
        "adapter.get_actions" -> CompletableFuture.completedFuture(catalog.specs())
        "adapter.execute" -> execute(params["call"] as? Map<String, Any?> ?: emptyMap())
        "adapter.undo" -> undo(params["token"] as? String ?: "")
        "adapter.highlight" -> highlight(
            params["ref"] as? String ?: "",
            (params["duration_ms"] as? Number)?.toInt() ?: 2500,
        )
        else -> CompletableFuture.failedFuture(WyspError(ErrorCode.METHOD_NOT_FOUND, "unknown method $method"))
    }

    fun observe(scope: Map<String, Any?>): CompletableFuture<Any?> {
        val project = activeProject() ?: return CompletableFuture.completedFuture(emptyObservation(scope))
        return withSnapshot(project) { snap -> Observer(project).observe(scope, snap, stateVersion.get()) }
    }

    fun context(): CompletableFuture<Any?> {
        val project = activeProject() ?: return CompletableFuture.completedFuture(
            mapOf("summary" to "No project is open in the IDE", "mode" to "welcome", "focus" to emptyList<String>(), "facts" to emptyMap<String, Any>()),
        )
        return withSnapshot(project) { snap -> fitContext(Observer(project).context(snap)) }
    }

    /** Focus refs for selection events. */
    fun focusOf(project: Project): CompletableFuture<List<String>> =
        withSnapshot(project) { snap ->
            @Suppress("UNCHECKED_CAST")
            Observer(project).context(snap)["focus"] as List<String>
        }

    fun execute(call: Map<String, Any?>): CompletableFuture<Any?> {
        val (action, params) = try {
            catalog.prepare(call)
        } catch (e: WyspError) {
            return CompletableFuture.failedFuture(e)
        }
        val dryRun = call["dry_run"] == true
        val project = activeProject() ?: return CompletableFuture.failedFuture(
            WyspError(ErrorCode.PRECONDITION_FAILED, "no project is open in the IDE"),
        )
        return busyAfter(inBackground(project) { action.resolve(project, params) }, 4000)
            .thenCompose { resolved ->
                onEdt(ModalityState.nonModal()) {
                    origin.wysp { catalog.execute(project, action, params, resolved, dryRun) }
                }
            }
            .thenCompose { executed ->
                // The change is done: past the budget, reply without the extra refs rather than with an error.
                inBackground(project) { catalog.finish(executed) }.completeOnTimeout(executed.result, 3, TimeUnit.SECONDS)
            }
            .thenApply { result ->
                result["state_version"] = if (dryRun) stateVersion.get() else bump()
                result as Any?
            }
    }

    fun undo(token: String): CompletableFuture<Any?> = onEdt(ModalityState.nonModal()) {
        val result = origin.wysp { catalog.undo(token) }.toMutableMap()
        result["state_version"] = bump()
        result as Any?
    }

    fun highlight(ref: String, durationMs: Int): CompletableFuture<Any?> {
        val project = activeProject() ?: return CompletableFuture.failedFuture(
            WyspError(ErrorCode.PRECONDITION_FAILED, "no project is open in the IDE"),
        )
        val highlighter = project.service<WyspProjectService>().highlighter
        return busyAfter(inBackground(project) { highlighter.resolve(ref) }, 2000)
            .thenCompose { target -> onEdt(ModalityState.any()) { highlighter.highlight(target, durationMs) as Any? } }
    }

    // ---------------------------------------------------------------------------------------- threading
    /**
     * Runs on the EDT. If the EDT cannot start the work within [startWithinMs] (a modal dialog, a long task),
     * the work is cancelled before it starts and the reply is BUSY: an action never runs after its caller was
     * told it failed. Once started, the work runs to completion.
     */
    private fun <T> onEdt(modality: ModalityState, startWithinMs: Long = 4000, block: () -> T): CompletableFuture<T> {
        val f = CompletableFuture<T>()
        val claimed = AtomicBoolean(false)
        ApplicationManager.getApplication().invokeLater({
            if (!claimed.compareAndSet(false, true)) return@invokeLater // timed out: never start late
            try {
                f.complete(block())
            } catch (e: Throwable) {
                f.completeExceptionally(e)
            }
        }, modality)
        AppExecutorUtil.getAppScheduledExecutorService().schedule({
            if (claimed.compareAndSet(false, true)) {
                f.completeExceptionally(WyspError(ErrorCode.BUSY, "the IDE is busy (a dialog is open or a task holds the interface); nothing was changed, try again"))
            }
        }, startWithinMs, TimeUnit.MILLISECONDS)
        return f
    }

    /** Reads have no side effects: past the budget, answer BUSY (the IDE is syncing or indexing) instead of hanging. */
    private fun <T> busyAfter(f: CompletableFuture<T>, ms: Long): CompletableFuture<T> {
        AppExecutorUtil.getAppScheduledExecutorService().schedule({
            f.completeExceptionally(WyspError(ErrorCode.BUSY, "the IDE is busy (syncing or indexing the project); try again in a moment"))
        }, ms, TimeUnit.MILLISECONDS)
        return f
    }

    /** A non-blocking read action on a pooled thread (restarted if a write action interrupts it). */
    private fun <T> inBackground(project: Project, block: () -> T): CompletableFuture<T> {
        val f = CompletableFuture<T>()
        // Expected failures (unknown target, invalid name) complete the future here: a rejected platform
        // promise would be logged as an IDE error blamed on the plugin.
        ReadAction.nonBlocking<Unit> {
            try {
                f.complete(block())
            } catch (e: com.intellij.openapi.progress.ProcessCanceledException) {
                throw e // let the platform restart the read action
            } catch (e: Throwable) {
                f.completeExceptionally(e)
            }
        }
            .expireWith(project)
            .submit(AppExecutorUtil.getAppExecutorService())
            .onError { if (!f.isDone) f.completeExceptionally(it) }
        return f
    }

    private fun <T> withSnapshot(project: Project, block: (EditorSnapshot) -> T): CompletableFuture<T> {
        val f = CompletableFuture<T>()
        ApplicationManager.getApplication().invokeLater({
            if (project.isDisposed) {
                f.completeExceptionally(WyspError(ErrorCode.PRECONDITION_FAILED, "the project was closed"))
                return@invokeLater
            }
            val snap = try {
                EditorSnapshot.capture(project)
            } catch (e: Throwable) {
                f.completeExceptionally(e)
                return@invokeLater
            }
            ReadAction.nonBlocking<Unit> {
                try {
                    f.complete(block(snap))
                } catch (e: com.intellij.openapi.progress.ProcessCanceledException) {
                    throw e
                } catch (e: Throwable) {
                    f.completeExceptionally(e)
                }
            }
                .expireWith(project)
                .submit(AppExecutorUtil.getAppExecutorService())
                .onError { if (!f.isDone) f.completeExceptionally(it) }
        }, ModalityState.any())
        return busyAfter(f, 4000)
    }

    /** The contract caps a context at 8 KB: shorten the code first, then the selection. */
    private fun fitContext(ctx: Map<String, Any?>): Map<String, Any?> {
        @Suppress("UNCHECKED_CAST")
        val facts = (ctx["facts"] as Map<String, Any?>).toMutableMap()
        fun size() = Json.write(ctx + ("facts" to facts)).toByteArray(Charsets.UTF_8).size
        for (key in listOf("code_at_caret", "code_near_caret", "selection")) {
            var budget = 1500
            while (size() > 8000 && facts[key] is String && budget >= 200) {
                facts[key] = Privacy.bound(facts[key] as String, budget)
                budget /= 2
            }
            if (size() > 8000) facts.remove(key)
        }
        return ctx + ("facts" to facts)
    }

    private fun emptyObservation(scope: Map<String, Any?>): Map<String, Any?> = mapOf(
        "observation_id" to "obs-" + java.util.UUID.randomUUID().toString().substring(0, 8),
        "state_version" to stateVersion.get(),
        "captured_at" to java.time.Instant.now().toString(),
        "scope" to scope,
        "entities" to emptyList<Any>(),
        "links" to emptyList<Any>(),
        "focus" to emptyList<String>(),
        "truncated" to false,
        "counts" to emptyMap<String, Int>(),
    )

    companion object {
        fun get(): WyspService = service()
    }
}
