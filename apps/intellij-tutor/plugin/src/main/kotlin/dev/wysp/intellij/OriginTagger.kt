package dev.wysp.intellij

/**
 * Tags state changes caused by Wysp: during a Wysp action and for a short window after it (600 ms),
 * changes are `wysp`; otherwise `user`. Wysp's own changes never count as the learner's evidence.
 */
class OriginTagger(private val windowMs: Long = 600, private val clock: () -> Long = { System.nanoTime() / 1_000_000 }) {
    private var active = 0
    private var until = 0L

    @Synchronized
    fun begin() {
        active++
    }

    @Synchronized
    fun end() {
        active = maxOf(0, active - 1)
        until = clock() + windowMs
    }

    @Synchronized
    fun current(): String = if (active > 0 || clock() < until) "wysp" else "user"

    inline fun <T> wysp(block: () -> T): T {
        begin()
        try {
            return block()
        } finally {
            end()
        }
    }
}
