package dev.wysp.intellij.json

/**
 * A small JSON codec for the contract messages (no third-party dependency in the plugin).
 *
 * Values: `Map<String, Any?>` (insertion ordered), `List<Any?>`, `String`, `Long` (integers), `Double`,
 * `Boolean` and `null`.
 */
object Json {
    fun write(value: Any?): String = StringBuilder().also { writeTo(it, value) }.toString()

    fun parse(text: String): Any? {
        val p = Parser(text)
        p.skipWs()
        val v = p.value()
        p.skipWs()
        if (p.i != text.length) throw JsonException("trailing characters at ${p.i}")
        return v
    }

    @Suppress("UNCHECKED_CAST")
    fun parseObject(text: String): Map<String, Any?> =
        parse(text) as? Map<String, Any?> ?: throw JsonException("expected a JSON object")

    private fun writeTo(sb: StringBuilder, v: Any?) {
        when (v) {
            null -> sb.append("null")
            is String -> quote(sb, v)
            is Boolean -> sb.append(v)
            is Int, is Long, is Short, is Byte -> sb.append(v.toString())
            is Double -> if (v.isFinite()) sb.append(if (v == Math.rint(v) && Math.abs(v) < 1e15) v.toLong().toString() else v.toString()) else sb.append("null")
            is Float -> writeTo(sb, v.toDouble())
            is Number -> sb.append(v.toString())
            is Map<*, *> -> {
                sb.append('{')
                var first = true
                for ((k, value) in v) {
                    if (!first) sb.append(',')
                    first = false
                    quote(sb, k.toString())
                    sb.append(':')
                    writeTo(sb, value)
                }
                sb.append('}')
            }
            is Iterable<*> -> {
                sb.append('[')
                var first = true
                for (item in v) {
                    if (!first) sb.append(',')
                    first = false
                    writeTo(sb, item)
                }
                sb.append(']')
            }
            is Array<*> -> writeTo(sb, v.asList())
            else -> quote(sb, v.toString())
        }
    }

    private fun quote(sb: StringBuilder, s: String) {
        sb.append('"')
        for (ch in s) {
            when (ch) {
                '"' -> sb.append("\\\"")
                '\\' -> sb.append("\\\\")
                '\n' -> sb.append("\\n")
                '\r' -> sb.append("\\r")
                '\t' -> sb.append("\\t")
                '\b' -> sb.append("\\b")
                '\u000C' -> sb.append("\\f")
                else -> if (ch < ' ') sb.append(String.format("\\u%04x", ch.code)) else sb.append(ch)
            }
        }
        sb.append('"')
    }

    private class Parser(val s: String) {
        var i = 0

        fun skipWs() {
            while (i < s.length && s[i].isWhitespace()) i++
        }

        fun value(): Any? {
            if (i >= s.length) throw JsonException("unexpected end")
            return when (s[i]) {
                '{' -> obj()
                '[' -> arr()
                '"' -> str()
                't' -> lit("true", true)
                'f' -> lit("false", false)
                'n' -> lit("null", null)
                else -> num()
            }
        }

        private fun lit(word: String, v: Any?): Any? {
            if (!s.startsWith(word, i)) throw JsonException("bad literal at $i")
            i += word.length
            return v
        }

        private fun obj(): Map<String, Any?> {
            val m = LinkedHashMap<String, Any?>()
            i++
            skipWs()
            if (peek('}')) {
                i++
                return m
            }
            while (true) {
                skipWs()
                if (!peek('"')) throw JsonException("expected a key at $i")
                val k = str()
                skipWs()
                expect(':')
                skipWs()
                m[k] = value()
                skipWs()
                if (peek(',')) {
                    i++
                    continue
                }
                expect('}')
                return m
            }
        }

        private fun arr(): List<Any?> {
            val l = ArrayList<Any?>()
            i++
            skipWs()
            if (peek(']')) {
                i++
                return l
            }
            while (true) {
                skipWs()
                l.add(value())
                skipWs()
                if (peek(',')) {
                    i++
                    continue
                }
                expect(']')
                return l
            }
        }

        private fun str(): String {
            val sb = StringBuilder()
            i++ // opening quote
            while (true) {
                if (i >= s.length) throw JsonException("unterminated string")
                val c = s[i++]
                when (c) {
                    '"' -> return sb.toString()
                    '\\' -> {
                        if (i >= s.length) throw JsonException("bad escape")
                        when (val e = s[i++]) {
                            '"' -> sb.append('"')
                            '\\' -> sb.append('\\')
                            '/' -> sb.append('/')
                            'b' -> sb.append('\b')
                            'f' -> sb.append('\u000C')
                            'n' -> sb.append('\n')
                            'r' -> sb.append('\r')
                            't' -> sb.append('\t')
                            'u' -> {
                                if (i + 4 > s.length) throw JsonException("bad unicode escape")
                                sb.append(s.substring(i, i + 4).toInt(16).toChar())
                                i += 4
                            }
                            else -> throw JsonException("bad escape \\$e")
                        }
                    }
                    else -> sb.append(c)
                }
            }
        }

        private fun num(): Any {
            val start = i
            if (peek('-')) i++
            while (i < s.length && (s[i].isDigit() || s[i] in ".eE+-")) i++
            val t = s.substring(start, i)
            if (t.isEmpty() || t == "-") throw JsonException("bad value at $start")
            return if (t.any { it in ".eE" }) t.toDouble() else t.toLongOrNull() ?: t.toDouble()
        }

        private fun peek(c: Char) = i < s.length && s[i] == c

        private fun expect(c: Char) {
            if (!peek(c)) throw JsonException("expected '$c' at $i")
            i++
        }
    }
}

class JsonException(message: String) : RuntimeException(message)

/** Typed access helpers for decoded messages. */
@Suppress("UNCHECKED_CAST")
fun Any?.obj(): Map<String, Any?> = this as? Map<String, Any?> ?: emptyMap()

@Suppress("UNCHECKED_CAST")
fun Any?.list(): List<Any?> = this as? List<Any?> ?: emptyList()

fun Map<String, Any?>.str(key: String): String? = this[key] as? String

fun Map<String, Any?>.int(key: String): Int? = (this[key] as? Number)?.toInt()
