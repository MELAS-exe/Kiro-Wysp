package dev.wysp.intellij

import com.intellij.ide.projectView.ProjectView
import com.intellij.openapi.Disposable
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.editor.EditorFactory
import com.intellij.openapi.editor.ScrollType
import com.intellij.openapi.editor.event.CaretEvent
import com.intellij.openapi.editor.event.CaretListener
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.editor.event.EditorMouseEvent
import com.intellij.openapi.editor.event.EditorMouseListener
import com.intellij.openapi.editor.markup.EffectType
import com.intellij.openapi.editor.markup.HighlighterLayer
import com.intellij.openapi.editor.markup.HighlighterTargetArea
import com.intellij.openapi.editor.markup.TextAttributes
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.OpenFileDescriptor
import com.intellij.openapi.module.ModuleManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.roots.ModuleRootManager
import com.intellij.openapi.ui.AbstractPainter
import com.intellij.openapi.ui.MessageType
import com.intellij.openapi.ui.popup.Balloon
import com.intellij.openapi.ui.popup.JBPopupFactory
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.wm.IdeGlassPaneUtil
import com.intellij.openapi.wm.ToolWindowManager
import com.intellij.ui.JBColor
import com.intellij.ui.awt.RelativePoint
import com.intellij.util.ui.JBUI
import dev.wysp.intellij.actions.resolveSymbol
import java.awt.AWTEvent
import java.awt.BasicStroke
import java.awt.Color
import java.awt.Component
import java.awt.Container
import java.awt.Font
import java.awt.Graphics2D
import java.awt.KeyboardFocusManager
import java.awt.Point
import java.awt.Rectangle
import java.awt.RenderingHints
import java.awt.Toolkit
import java.awt.event.AWTEventListener
import java.awt.event.MouseEvent
import java.awt.Window
import javax.swing.AbstractButton
import javax.swing.JComponent
import javax.swing.JLabel
import javax.swing.JTabbedPane
import javax.swing.SwingUtilities
import javax.swing.Timer
import javax.swing.text.JTextComponent

/**
 * Points at things for the user. Every method runs on the EDT and changes UI state only.
 *
 * A highlight with `durationMs <= 0` is persistent (contract 1.1): no timer; it stays until [clear], until another
 * highlight replaces it, or until the user interacts with what it points at, which is reported to `dismissed`.
 */
class Highlighter(
    private val project: Project,
    private val parent: Disposable,
    private val dismissed: (String) -> Unit = {},
) {
    private var current: Disposable? = null
    private var currentRef: String? = null
    private var armedAtMs = 0L

    /** What to point at, found in a background read action (PSI and highlighting data are slow on the EDT). */
    sealed class Plan {
        class Code(val path: String, val vf: VirtualFile, val range: IntRange?, val wholeLines: Boolean = false) : Plan()
        class InProjectView(val vf: VirtualFile, val what: String) : Plan()
        class ToolWindowPlan(val id: String) : Plan()
        class Label(val text: String) : Plan()
    }

    fun resolve(ref: String): Plan {
        val r = Refs.parse(ref) ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "not an intellij:// ref: $ref")
        return when (r) {
            is Ref.File -> Plan.Code(r.path, file(r.path), null)
            is Ref.Symbol -> {
                val (path, vf, s) = resolveSymbol(project, ref)
                // Long classes: frame the declaration line rather than the whole body.
                val name = s.element.textOffset
                val range = if (s.endLine - s.line > 60) name until name + s.name.length else s.startOffset until s.endOffset
                Plan.Code(path, vf, range)
            }
            is Ref.Problem -> {
                val vf = file(r.path)
                val doc = FileDocumentManager.getInstance().getDocument(vf) ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "cannot read ${r.path}")
                val range = Observer(project).problemRange(doc, r.line, r.n)
                    ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "no problem ${r.n} on line ${r.line} of ${r.path} (fixed already?)")
                Plan.Code(r.path, vf, range)
            }
            is Ref.Lines -> {
                val vf = file(r.path)
                val doc = FileDocumentManager.getInstance().getDocument(vf) ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "cannot read ${r.path}")
                if (doc.lineCount == 0 || r.from > doc.lineCount) {
                    throw WyspError(ErrorCode.TARGET_NOT_FOUND, "${r.path} has ${doc.lineCount} lines, no line ${r.from}")
                }
                val to = minOf(r.to, doc.lineCount)
                Plan.Code(r.path, vf, doc.getLineStartOffset(r.from - 1) until maxOf(doc.getLineEndOffset(to - 1), doc.getLineStartOffset(r.from - 1) + 1), wholeLines = true)
            }
            is Ref.Dir -> Plan.InProjectView(file(r.path), r.path)
            is Ref.Module -> {
                val m = ModuleManager.getInstance(project).findModuleByName(r.name)
                    ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "no module ${r.name}")
                val root = ModuleRootManager.getInstance(m).contentRoots.firstOrNull()
                    ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "module ${r.name} has no content root")
                Plan.InProjectView(root, r.name)
            }
            is Ref.Project -> Plan.ToolWindowPlan("Project")
            is Ref.ToolWindow -> Plan.ToolWindowPlan(r.id)
            is Ref.Run -> Plan.Label(r.name)
            is Ref.Label -> Plan.Label(r.text)
        }
    }

    /** On the EDT: show the plan for `durationMs` (0: until cleared), replacing the previous highlight. */
    fun highlight(plan: Plan, durationMs: Int, ref: String? = null): Map<String, Any?> {
        clear()
        val persistent = durationMs <= 0
        val life = Disposer.newDisposable("wysp-highlight")
        Disposer.register(parent, life)
        current = life
        currentRef = ref
        // Our own scrolling, opening and caret placement happen in this window and never count as the user's.
        armedAtMs = System.currentTimeMillis() + GRACE_MS
        if (!persistent) {
            Timer(durationMs.coerceIn(500, 30_000)) { if (current === life) clear() else Disposer.dispose(life) }.apply {
                isRepeats = false
                start()
            }
        }
        return try {
            when (plan) {
                is Plan.Code -> code(life, plan.path, plan.vf, plan.range, plan.wholeLines, persistent)
                is Plan.InProjectView -> inProjectView(life, plan.vf, plan.what, persistent)
                is Plan.ToolWindowPlan -> toolWindow(life, plan.id, persistent)
                is Plan.Label -> label(life, plan.text, persistent)
            }
        } catch (e: Throwable) {
            if (current === life) clear() // nothing was shown: nothing stays active
            throw e
        }
    }

    fun clear() {
        current?.let { Disposer.dispose(it) }
        current = null
        currentRef = null
    }

    /** Take the highlight down on request. True when there was one. */
    fun clearActive(): Boolean {
        val had = current != null
        clear()
        return had
    }

    /** The user interacted with what is highlighted: take it down and say so. */
    private fun dismiss(life: Disposable) {
        if (current !== life || System.currentTimeMillis() < armedAtMs) return
        val ref = currentRef
        clear()
        if (ref != null) dismissed(ref)
    }

    /** A mouse press anywhere on screen inside `bounds()` (screen coordinates) is the user using the highlighted control. */
    private fun dismissOnClickIn(life: Disposable, bounds: () -> Rectangle?) {
        val listener = AWTEventListener { e ->
            if (e is MouseEvent && e.id == MouseEvent.MOUSE_PRESSED) {
                val r = bounds() ?: return@AWTEventListener
                if (r.contains(e.locationOnScreen)) dismiss(life)
            }
        }
        Toolkit.getDefaultToolkit().addAWTEventListener(listener, AWTEvent.MOUSE_EVENT_MASK)
        Disposer.register(life) { Toolkit.getDefaultToolkit().removeAWTEventListener(listener) }
    }

    /** Code: a click, a caret move or an edit inside the highlighted range (any click or edit, when a whole file is pointed at). */
    private fun dismissOnUseOf(life: Disposable, editor: Editor, range: IntRange?) {
        fun inside(offset: Int) = range == null || offset in range.first..(range.last + 1)
        editor.addEditorMouseListener(object : EditorMouseListener {
            override fun mousePressed(event: EditorMouseEvent) {
                val offset = editor.logicalPositionToOffset(editor.xyToLogicalPosition(event.mouseEvent.point))
                if (inside(offset)) dismiss(life)
            }
        }, life)
        EditorFactory.getInstance().eventMulticaster.addCaretListener(object : CaretListener {
            override fun caretPositionChanged(event: CaretEvent) {
                if (event.editor === editor && range != null && inside(editor.caretModel.offset)) dismiss(life)
            }
        }, life)
        EditorFactory.getInstance().eventMulticaster.addDocumentListener(object : DocumentListener {
            override fun documentChanged(event: DocumentEvent) {
                if (event.document !== editor.document) return
                if (range == null || (event.offset <= range.last + 1 && event.offset + event.oldLength >= range.first)) dismiss(life)
            }
        }, life)
    }

    private fun file(path: String): VirtualFile =
        Observer(project).resolve(path)
            ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "no $path in the project")

    // ---------------------------------------------------------------------------------------------- code
    private fun code(life: Disposable, path: String, vf: VirtualFile, range: IntRange?, wholeLines: Boolean = false, persistent: Boolean = false): Map<String, Any?> {
        val offset = range?.first ?: 0
        val editor = FileEditorManager.getInstance(project).openTextEditor(OpenFileDescriptor(project, vf, offset), false)
            ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "cannot open $path in an editor")
        if (range == null) {
            // A whole file: open it and frame the editor, so it is obvious which one is meant.
            pointAt(life, editor.component, null, vf.name, frame = true, persistent = persistent)
            if (persistent) dismissOnUseOf(life, editor, null)
            return mapOf("ok" to true, "located" to true)
        }
        val end = minOf(range.last + 1, editor.document.textLength)
        editor.scrollingModel.scrollTo(editor.offsetToLogicalPosition(range.first), ScrollType.CENTER)
        val attrs = TextAttributes(null, BACKGROUND, ACCENT, EffectType.ROUNDED_BOX, Font.PLAIN).apply { errorStripeColor = ACCENT }
        val h = editor.markupModel.addRangeHighlighter(range.first, end, HighlighterLayer.SELECTION - 1, attrs,
            if (wholeLines) HighlighterTargetArea.LINES_IN_RANGE else HighlighterTargetArea.EXACT_RANGE)
        Disposer.register(life) { if (!editor.isDisposed) editor.markupModel.removeHighlighter(h) }
        if (persistent) dismissOnUseOf(life, editor, range)
        return mapOf("ok" to true, "located" to true)
    }

    private fun inProjectView(life: Disposable, vf: VirtualFile, what: String, persistent: Boolean = false): Map<String, Any?> {
        val tw = ToolWindowManager.getInstance(project).getToolWindow("Project")
            ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "the Project tool window is not available")
        var framed = false
        fun frameWholeWindow() {
            if (framed || Disposer.isDisposed(life)) return
            framed = true
            pointAt(life, tw.component, null, what, frame = true, persistent = persistent)
            if (persistent) dismissOnClickIn(life) { screenBounds(tw.component) }
        }
        tw.show {
            // Selecting (and expanding the tree down to the item) finishes later: frame the row once it is there.
            ProjectView.getInstance(project).selectCB(null, vf, false).doWhenDone {
                if (framed || Disposer.isDisposed(life)) return@doWhenDone
                val tree = ProjectView.getInstance(project).currentProjectViewPane?.tree
                val path = tree?.selectionPath
                if (tree == null || path == null) return@doWhenDone frameWholeWindow()
                tree.scrollPathToVisible(path)
                // The whole row, recomputed on every paint so the frame stays on it when the tree scrolls.
                val row = { tree.getPathBounds(path)?.let { r -> Rectangle(tree.visibleRect.x, r.y, tree.visibleRect.width, r.height) } }
                framed = true
                pointAt(life, tree, null, what, frame = true, persistent = persistent, rectOf = row)
                if (persistent) dismissOnClickIn(life) { row()?.let { screenBounds(tree, it) } }
            }
        }
        // If the tree never answers, still show where to look.
        Timer(2500) { frameWholeWindow() }.apply {
            isRepeats = false
            start()
        }
        return mapOf("ok" to true, "located" to true)
    }

    private fun toolWindow(life: Disposable, id: String, persistent: Boolean = false): Map<String, Any?> {
        val manager = ToolWindowManager.getInstance(project)
        val tw = manager.getToolWindow(id)
            ?: manager.toolWindowIds.firstOrNull { it.equals(id, ignoreCase = true) }?.let { manager.getToolWindow(it) }
            ?: throw WyspError(
                ErrorCode.TARGET_NOT_FOUND,
                "no tool window '$id'. Available: ${manager.toolWindowIds.sorted().joinToString(", ")}",
            )
        tw.show {
            pointAt(life, tw.component, null, tw.stripeTitle, frame = true, persistent = persistent)
        }
        if (persistent) dismissOnClickIn(life) { screenBounds(tw.component) }
        return mapOf("ok" to true, "located" to true)
    }

    // --------------------------------------------------------------------------------------------- label
    private class Target(val text: String, val component: Component, val rect: Rectangle?)

    private fun label(life: Disposable, wanted: String, persistent: Boolean = false): Map<String, Any?> {
        val targets = visibleTargets()
        val i = LabelMatch.best(wanted, targets.map { it.text })
        if (i == null) {
            val visible = LabelMatch.visible(targets.map { it.text })
            throw WyspError(
                ErrorCode.TARGET_NOT_FOUND,
                "'$wanted' is not visible in the IDE right now. Visible labels: ${visible.joinToString(", ")}",
                mapOf("located" to false, "visible" to visible),
            )
        }
        val t = targets[i]
        pointAt(life, t.component, t.rect, t.text, frame = true, persistent = persistent)
        if (persistent) dismissOnClickIn(life) { screenBounds(t.component, t.rect) }
        return mapOf("ok" to true, "located" to true, "matched" to t.text)
    }

    /** Showing components with a label, in the active window first (a dialog), then the project frame. */
    private fun visibleTargets(): List<Target> {
        val active = KeyboardFocusManager.getCurrentKeyboardFocusManager().activeWindow
        val frame = com.intellij.openapi.wm.WindowManager.getInstance().getFrame(project)
        val windows = (listOfNotNull(active, frame) + Window.getWindows().filter { it.isShowing }).distinct().filter { it.isShowing }
        val wysp = ToolWindowManager.getInstance(project).getToolWindow(Wysp.TOOL_WINDOW_ID)?.component
        val out = mutableListOf<Target>()
        for (w in windows) {
            val queue = ArrayDeque<Component>()
            queue += w
            while (queue.isNotEmpty() && out.size < 2000) {
                val c = queue.removeFirst()
                if (!c.isShowing || c.width <= 0 || c.height <= 0) continue
                if (wysp != null && SwingUtilities.isDescendingFrom(c, wysp)) continue // never Wysp's own text
                if (c is JTextComponent || c.javaClass.name.endsWith("EditorComponentImpl")) continue // user content
                texts(c).forEach { out += Target(it, c, null) }
                if (c is JTabbedPane) {
                    for (k in 0 until c.tabCount) c.getTitleAt(k)?.takeIf { it.isNotBlank() }?.let { out += Target(it, c, c.getBoundsAt(k)) }
                }
                if (c is Container) queue.addAll(c.components)
            }
        }
        return out
    }

    private fun texts(c: Component): List<String> {
        if (c is Window) return emptyList() // the frame title is not a control
        val out = LinkedHashSet<String>()
        when (c) {
            is AbstractButton -> c.text?.let { out += it }
            is JLabel -> c.text?.let { out += it }
        }
        runCatching { c.accessibleContext?.accessibleName }.getOrNull()?.let { out += it }
        (c as? JComponent)?.toolTipText?.let { out += it.substringBefore('(').trim() } // icon buttons: "Run 'Main' (Shift+F10)"
        return out.filter { it.isNotBlank() && it.length <= 80 && !LANDMARKS.matches(it) }
    }

    // -------------------------------------------------------------------------------------------- pointer
    private fun pointAt(
        life: Disposable,
        target: Component,
        rect: Rectangle?,
        text: String,
        frame: Boolean,
        persistent: Boolean = false,
        rectOf: (() -> Rectangle?)? = null,
    ) {
        val r = rectOf?.invoke() ?: rect ?: Rectangle(0, 0, target.width, target.height)
        if (frame && target is JComponent) {
            runCatching {
                val glass = IdeGlassPaneUtil.find(target)
                val painter = FramePainter(target, rectOf ?: { r })
                glass.addPainter(target, painter, life)
                painter.setNeedsRepaint(true, target.rootPane)
                Disposer.register(life) { target.rootPane?.repaint() }
            }
        }
        val balloon = JBPopupFactory.getInstance()
            .createHtmlTextBalloonBuilder("<b>Wysp</b>: ${escape(LabelMatch.visible(listOf(text)).firstOrNull() ?: "here")}", MessageType.INFO, null)
            // A persistent pointer outlives the user's other clicks and actions; only using the target, or Wysp, ends it.
            .setHideOnClickOutside(!persistent)
            .setHideOnKeyOutside(false)
            .setHideOnAction(!persistent)
            .createBalloon()
        Disposer.register(life, balloon)
        val point = if (rect == null && !frame) Point(minOf(r.width / 2, JBUI.scale(160)), r.y + JBUI.scale(16)) else Point(r.x + r.width / 2, r.y + r.height)
        balloon.show(RelativePoint(target, point), Balloon.Position.below)
    }

    /** Where a component (or a rectangle inside it) is on screen, or null when it is not showing any more. */
    private fun screenBounds(c: Component, inside: Rectangle? = null): Rectangle? {
        if (!c.isShowing) return null
        val origin = c.locationOnScreen
        val r = inside ?: Rectangle(0, 0, c.width, c.height)
        return Rectangle(origin.x + r.x, origin.y + r.y, r.width, r.height)
    }

    private fun escape(s: String) = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    private class FramePainter(private val target: Component, private val rectOf: () -> Rectangle?) : AbstractPainter() {
        override fun needsRepaint(): Boolean = true

        override fun executePaint(component: Component, g: Graphics2D) {
            if (!target.isShowing) return
            val rect = rectOf() ?: return
            val r = SwingUtilities.convertRectangle(target, rect, component)
            val pad = JBUI.scale(3)
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
            g.color = ACCENT
            g.stroke = BasicStroke(JBUI.scale(3).toFloat())
            g.drawRoundRect(r.x - pad, r.y - pad, r.width + 2 * pad, r.height + 2 * pad, JBUI.scale(10), JBUI.scale(10))
        }
    }

    companion object {
        // Accessible names of layout regions, not of controls a student would click.
        private val LANDMARKS = Regex("(?i)^(status bar|left toolbar|right toolbar|main toolbar.*|application icon|.* - intellij idea)$")
        val ACCENT: Color = JBColor(Color(0x6503FC), Color(0xCA84FC)) // the mascot's violet on light themes, its lilac on dark
        val BACKGROUND: Color = JBColor(Color(0xF0E2FF), Color(0x3B2470))
        /** After showing a highlight, the IDE's own scrolling and caret placement for this long never count as the user's. */
        const val GRACE_MS = 1500L
    }
}
