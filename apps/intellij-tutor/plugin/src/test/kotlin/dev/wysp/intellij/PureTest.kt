package dev.wysp.intellij

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.random.Random

class RefsTest {
    private val alphabet = listOf("a", "b", "c", "X", "Y", "Z", "0", "1", "9", " ", "_", "-", ".", "#", ":", "%", "+", "é", "漢", "😀")

    private fun randomSegment(rnd: Random): String {
        while (true) {
            val s = buildString { repeat(rnd.nextInt(1, 10)) { append(alphabet.random(rnd)) } }
            if (s.isNotEmpty() && s != "." && s != "..") return s
        }
    }

    /** Property IJ-P2: refs round trip. Validates: Requirement 3.1 */
    @Test
    fun `prop IJ-P2 refs round trip`() {
        val rnd = Random(3_1)
        repeat(400) {
            val path = List(rnd.nextInt(1, 5)) { randomSegment(rnd) }.joinToString("/")
            val parts = List(rnd.nextInt(1, 4)) { randomSegment(rnd) }
            assertEquals(Ref.File(path), Refs.parse(Refs.file(path)))
            assertEquals(Ref.Dir(path), Refs.parse(Refs.dir(path)))
            assertEquals(Ref.Symbol(path, parts), Refs.parse(Refs.symbol(path, parts)))
            val line = rnd.nextInt(1, 5000)
            assertEquals(Ref.Problem(path, line, 2), Refs.parse(Refs.problem(path, line, 2)))
            val name = randomSegment(rnd) + "/" + randomSegment(rnd)
            assertEquals(Ref.Run(name), Refs.parse(Refs.run(name)))
            assertEquals(Ref.Label(name), Refs.parse(Refs.label(name)))
            assertEquals(Ref.ToolWindow(name), Refs.parse(Refs.toolWindow(name)))
            assertEquals(Ref.Module(name), Refs.parse(Refs.module(name)))
        }
    }

    @Test
    fun `hand-written refs parse`() {
        assertEquals(Ref.Symbol("src/Main.kt", listOf("Greeter", "greet")), Refs.parse("intellij://file/src/Main.kt#Greeter.greet"))
        assertEquals(Ref.Label("Add Configuration…"), Refs.parse("intellij://ui/label/Add Configuration…"))
        assertEquals(Ref.ToolWindow("Problems View"), Refs.parse("intellij://ui/toolwindow/Problems%20View"))
        assertEquals(Ref.Label("100%"), Refs.parse("intellij://ui/label/100%")) // malformed escape: taken as is
    }

    @Test
    fun `refs never escape the project`() {
        for (bad in listOf("intellij://file/../secret.txt", "intellij://file/a/./b", "intellij://file/a//b", "intellij://dir/..",
            "intellij://file/a#", "intellij://problem/a:x:1", "blender://object/Cube", "intellij://nope/x", "intellij://file/")) {
            assertNull(bad, Refs.parse(bad))
        }
    }

    @Test
    fun `ref patterns match built refs`() {
        assertTrue(Regex(Refs.FILE_PATTERN).containsMatchIn(Refs.file("src/A B.kt")))
        assertTrue(Regex(Refs.SYMBOL_PATTERN).containsMatchIn(Refs.symbol("src/A.kt", listOf("A", "b"))))
        assertFalse(Regex(Refs.FILE_PATTERN).containsMatchIn(Refs.symbol("src/A.kt", listOf("A"))))
    }
}

class PrivacyTest {
    /** Property IJ-P3 (name rules): sensitive names are recognised in any case and any folder. */
    @Test
    fun `prop IJ-P3 sensitive names are detected`() {
        val rnd = Random(4_4)
        val names = listOf(".env", ".env.local", "server.pem", "tls.key", "store.p12", "cert.pfx", "id_rsa", "id_ed25519.pub",
            "aws_credentials.json", "client_secret.json", "release.keystore", "app.jks", ".netrc", ".npmrc")
        repeat(200) {
            val n = names.random(rnd)
            val cased = n.map { if (rnd.nextBoolean()) it.uppercaseChar() else it }.joinToString("")
            val dir = List(rnd.nextInt(0, 3)) { "d${rnd.nextInt(100)}" }.joinToString("/")
            val path = if (dir.isEmpty()) cased else "$dir/$cased"
            assertTrue(path, Privacy.isSensitivePath(path))
        }
        assertTrue(Privacy.isSensitivePath("secrets/config.yaml"))
    }

    @Test
    fun `ordinary code is not sensitive`() {
        for (n in listOf("Main.kt", "Tokenizer.java", "PasswordValidator.java", "build.gradle.kts", "env.py", "keys.md", "README.md")) {
            assertFalse(n, Privacy.isSensitive(n))
        }
    }

    @Test
    fun `bound cuts long text on a line`() {
        val text = (1..400).joinToString("\n") { "line $it" }
        val cut = Privacy.bound(text, 1500)
        assertTrue(cut.length <= 1502)
        assertTrue(cut.endsWith("\n…"))
        assertEquals("short", Privacy.bound("short", 10))
        assertEquals("a b…", Privacy.oneLine("a   b\n c d e", 4))
    }
}

class LabelMatchTest {
    @Test
    fun `scores follow the label rules`() {
        assertEquals(1.0, LabelMatch.score("Commit", "Commit"), 1e-9)
        assertEquals(1.0, LabelMatch.score("problems", "<html><b>Problems</b></html>"), 1e-9)
        assertEquals(0.95, LabelMatch.score("Rename", "Rename..."), 1e-9)
        assertEquals(0.85, LabelMatch.score("Configuration", "Configur…"), 1e-9)
        assertTrue(LabelMatch.score("Terminl", "Terminal") > 0.7)
        assertEquals(0.0, LabelMatch.score("Run", "Debug"), 1e-9)
    }

    @Test
    fun `best prefers the exact label and the first on ties`() {
        assertEquals(2, LabelMatch.best("Run", listOf("Run Anything", "Debug", "Run", "Run")))
        assertEquals(0, LabelMatch.best("Rename", listOf("Rename…", "Refactor")))
        assertNull(LabelMatch.best("Deploy", listOf("Run", "Debug")))
    }

    @Test
    fun `visible lists distinct readable labels`() {
        assertEquals(listOf("Project", "Run"), LabelMatch.visible(listOf("Project", "", "x", "Run", "Project", "12")))
    }
}

class SchemaTest {
    private val schema = mapOf(
        "type" to "object",
        "properties" to mapOf(
            "target" to mapOf("type" to "string", "pattern" to Refs.FILE_PATTERN),
            "line" to mapOf("type" to "integer", "minimum" to 1),
        ),
        "required" to listOf("target"),
        "additionalProperties" to false,
    )

    @Test
    fun `validates action parameters`() {
        assertEquals(emptyList<String>(), Schema.validate(mapOf("target" to "intellij://file/a.kt", "line" to 3L), schema))
        assertEquals(1, Schema.validate(mapOf("line" to 3L), schema).size)
        assertEquals(1, Schema.validate(mapOf("target" to "intellij://file/a.kt", "line" to 0L), schema).size)
        assertEquals(1, Schema.validate(mapOf("target" to "intellij://file/a.kt", "line" to "x"), schema).size)
        assertEquals(1, Schema.validate(mapOf("target" to "intellij://file/a.kt#A"), schema).size)
        assertEquals(1, Schema.validate(mapOf("target" to "intellij://file/a.kt", "extra" to 1L), schema).size)
    }
}

class OriginTaggerTest {
    @Test
    fun `changes during and just after an action are wysp`() {
        var now = 1000L
        val tagger = OriginTagger(600) { now }
        assertEquals("user", tagger.current())
        tagger.wysp { assertEquals("wysp", tagger.current()) }
        now += 500
        assertEquals("wysp", tagger.current())
        now += 200
        assertEquals("user", tagger.current())
    }
}
