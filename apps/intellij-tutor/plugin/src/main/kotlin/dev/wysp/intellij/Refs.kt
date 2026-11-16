package dev.wysp.intellij

import java.net.URLDecoder
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/**
 * `intellij://` refs. Paths are relative to the project base directory, with `/` separators and
 * percent-encoded segments; a symbol is `file/<path>#<Qualified.Name>` with encoded name parts.
 * Pure Kotlin (no IDE classes), so the grammar is tested without an IDE.
 */
sealed class Ref {
    data class Project(val name: String) : Ref()
    data class Module(val name: String) : Ref()
    data class Dir(val path: String) : Ref()
    data class File(val path: String) : Ref()
    data class Symbol(val path: String, val parts: List<String>) : Ref() {
        val qualifiedName: String get() = parts.joinToString(".")
        val name: String get() = parts.last()
    }
    data class Problem(val path: String, val line: Int, val n: Int) : Ref()
    /** Whole lines `from..to` (1-based, inclusive) of a file: what a line-by-line explanation points at. */
    data class Lines(val path: String, val from: Int, val to: Int) : Ref()
    data class Run(val name: String) : Ref()
    data class ToolWindow(val id: String) : Ref()
    data class Label(val text: String) : Ref()
}

object Refs {
    const val PREFIX = "intellij://"
    const val FILE_PATTERN = "^intellij://file/[^#]+$"
    const val SYMBOL_PATTERN = "^intellij://file/[^#]+#.+$"

    fun project(name: String) = PREFIX + "project/" + enc(name)
    fun module(name: String) = PREFIX + "module/" + enc(name)
    fun dir(path: String) = PREFIX + "dir/" + encPath(path)
    fun file(path: String) = PREFIX + "file/" + encPath(path)

    /** A symbol: name parts are joined by `.`; a part containing `.` is encoded so the split stays exact. */
    fun symbol(path: String, parts: List<String>) = file(path) + "#" + parts.joinToString(".") { enc(it).replace(".", "%2E") }
    fun problem(path: String, line: Int, n: Int) = PREFIX + "problem/" + encPath(path) + ":" + line + ":" + n
    /** `intellij://lines/<path>:<from>-<to>`; a single line is `:<n>`. */
    fun lines(path: String, from: Int, to: Int = from) =
        PREFIX + "lines/" + encPath(path) + ":" + from + if (to != from) "-$to" else ""
    fun run(name: String) = PREFIX + "run/" + enc(name)
    fun toolWindow(id: String) = PREFIX + "ui/toolwindow/" + enc(id)
    fun label(text: String) = PREFIX + "ui/label/" + enc(text)

    fun parse(ref: String): Ref? {
        if (!ref.startsWith(PREFIX)) return null
        val rest = ref.substring(PREFIX.length)
        val slash = rest.indexOf('/')
        if (slash <= 0 || slash == rest.length - 1) return null
        val head = rest.substring(0, slash)
        val body = rest.substring(slash + 1)
        return when (head) {
            "project" -> Ref.Project(dec(body))
            "module" -> Ref.Module(dec(body))
            "dir" -> decPath(body)?.let { Ref.Dir(it) }
            "file" -> {
                val hash = body.indexOf('#')
                if (hash < 0) {
                    decPath(body)?.let { Ref.File(it) }
                } else {
                    val path = decPath(body.substring(0, hash)) ?: return null
                    val name = body.substring(hash + 1)
                    if (name.isEmpty()) return null
                    val parts = name.split('.').map { dec(it) }
                    if (parts.any { it.isEmpty() }) return null
                    Ref.Symbol(path, parts)
                }
            }
            "problem" -> {
                val b = body.lastIndexOf(':')
                val a = if (b > 0) body.lastIndexOf(':', b - 1) else -1
                if (a <= 0) return null
                val line = body.substring(a + 1, b).toIntOrNull() ?: return null
                val n = body.substring(b + 1).toIntOrNull() ?: return null
                decPath(body.substring(0, a))?.let { Ref.Problem(it, line, n) }
            }
            "lines" -> {
                val colon = body.lastIndexOf(':')
                if (colon <= 0) return null
                val range = body.substring(colon + 1)
                val dash = range.indexOf('-')
                val from = (if (dash < 0) range else range.substring(0, dash)).toIntOrNull() ?: return null
                val to = if (dash < 0) from else range.substring(dash + 1).toIntOrNull() ?: return null
                if (from < 1 || to < from) return null
                decPath(body.substring(0, colon))?.let { Ref.Lines(it, from, to) }
            }
            "run" -> Ref.Run(dec(body))
            "ui" -> when {
                body.startsWith("toolwindow/") && body.length > 11 -> Ref.ToolWindow(dec(body.substring(11)))
                body.startsWith("label/") && body.length > 6 -> Ref.Label(dec(body.substring(6)))
                else -> null
            }
            else -> null
        }
    }

    private fun enc(s: String): String = URLEncoder.encode(s, StandardCharsets.UTF_8).replace("+", "%20")

    private fun encPath(path: String): String = path.split('/').joinToString("/") { enc(it) }

    private fun dec(s: String): String = try {
        URLDecoder.decode(s.replace("+", "%2B"), StandardCharsets.UTF_8)
    } catch (_: IllegalArgumentException) {
        s // a malformed escape written by hand: take the text as it is
    }

    private fun decPath(s: String): String? {
        val parts = s.split('/').map { dec(it) }
        if (parts.any { it.isEmpty() || it == "." || it == ".." }) return null // no escaping the project
        return parts.joinToString("/")
    }
}
