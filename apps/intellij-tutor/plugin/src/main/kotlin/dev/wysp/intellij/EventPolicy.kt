package dev.wysp.intellij

/**
 * Pending `state_changed` refs, grouped by origin. A user edit that lands in the same debounce window as a Wysp
 * change must not be swallowed into a `wysp` batch (it would never count as the learner's evidence), so a change
 * with another origin closes the pending batch first. Pure Kotlin: tested without an IDE.
 */
class ChangeBatch(private val max: Int = 50) {
    class Batch(val changed: List<String>, val origin: String)

    private val refs = LinkedHashSet<String>()
    private var origin = "user"

    /** Adds [ref]; returns the previous batch when [newOrigin] differs from it (the caller must send it). */
    @Synchronized
    fun add(ref: String, newOrigin: String): Batch? {
        var closed: Batch? = null
        if (refs.isNotEmpty() && newOrigin != origin) closed = takeLocked()
        refs += ref
        origin = newOrigin
        return closed
    }

    @Synchronized
    fun take(): Batch? = takeLocked()

    private fun takeLocked(): Batch? {
        if (refs.isEmpty()) return null
        val b = Batch(refs.take(max), origin)
        refs.clear()
        origin = "user"
        return b
    }
}

/**
 * Caret and selection changes. The Core verifies "select X" exercises from a fresh observation whose
 * `state_version` is greater than the one at the exercise start, so a focus change the user made must advance
 * the version: [onFocus] says whether to bump and notify.
 */
class SelectionTracker {
    private var last: List<String> = emptyList()

    /** True when the user's focus changed (bump the state version and send `event.selection_changed`). */
    @Synchronized
    fun onFocus(focus: List<String>, ours: Boolean): Boolean {
        if (focus == last) return false
        last = focus
        return !ours
    }
}

/**
 * Tracks the problems the IDE's analysis reports per file. The analysis finishes after the document change that
 * triggered it, so the `state_changed` sent for the edit still sees the old problems: the Core needs a second
 * event when the list actually changes.
 */
class ProblemTracker {
    private val last = HashMap<String, Set<String>>()

    /** True when the problem signature of [path] differs from the last one seen (the first sighting is a change only if non-empty). */
    @Synchronized
    fun changed(path: String, signature: Set<String>): Boolean {
        val before = last.put(path, signature) ?: emptySet()
        return before != signature
    }

    @Synchronized
    fun forget(path: String) {
        last.remove(path)
    }
}
