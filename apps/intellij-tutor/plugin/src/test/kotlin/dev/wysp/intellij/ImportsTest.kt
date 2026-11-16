package dev.wysp.intellij

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Import lines to dotted names, and names to the file paths they could be (no IDE needed). */
class ImportsTest {
    @Test
    fun `java imports, static and wildcard included`() {
        val text = """
            package a.b;

            import java.util.List;
            import static a.util.Strings.trim;
            import a.model.*;
            import a.model.Movement;
            // import commented.Out;
            public class X {}
        """.trimIndent()
        val names = Imports.names("java", text)
        assertTrue(names.toString(), names.containsAll(listOf("java.util.List", "a.util.Strings.trim", "a.model", "a.model.Movement")))
        assertEquals(names.distinct(), names)
    }

    @Test
    fun `kotlin imports have no semicolon, aliases are understood`() {
        assertEquals(listOf("a.b.C", "d.E"), Imports.names("kt", "import a.b.C\nimport d.E as F\n"))
    }

    @Test
    fun `python imports`() {
        val names = Imports.names("py", "import os.path\nfrom pkg.mod import thing\nfrom . import sibling\n")
        assertTrue(names.toString(), names.containsAll(listOf("pkg.mod", "os.path")))
    }

    @Test
    fun `other languages give nothing instead of a wrong guess`() {
        assertEquals(emptyList<String>(), Imports.names("md", "import a.b.C"))
    }

    @Test
    fun `a member import falls back to its class`() {
        val c = Imports.candidates("java", "a.util.Strings.trim").map { it.first }
        assertTrue(c.toString(), "a/util/Strings.java" in c && "a/util/Strings/trim.java" in c)
    }

    @Test
    fun `scanning is bounded`() {
        val big = (1..5000).joinToString("\n") { "import p.C$it;" }
        assertTrue(Imports.names("java", big).size <= Imports.MAX_PER_FILE * 3)
    }
}
