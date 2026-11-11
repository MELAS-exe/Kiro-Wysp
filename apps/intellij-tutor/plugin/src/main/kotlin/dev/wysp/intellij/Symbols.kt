package dev.wysp.intellij

import com.intellij.ide.structureView.StructureViewTreeElement
import com.intellij.ide.structureView.TreeBasedStructureViewBuilder
import com.intellij.lang.LanguageStructureViewBuilder
import com.intellij.openapi.editor.Document
import com.intellij.openapi.util.Disposer
import com.intellij.psi.PsiDocumentManager
import com.intellij.psi.PsiElement
import com.intellij.psi.PsiFile
import com.intellij.psi.PsiNamedElement

/** A named element of a file, as the IDE's structure view shows it. */
class SymbolInfo(
    val parts: List<String>, // qualified name parts, e.g. [Greeter, greet]
    val element: PsiElement,
    val type: String, // class | interface | function | field | other
    val line: Int, // 1-based line of the name
    val endLine: Int,
    val startOffset: Int,
    val endOffset: Int,
    val signature: String,
) {
    val name: String get() = parts.last()
    val parentParts: List<String>? get() = if (parts.size > 1) parts.dropLast(1) else null
}

/**
 * Symbols come from the generic structure view model, so every language with a Structure tool window
 * (Java, Kotlin, Python, JavaScript, ...) works without language-specific code. Call inside a read action.
 */
object Symbols {
    const val MAX_DEPTH = 3
    const val MAX_PER_FILE = 150

    fun collect(file: PsiFile, maxDepth: Int = MAX_DEPTH, max: Int = MAX_PER_FILE): List<SymbolInfo> {
        val builder = LanguageStructureViewBuilder.getInstance().getStructureViewBuilder(file) as? TreeBasedStructureViewBuilder
            ?: return emptyList()
        val document = PsiDocumentManager.getInstance(file.project).getDocument(file) ?: return emptyList()
        val model = builder.createStructureViewModel(null)
        val out = mutableListOf<SymbolInfo>()
        try {
            walk(model.root, emptyList(), 1, maxDepth, max, document, out)
        } finally {
            Disposer.dispose(model)
        }
        return out
    }

    private fun walk(
        node: StructureViewTreeElement,
        prefix: List<String>,
        depth: Int,
        maxDepth: Int,
        max: Int,
        document: Document,
        out: MutableList<SymbolInfo>,
    ) {
        if (depth > maxDepth) return
        val used = HashMap<String, Int>()
        for (child in node.children) {
            if (out.size >= max) return
            val tree = child as? StructureViewTreeElement ?: continue
            val element = tree.value as? PsiElement ?: continue
            if (!element.isValid || element is PsiFile) continue
            val text = tree.presentation.presentableText.orEmpty()
            val base = ((element as? PsiNamedElement)?.name ?: text.substringBefore('(').substringBefore(':').trim())
                .takeIf { it.isNotBlank() } ?: continue
            val seen = used.merge(base, 1, Int::plus)!!
            val name = if (seen == 1) base else "$base~$seen" // overloads: greet, greet~2
            val range = element.textRange ?: continue
            val nameOffset = element.textOffset.coerceIn(0, document.textLength)
            val parts = prefix + name
            val kids = tree.children
            out += SymbolInfo(
                parts = parts,
                element = element,
                type = typeOf(element, text, kids.isNotEmpty()),
                line = document.getLineNumber(nameOffset) + 1,
                endLine = document.getLineNumber(range.endOffset.coerceIn(0, document.textLength)) + 1,
                startOffset = range.startOffset,
                endOffset = range.endOffset,
                signature = Privacy.oneLine(text, Privacy.MAX_SIGNATURE),
            )
            walk(tree, parts, depth + 1, maxDepth, max, document, out)
        }
    }

    /** Language-neutral guess from the PSI class name (PsiMethod, KtNamedFunction, PyFunction, JSClass...). */
    fun typeOf(element: PsiElement, presentable: String, hasChildren: Boolean): String {
        val n = element.javaClass.simpleName.lowercase()
        val isInterface = runCatching {
            element.javaClass.getMethod("isInterface").invoke(element) == true
        }.getOrDefault(false)
        return when {
            isInterface || "interface" in n || "trait" in n -> "interface"
            "function" in n || "method" in n || "constructor" in n -> "function"
            "class" in n || "object" in n || "enum" in n || "record" in n || "struct" in n -> "class"
            "field" in n || "property" in n || "variable" in n || "constant" in n -> "field"
            '(' in presentable -> "function"
            hasChildren -> "class"
            else -> "other"
        }
    }

    fun find(symbols: List<SymbolInfo>, parts: List<String>): SymbolInfo? =
        symbols.firstOrNull { it.parts == parts }
            ?: symbols.filter { it.name == parts.last() }.singleOrNull() // a short name, when unambiguous

    /** The innermost symbol whose range contains the offset (functions and classes first). */
    fun at(symbols: List<SymbolInfo>, offset: Int, types: Set<String>? = null): SymbolInfo? =
        symbols.filter { offset >= it.startOffset && offset <= it.endOffset && (types == null || it.type in types) }
            .minByOrNull { it.endOffset - it.startOffset }
}
