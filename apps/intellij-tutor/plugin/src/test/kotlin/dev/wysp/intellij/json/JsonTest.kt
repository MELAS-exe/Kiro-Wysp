package dev.wysp.intellij.json

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test
import kotlin.random.Random

class JsonTest {
    @Test
    fun `writes and parses a contract message`() {
        val msg = mapOf(
            "jsonrpc" to "2.0",
            "id" to "hello-1",
            "params" to mapOf("token" to "t", "list" to listOf(1L, 2.5, true, null, "é\n\"x\"")),
        )
        val text = Json.write(msg)
        assertEquals(msg, Json.parse(text))
    }

    @Test
    fun `parses unicode escapes and whitespace`() {
        assertEquals(mapOf("a" to "\u00e9\u20ac", "b" to listOf<Any?>()), Json.parse(" { \"a\" : \"\\u00e9\\u20ac\" , \"b\" : [ ] } "))
    }

    @Test
    fun `rejects malformed input`() {
        for (bad in listOf("{", "[1,]x", "{\"a\" 1}", "tru", "\"abc", "-", "{} {}")) {
            assertThrows(JsonException::class.java) { Json.parse(bad) }
        }
    }

    /** Property IJ-P1: codec round trip. Validates: Requirement 10.1 */
    @Test
    fun `prop IJ-P1 codec round trip`() {
        val rnd = Random(20261111)
        repeat(500) {
            val v = randomValue(rnd, 0)
            assertEquals(v, Json.parse(Json.write(v)))
        }
    }

    private fun randomString(rnd: Random): String {
        val n = rnd.nextInt(0, 12)
        val sb = StringBuilder()
        repeat(n) {
            when (rnd.nextInt(5)) {
                0 -> sb.append(rnd.nextInt(0, 32).toChar()) // control characters
                1 -> sb.append("\"\\/".random(rnd))
                2 -> sb.appendCodePoint(rnd.nextInt(0x80, 0xD7FF)) // BMP outside the surrogates
                3 -> sb.appendCodePoint(rnd.nextInt(0x10000, 0x10FFFF)) // astral: a surrogate pair
                else -> sb.append(rnd.nextInt(32, 127).toChar())
            }
        }
        return sb.toString()
    }

    private fun randomValue(rnd: Random, depth: Int): Any? {
        val kind = rnd.nextInt(if (depth > 3) 6 else 8)
        return when (kind) {
            0 -> null
            1 -> rnd.nextBoolean()
            2 -> rnd.nextLong(-1_000_000_000_000L, 1_000_000_000_000L)
            3 -> rnd.nextDouble(-1e6, 1e6).let { if (it == Math.rint(it)) it + 0.5 else it }
            4, 5 -> randomString(rnd)
            6 -> List(rnd.nextInt(0, 5)) { randomValue(rnd, depth + 1) }
            else -> LinkedHashMap<String, Any?>().also { m ->
                repeat(rnd.nextInt(0, 5)) { m[randomString(rnd)] = randomValue(rnd, depth + 1) }
            }
        }
    }
}
