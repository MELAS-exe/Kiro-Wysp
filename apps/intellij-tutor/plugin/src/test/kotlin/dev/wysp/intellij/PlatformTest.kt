package dev.wysp.intellij

import com.intellij.testFramework.fixtures.BasePlatformTestCase
import dev.wysp.intellij.actions.Catalog
import dev.wysp.intellij.actions.RenameSymbol
import dev.wysp.intellij.json.Json

/** Observation, context and actions on a light Java fixture (the IDE's real PSI, no UI). */
class PlatformTest : BasePlatformTestCase() {
    private val source = """
        public class Greeter {
            private final String prefix = "Hello";

            public String greet(String name) {
                return prefix + ", " + name;<caret>
            }

            public static void main(String[] args) {
                System.out.println(new Greeter().greet("Ada"));
            }
        }
    """.trimIndent()

    private fun snapshot() = EditorSnapshot.capture(project)

    @Suppress("UNCHECKED_CAST")
    private fun entities(obs: Map<String, Any?>) = obs["entities"] as List<Map<String, Any?>>

    fun testObservationListsCodeStructure() {
        myFixture.configureByText("Greeter.java", source)
        val obs = Observer(project).observe(mapOf("level" to "focus"), snapshot(), 7)
        val ents = entities(obs)
        val labels = ents.filter { it["kind"] == "symbol" }.map { it["label"] }
        assertTrue(labels.toString(), labels.containsAll(listOf("Greeter", "prefix", "greet", "main")))
        val greet = ents.first { it["label"] == "greet" }
        @Suppress("UNCHECKED_CAST")
        val props = greet["props"] as Map<String, Any?>
        assertEquals("function", props["type"])
        assertEquals(4, props["line"])
        // Referential integrity: every parent and focus ref is in the observation.
        val refs = ents.map { it["ref"] }.toSet()
        for (e in ents) e["parent"]?.let { assertTrue("parent $it", it in refs) }
        @Suppress("UNCHECKED_CAST")
        val focus = obs["focus"] as List<String>
        assertTrue(focus.toString(), focus.any { it.endsWith("#Greeter.greet") })
        assertEquals(7L, obs["state_version"].let { (it as Number).toLong() })
        assertTrue(Json.write(obs).length < 256 * 1024)
    }

    fun testContextCarriesCodeAtCaretOnly() {
        myFixture.configureByText("Greeter.java", source)
        val ctx = Observer(project).context(snapshot())
        @Suppress("UNCHECKED_CAST")
        val facts = ctx["facts"] as Map<String, Any?>
        val code = facts["code_at_caret"] as String
        assertTrue(code, code.startsWith("public String greet"))
        assertFalse(code.contains("main"))
        assertTrue(ctx["summary"].toString(), ctx["summary"].toString().contains("Greeter.greet"))
    }

    /** Property IJ-P3 (in the IDE): the context never carries text from a sensitive file. */
    fun testSensitiveFileTextNeverLeaks() {
        for (name in listOf(".env", "server.pem", "client_secret.json")) {
            myFixture.configureByText(name, "API_KEY=sk-live-do-not-leak<caret>\n")
            myFixture.editor.selectionModel.setSelection(0, 10)
            val ctx = Json.write(Observer(project).context(snapshot()))
            assertFalse(ctx, ctx.contains("do-not-leak"))
            assertFalse(ctx, ctx.contains("API_KEY"))
            val obs = Json.write(Observer(project).observe(mapOf("level" to "full"), snapshot(), 1))
            assertFalse(obs, obs.contains("do-not-leak"))
        }
    }

    /** Property IJ-P4: renaming a symbol and undoing restores the original file text. */
    fun testRenameIsUndoable() {
        val file = myFixture.configureByText("Greeter.java", source)
        val original = myFixture.editor.document.text
        val path = Observer(project).relPath(file.virtualFile)!!
        val ref = Refs.symbol(path, listOf("Greeter", "greet"))
        val catalog = Catalog()
        val (action, params) = catalog.prepare(mapOf("action_id" to "rename_symbol", "params" to mapOf("target" to ref, "new_name" to "welcome")))
        assertTrue(action is RenameSymbol)
        val result = catalog.runAll(project, action, params, false)
        val renamed = myFixture.editor.document.text
        assertEquals(2, Regex("welcome\\(").findAll(renamed).count())
        assertFalse(renamed.contains("greet("))
        val obs = Observer(project).observe(mapOf("level" to "focus"), snapshot(), 2)
        assertTrue(entities(obs).any { it["kind"] == "symbol" && it["label"] == "welcome" }) // the postcondition
        catalog.undo(result["undo_token"] as String)
        assertEquals(original, myFixture.editor.document.text)
    }

    fun testInvalidCallsChangeNothing() {
        val file = myFixture.configureByText("Greeter.java", source)
        val before = myFixture.editor.document.text
        val path = Observer(project).relPath(file.virtualFile)!!
        val catalog = Catalog()
        fun code(call: Map<String, Any?>): Int = try {
            val (a, p) = catalog.prepare(call)
            catalog.runAll(project, a, p, false)
            0
        } catch (e: WyspError) {
            e.code
        }
        assertEquals(ErrorCode.ACTION_NOT_FOUND, code(mapOf("action_id" to "run_anything", "params" to emptyMap<String, Any>())))
        assertEquals(ErrorCode.INVALID_PARAMS, code(mapOf("action_id" to "rename_symbol", "params" to mapOf("target" to Refs.symbol(path, listOf("Greeter", "greet")), "new_name" to "1bad"))))
        assertEquals(ErrorCode.INVALID_PARAMS, code(mapOf("action_id" to "rename_symbol", "params" to mapOf("target" to Refs.symbol(path, listOf("Greeter", "greet")), "new_name" to "class"))))
        assertEquals(ErrorCode.TARGET_NOT_FOUND, code(mapOf("action_id" to "rename_symbol", "params" to mapOf("target" to Refs.symbol(path, listOf("Greeter", "nope")), "new_name" to "x"))))
        assertEquals(ErrorCode.TARGET_NOT_FOUND, code(mapOf("action_id" to "open_file", "params" to mapOf("target" to Refs.file("missing/File.java")))))
        assertEquals(before, myFixture.editor.document.text)
    }

    fun testRenameConflictIsReportedAndChangesNothing() {
        val text = source.replace("public static void main", "public String hello(String other) { return other; }\n\n    public static void main")
        val file = myFixture.configureByText("Greeter.java", text)
        val before = myFixture.editor.document.text
        val path = Observer(project).relPath(file.virtualFile)!!
        val catalog = Catalog()
        val (a, p) = catalog.prepare(mapOf("action_id" to "rename_symbol", "params" to mapOf("target" to Refs.symbol(path, listOf("Greeter", "greet")), "new_name" to "hello")))
        val error = try {
            catalog.runAll(project, a, p, false)
            null
        } catch (e: WyspError) {
            e
        }
        assertNotNull("a conflicting rename must fail", error)
        assertEquals(error!!.message, ErrorCode.PRECONDITION_FAILED, error.code)
        assertEquals(before, myFixture.editor.document.text)
    }

    fun testDryRunPreviewsWithoutChanging() {
        val file = myFixture.configureByText("Greeter.java", source)
        val before = myFixture.editor.document.text
        val path = Observer(project).relPath(file.virtualFile)!!
        val catalog = Catalog()
        val (a, p) = catalog.prepare(mapOf("action_id" to "rename_symbol", "params" to mapOf("target" to Refs.symbol(path, listOf("Greeter", "greet")), "new_name" to "welcome")))
        val result = catalog.runAll(project, a, p, true)
        assertNotNull(result["preview"])
        assertNull(result["undo_token"])
        assertEquals(before, myFixture.editor.document.text)
    }
}
