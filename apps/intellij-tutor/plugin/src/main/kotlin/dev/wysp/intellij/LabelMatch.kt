package dev.wysp.intellij

/**
 * Which visible component is the button, tab or menu the tutor names? Same rules as the Blender label
 * matcher, for Swing texts instead of OCR words: exact (case-insensitive, ignoring `…`, mnemonics,
 * HTML and stray symbols), truncated labels, and close spellings. Pure Kotlin, tested without an IDE.
 */
object LabelMatch {
    private val TAGS = Regex("<[^>]*>")
    private val JUNK = Regex("^[^\\p{L}\\p{N}]+|[^\\p{L}\\p{N}…]+$")

    fun norm(text: String): String {
        val plain = TAGS.replace(text, " ").replace("&nbsp;", " ").replace("...", "…").replace("_", "").lowercase()
        return plain.split(Regex("\\s+")).map { JUNK.replace(it, "") }.filter { it.isNotEmpty() }.joinToString(" ")
    }

    /** 1.0 for the same label, 0.95 when only a trailing `…` differs, ~0.85 for a truncated one, fuzzy ≥ 0.85 × 0.9. */
    fun score(wanted: String, seen: String): Double {
        val a = norm(wanted)
        val b = norm(seen)
        if (a.isEmpty() || b.isEmpty()) return 0.0
        if (a == b) return 1.0
        if (a.trimEnd('…').trimEnd() == b.trimEnd('…').trimEnd()) return 0.95
        if (b.endsWith('…')) {
            val stem = b.dropLast(1).trimEnd()
            if (stem.length >= 3 && a.startsWith(stem)) return 0.85
        }
        val r = ratio(a, b)
        return if (r >= 0.85) Math.round(r * 0.9 * 1000) / 1000.0 else 0.0
    }

    /** Similarity in [0, 1] from the edit distance. */
    fun ratio(a: String, b: String): Double {
        if (a == b) return 1.0
        val n = maxOf(a.length, b.length)
        if (n == 0) return 1.0
        var prev = IntArray(b.length + 1) { it }
        var cur = IntArray(b.length + 1)
        for (i in 1..a.length) {
            cur[0] = i
            for (j in 1..b.length) {
                val cost = if (a[i - 1] == b[j - 1]) 0 else 1
                cur[j] = minOf(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            }
            val t = prev; prev = cur; cur = t
        }
        return 1.0 - prev[b.length].toDouble() / n
    }

    /** Index of the best candidate scoring at least `minScore`; the first in order wins ties. */
    fun best(wanted: String, candidates: List<String>, minScore: Double = 0.8): Int? {
        var bestIndex: Int? = null
        var bestScore = minScore - 1e-9
        candidates.forEachIndexed { i, c ->
            val s = score(wanted, c)
            if (s > bestScore + 1e-9) {
                bestScore = s
                bestIndex = i
            }
        }
        return bestIndex
    }

    /** Readable, distinct labels, for telling the tutor what it could point at instead. */
    fun visible(candidates: List<String>, limit: Int = 30): List<String> {
        val out = LinkedHashSet<String>()
        for (c in candidates) {
            val t = TAGS.replace(c, " ").replace(Regex("\\s+"), " ").trim()
            if (t.length >= 2 && t.any { it.isLetter() } && t.length <= 60) out += t
            if (out.size >= limit) break
        }
        return out.toList()
    }
}
