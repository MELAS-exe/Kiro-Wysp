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

    fun testLinesRefResolvesToWholeLines() {
        myFixture.configureByText("Greeter.java", source)
        val plan = Highlighter(project, testRootDisposable).resolve(Refs.lines("Greeter.java", 4, 5))
        plan as Highlighter.Plan.Code
        assertTrue(plan.wholeLines)
        val doc = myFixture.editor.document
        assertEquals(doc.getLineStartOffset(3), plan.range!!.first)
        assertEquals(doc.getLineEndOffset(4), plan.range!!.last + 1)
        assertEquals(Ref.Lines("a/B.java", 4, 6), Refs.parse(Refs.lines("a/B.java", 4, 6)))
        assertNull(Refs.parse("intellij://lines/a/B.java:6-4"))
        assertNull(Refs.parse("intellij://lines/a/B.java:0"))
    }

    fun testContextCarriesCodeAtCaretOnly() {
        myFixture.configureByText("Greeter.java", source)
        val ctx = Observer(project).context(snapshot())
        @Suppress("UNCHECKED_CAST")
        val facts = ctx["facts"] as Map<String, Any?>
        val code = facts["code_at_caret"] as String
        assertTrue(code, Regex("""^\s*\d+\| public String greet""").containsMatchIn(code))
        assertTrue(facts.toString(), Regex("""\d+-\d+""").matches(facts["code_at_caret_lines"] as String))
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

    /** Survey (level full, no root): the whole project tree, by names only; sensitive files and noise stay out. */
    fun testFullObservationSurveysTheProjectTree() {
        myFixture.addFileToProject("src/app/Main.java", "class Main {}")
        myFixture.addFileToProject("src/app/util/Helper.java", "class Helper {}")
        myFixture.addFileToProject(".env", "API_KEY=sk-live-do-not-leak")
        myFixture.addFileToProject("keys/server.pem", "-----BEGIN-----")
        myFixture.addFileToProject("build/out.txt", "build output")
        myFixture.configureByText("Greeter.java", source)
        val obs = Observer(project).observe(mapOf("level" to "full"), snapshot(), 3)
        val ents = entities(obs)
        val labels = ents.map { it["label"] }
        assertTrue(labels.toString(), labels.containsAll(listOf("Main.java", "Helper.java", "util", "Greeter.java")))
        val text = Json.write(obs)
        assertFalse(text, text.contains(".env"))
        assertFalse(text, text.contains("server.pem"))
        assertFalse(text, text.contains("out.txt"))
        assertFalse(text, text.contains("do-not-leak"))
        // Referential integrity and counts: each ref once, parents present.
        val refs = ents.map { it["ref"] }
        assertEquals(refs.size, refs.toSet().size)
        for (e in ents) e["parent"]?.let { assertTrue("parent $it", it in refs.toSet()) }
        @Suppress("UNCHECKED_CAST")
        val counts = obs["counts"] as Map<String, Int>
        assertEquals(ents.count { it["kind"] == "file" }, counts["file"])
        // A focus observation does not walk the tree.
        val focusLabels = entities(Observer(project).observe(mapOf("level" to "focus"), snapshot(), 3)).map { it["label"] }
        assertFalse(focusLabels.toString(), focusLabels.contains("Helper.java"))
    }

    /** Persistent highlight (contract 1.1): stays until cleared; the user editing it ends it; our own moves do not. */
    fun testPersistentHighlightEndsWhenTheUserEditsIt() {
        myFixture.configureByText("Greeter.java", source)
        val dismissed = mutableListOf<String>()
        val h = Highlighter(project, testRootDisposable) { dismissed += it }
        val ref = Refs.symbol("Greeter.java", listOf("Greeter", "greet"))
        val plan = h.resolve(ref) as Highlighter.Plan.Code
        val at = plan.range!!.first + 1

        // No timer: it is still there after a clear request asks for it, and clearing says so.
        h.highlight(plan, 0, ref)
        assertTrue(h.clearActive())
        assertFalse("nothing left to clear", h.clearActive())

        // An edit right after showing is Wysp's own doing (or the IDE's), not the user's.
        h.highlight(plan, 0, ref)
        com.intellij.openapi.command.WriteCommandAction.runWriteCommandAction(project) { myFixture.editor.document.insertString(at, " ") }
        assertTrue("grace period: $dismissed", dismissed.isEmpty())

        // The user edits inside the highlighted range later on: it comes down and the Core is told.
        Thread.sleep(Highlighter.GRACE_MS + 200)
        com.intellij.openapi.command.WriteCommandAction.runWriteCommandAction(project) { myFixture.editor.document.insertString(at, " ") }
        assertEquals(listOf(ref), dismissed)
        assertFalse("already down", h.clearActive())

        // A timed highlight (a narration cue) never reports a dismissal and replaces a persistent one.
        h.highlight(plan, 0, ref)
        h.highlight(plan, 1500, ref)
        assertTrue(h.clearActive())
    }

    /** Exploration: `observe {level: full, root: dir}` returns that folder's files with symbols and project imports. */
    fun testSubtreeObservationForExploration() {
        myFixture.addFileToProject("src/app/Movement.java", "package app;\npublic class Movement { public int id() { return 1; } }")
        myFixture.addFileToProject("src/app/Service.java", "package app;\nimport app.Movement;\nimport java.util.List;\npublic class Service { Movement m; void run() {} }")
        myFixture.addFileToProject("src/app/.env", "API_KEY=sk-live-do-not-leak")
        myFixture.addFileToProject("src/other/Elsewhere.java", "package other;\npublic class Elsewhere {}")
        myFixture.configureByText("Greeter.java", source)
        val dir = Refs.dir("src/app")
        val obs = Observer(project).observe(mapOf("level" to "full", "root" to dir), snapshot(), 5)
        val ents = entities(obs)
        val byLabel = ents.associateBy { it["label"] }
        // Only this folder's subtree: its files, their symbols, the ancestors; not the sibling folder or the editor's file.
        assertTrue(ents.toString(), byLabel.containsKey("Movement.java") && byLabel.containsKey("Service.java"))
        assertFalse(byLabel.containsKey("Elsewhere.java"))
        assertFalse(byLabel.containsKey("Greeter.java"))
        val labels = ents.filter { it["kind"] == "symbol" }.map { it["label"] }
        assertTrue(labels.toString(), labels.containsAll(listOf("Movement", "Service", "run", "id")))
        // Dependencies are refs of project files only: java.util.List is a library and does not appear.
        @Suppress("UNCHECKED_CAST")
        val deps = (byLabel["Service.java"]!!["props"] as Map<String, Any?>)["depends_on"] as List<String>
        assertEquals(listOf(Refs.file("src/app/Movement.java")), deps)
        @Suppress("UNCHECKED_CAST")
        assertEquals("done", (byLabel["Movement.java"]!!["props"] as Map<String, Any?>)["symbols"])
        // Sensitive files never appear, by name or by content.
        val text = Json.write(obs)
        assertFalse(text, text.contains(".env"))
        assertFalse(text, text.contains("do-not-leak"))
        // No code bodies: signatures and names only.
        assertFalse(text, text.contains("return 1"))
        // Referential integrity: every parent is in the observation.
        val refs = ents.map { it["ref"] }.toSet()
        for (e in ents) e["parent"]?.let { assertTrue("parent $it", it in refs) }
        // One file: its symbols and dependencies, nothing else.
        val one = entities(Observer(project).observe(mapOf("level" to "full", "root" to Refs.file("src/app/Service.java")), snapshot(), 6))
        assertTrue(one.any { it["label"] == "run" })
        assertFalse(one.any { it["label"] == "Movement.java" })
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
