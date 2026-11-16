package dev.wysp.intellij

import com.intellij.testFramework.fixtures.BasePlatformTestCase
import dev.wysp.intellij.actions.Catalog
import kotlin.random.Random

/** The code tools (read, search, usages, edits, create, reformat, imports) on a light Java fixture. */
class CodeToolsTest : BasePlatformTestCase() {
    private val catalog = Catalog()

    private val source = (1..10).joinToString("\n") { "line $it" } + "\n"

    private fun ref(path: String) = Refs.file(path)

    private fun call(id: String, params: Map<String, Any?>, dryRun: Boolean = false): MutableMap<String, Any?> {
        val (action, p) = catalog.prepare(mapOf("action_id" to id, "params" to params))
        return catalog.runAll(project, action, p, dryRun)
    }

    private fun code(id: String, params: Map<String, Any?>): Int =
        try {
            call(id, params)
            0
        } catch (e: WyspError) {
            e.code
        }

    private fun open(name: String = "Notes.txt", text: String = source): String {
        val file = myFixture.configureByText(name, text)
        return Observer(project).relPath(file.virtualFile)!!
    }

    private val doc get() = myFixture.editor.document

    fun testReadCodeNumbersLinesAndBoundsTheRange() {
        val path = open()
        val out = call("read_code", mapOf("target" to ref(path), "from_line" to 2, "to_line" to 4))["message"] as String
        assertTrue(out, out.contains("   2| line 2") && out.contains("   4| line 4") && !out.contains("line 5"))
        val big = open("Big.txt", (1..400).joinToString("\n") { "row $it" })
        val cut = call("read_code", mapOf("target" to ref(big), "from_line" to 1, "to_line" to 400))["message"] as String
        assertTrue(cut, cut.contains("cut at 150") && !cut.contains("| row 151"))
        assertEquals(ErrorCode.TARGET_NOT_FOUND, code("read_code", mapOf("target" to ref(path), "from_line" to 99, "to_line" to 100)))
    }

    fun testSearchCodeFindsTextWithLineNumbers() {
        val path = open("Findme.txt", "alpha\nneedle here\nomega\n")
        val out = call("search_code", mapOf("query" to "NEEDLE"))["message"] as String
        assertTrue(out, out.contains("$path:2: needle here"))
    }

    /** Property IJ-P3 (code tools): sensitive and IDE files are neither read, searched nor changed. */
    fun testSensitiveAndNoiseFilesAreRefused() {
        for (name in listOf(".env", "server.pem", "client_secret.json")) {
            val path = open(name, "API_KEY=sk-live-do-not-leak\nsecond\n")
            val before = doc.text
            assertEquals(name, ErrorCode.PRECONDITION_FAILED, code("read_code", mapOf("target" to ref(path), "from_line" to 1, "to_line" to 1)))
            assertEquals(name, ErrorCode.PRECONDITION_FAILED, code("replace_lines", mapOf("target" to ref(path), "from_line" to 1, "to_line" to 1, "old_text" to "API_KEY=sk-live-do-not-leak", "new_text" to "x")))
            assertEquals(name, ErrorCode.PRECONDITION_FAILED, code("insert_lines", mapOf("target" to ref(path), "after_line" to 0, "new_text" to "x")))
            assertEquals(name, before, doc.text)
            val found = call("search_code", mapOf("query" to "sk-live"))["message"] as String
            assertFalse(found, found.contains("do-not-leak"))
        }
        assertEquals(ErrorCode.PRECONDITION_FAILED, code("create_file", mapOf("target" to "intellij://file/.env", "text" to "A=1")))
        assertEquals(ErrorCode.PRECONDITION_FAILED, code("create_file", mapOf("target" to "intellij://file/.idea/x.xml", "text" to "<a/>")))
        assertEquals(ErrorCode.TARGET_NOT_FOUND, code("read_code", mapOf("target" to "intellij://file/../outside.txt", "from_line" to 1, "to_line" to 1)))
    }

    fun testReplaceLinesThenUndoRestoresTheText() {
        val path = open()
        val result = call("replace_lines", mapOf("target" to ref(path), "from_line" to 3, "to_line" to 4, "old_text" to "line 3\nline 4", "new_text" to "three\n  four\nfour and a half\n"))
        assertEquals("line 1\nline 2\nthree\n  four\nfour and a half\nline 5", doc.text.lines().take(6).joinToString("\n"))
        catalog.undo(result["undo_token"] as String)
        assertEquals(source, doc.text)
    }

    fun testStaleOrWrongOldTextChangesNothing() {
        val path = open()
        assertEquals(ErrorCode.PRECONDITION_FAILED, code("replace_lines", mapOf("target" to ref(path), "from_line" to 3, "to_line" to 3, "old_text" to "line 4", "new_text" to "x")))
        assertEquals(ErrorCode.TARGET_NOT_FOUND, code("replace_lines", mapOf("target" to ref(path), "from_line" to 30, "to_line" to 31, "old_text" to "a", "new_text" to "x")))
        assertEquals(ErrorCode.INVALID_PARAMS, code("replace_lines", mapOf("target" to ref(path), "from_line" to 5, "to_line" to 4, "old_text" to "a", "new_text" to "x")))
        assertEquals(ErrorCode.INVALID_PARAMS, code("insert_lines", mapOf("target" to ref(path), "after_line" to 2, "new_text" to "x")))
        assertEquals(ErrorCode.PRECONDITION_FAILED, code("insert_lines", mapOf("target" to ref(path), "after_line" to 2, "anchor_text" to "nope", "new_text" to "x")))
        assertEquals(source, doc.text)
    }

    fun testUndoNeverOverwritesNewerWork() {
        val path = open()
        val result = call("replace_lines", mapOf("target" to ref(path), "from_line" to 2, "to_line" to 2, "old_text" to "line 2", "new_text" to "two"))
        com.intellij.openapi.command.WriteCommandAction.runWriteCommandAction(project) {
            doc.replaceString(doc.getLineStartOffset(1), doc.getLineEndOffset(1), "the user typed here")
        }
        assertEquals(ErrorCode.UNDO_UNAVAILABLE, try {
            catalog.undo(result["undo_token"] as String)
            0
        } catch (e: WyspError) {
            e.code
        })
        assertTrue(doc.text.contains("the user typed here"))
    }

    fun testInsertAndDeleteLinesAndUndo() {
        val path = open()
        val top = call("insert_lines", mapOf("target" to ref(path), "after_line" to 0, "new_text" to "header"))
        assertTrue(doc.text, doc.text.startsWith("header\nline 1\n"))
        catalog.undo(top["undo_token"] as String)
        assertEquals(source, doc.text)
        val mid = call("insert_lines", mapOf("target" to ref(path), "after_line" to 2, "anchor_text" to "line 2", "new_text" to "a\nb"))
        assertTrue(doc.text, doc.text.startsWith("line 1\nline 2\na\nb\nline 3\n"))
        catalog.undo(mid["undo_token"] as String)
        val del = call("replace_lines", mapOf("target" to ref(path), "from_line" to 9, "to_line" to 10, "old_text" to "line 9\nline 10", "new_text" to ""))
        assertEquals("line 1\nline 2\nline 3\nline 4\nline 5\nline 6\nline 7\nline 8\n", doc.text)
        catalog.undo(del["undo_token"] as String)
        assertEquals(source, doc.text)
    }

    fun testDryRunPreviewIsADiffAndChangesNothing() {
        val path = open()
        val r = call("replace_lines", mapOf("target" to ref(path), "from_line" to 3, "to_line" to 3, "old_text" to "line 3", "new_text" to "three"), dryRun = true)
        @Suppress("UNCHECKED_CAST")
        val preview = r["preview"] as Map<String, Any?>
        val diff = preview["diff"] as String
        assertTrue(diff, diff.contains("-line 3") && diff.contains("+three") && diff.contains(" line 2"))
        assertNull(r["undo_token"])
        assertEquals(source, doc.text)
    }

    fun testCreateFileThenUndoDeletesIt() {
        open() // the light project exists
        val target = "intellij://file/gen/notes/Hello.txt"
        val r = call("create_file", mapOf("target" to target, "text" to "hello\nworld\n"))
        val vf = Observer(project).resolve("gen/notes/Hello.txt")
        assertNotNull(vf)
        assertEquals("hello\nworld\n", String(vf!!.contentsToByteArray()))
        assertEquals(ErrorCode.PRECONDITION_FAILED, code("create_file", mapOf("target" to target, "text" to "again")))
        catalog.undo(r["undo_token"] as String)
        assertNull(Observer(project).resolve("gen/notes/Hello.txt"))
        assertNull(Observer(project).resolve("gen"))
    }

    fun testReformatAndOptimizeImportsAreUndoable() {
        val messy = "import java.util.List;\nimport java.util.Map;\npublic class Messy {\nint   x=1 ;\n  Map<String,String> m;\n}\n"
        val path = open("Messy.java", messy)
        val imports = call("optimize_imports", mapOf("target" to ref(path)))
        assertFalse(doc.text, doc.text.contains("import java.util.List;"))
        catalog.undo(imports["undo_token"] as String)
        assertEquals(messy, doc.text)
        val format = call("reformat_code", mapOf("target" to ref(path)))
        assertTrue(doc.text, doc.text.contains("int x = 1;"))
        catalog.undo(format["undo_token"] as String)
        assertEquals(messy, doc.text)
    }

    fun testFindUsagesListsDeclarationUsers() {
        val path = open("Greeter.java", "public class Greeter {\n    String hi() { return \"hi\"; }\n    void a() { hi(); }\n    void b() { hi(); }\n}\n")
        val out = call("find_usages", mapOf("target" to Refs.symbol(path, listOf("Greeter", "hi"))))["message"] as String
        assertTrue(out, out.contains("2 time(s)") && out.contains("$path:3:") && out.contains("$path:4:"))
    }

    fun testListFilesShowsNamesOnly() {
        open("Visible.txt")
        open("client_secret.json", "SECRET=1")
        val out = call("list_files", emptyMap())["message"] as String
        assertTrue(out, out.contains("Visible.txt") && out.contains("(sensitive: never read)"))
        assertFalse(out, out.contains("SECRET=1"))
    }

    /**
     * Property IJ-P5: any sequence of edits followed by their undos in reverse order restores the exact text,
     * and every edit gives the text a line-model predicts.
     */
    fun testPropIJP5EditsAndUndosRoundTrip() {
        val rnd = Random(5_5)
        repeat(40) {
            val n = rnd.nextInt(3, 12)
            val text = (1..n).joinToString("\n") { "row $it ${rnd.nextInt(100)}" } + "\n"
            val path = open("Prop$it.txt", text)
            var model = text.removeSuffix("\n").split("\n")
            val tokens = mutableListOf<String>()
            repeat(rnd.nextInt(1, 5)) {
                if (doc.text.isEmpty()) return@repeat // everything was deleted: nothing left to replace
                val lines = doc.text.removeSuffix("\n").split("\n")
                val from = rnd.nextInt(1, lines.size + 1)
                val to = rnd.nextInt(from, lines.size + 1)
                val old = lines.subList(from - 1, to).joinToString("\n")
                val fresh = (0 until rnd.nextInt(0, 3)).map { "new ${rnd.nextInt(1000)}" }
                val r = call("replace_lines", mapOf("target" to ref(path), "from_line" to from, "to_line" to to, "old_text" to old, "new_text" to fresh.joinToString("\n")))
                model = model.subList(0, from - 1) + fresh + model.subList(to, model.size)
                assertEquals(model.joinToString("\n"), doc.text.removeSuffix("\n"))
                tokens += r["undo_token"] as String
            }
            tokens.asReversed().forEach { t -> catalog.undo(t) }
            assertEquals(text, doc.text)
        }
    }
}
