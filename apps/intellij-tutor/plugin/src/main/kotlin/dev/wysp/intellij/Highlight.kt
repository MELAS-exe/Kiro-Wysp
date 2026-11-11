package dev.wysp.intellij

import com.intellij.ide.projectView.ProjectView
import com.intellij.openapi.Disposable
import com.intellij.openapi.editor.ScrollType
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
import java.awt.Window
import javax.swing.AbstractButton
import javax.swing.JComponent
import javax.swing.JLabel
import javax.swing.JTabbedPane
import javax.swing.SwingUtilities
import javax.swing.Timer
import javax.swing.text.JTextComponent

/** Points at things for the user. Every method runs on the EDT and changes UI state only. */
class Highlighter(private val project: Project, private val parent: Disposable) {
    private var current: Disposable? = null

    /** What to point at, found in a background read action (PSI and highlighting data are slow on the EDT). */
    sealed class Plan {
        class Code(val path: String, val vf: VirtualFile, val range: IntRange?) : Plan()
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

    /** On the EDT: show the plan for `durationMs`, replacing the previous highlight. */
    fun highlight(plan: Plan, durationMs: Int): Map<String, Any?> {
        clear()
        val life = Disposer.newDisposable("wysp-highlight")
        Disposer.register(parent, life)
        current = life
        Timer(durationMs.coerceIn(500, 30_000)) { if (current === life) clear() else Disposer.dispose(life) }.apply {
            isRepeats = false
            start()
        }
        return when (plan) {
            is Plan.Code -> code(life, plan.path, plan.vf, plan.range)
            is Plan.InProjectView -> inProjectView(life, plan.vf, plan.what)
            is Plan.ToolWindowPlan -> toolWindow(life, plan.id)
            is Plan.Label -> label(life, plan.text)
        }
    }
    fun clear() {
        current?.let { Disposer.dispose(it) }
        current = null
    }

    private fun file(path: String): VirtualFile =
        Observer(project).resolve(path)
            ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "no $path in the project")

    // ---------------------------------------------------------------------------------------------- code
    private fun code(life: Disposable, path: String, vf: VirtualFile, range: IntRange?): Map<String, Any?> {
        val offset = range?.first ?: 0
        val editor = FileEditorManager.getInstance(project).openTextEditor(OpenFileDescriptor(project, vf, offset), false)
            ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "cannot open $path in an editor")
        if (range == null) {
            pointAt(life, editor.contentComponent, Rectangle(0, editor.scrollingModel.verticalScrollOffset, 0, 0), vf.name, frame = false)
            return mapOf("ok" to true, "located" to true)
        }
        val end = minOf(range.last + 1, editor.document.textLength)
        editor.scrollingModel.scrollTo(editor.offsetToLogicalPosition(range.first), ScrollType.CENTER)
        val attrs = TextAttributes(null, BACKGROUND, ACCENT, EffectType.ROUNDED_BOX, Font.PLAIN).apply { errorStripeColor = ACCENT }
        val h = editor.markupModel.addRangeHighlighter(range.first, end, HighlighterLayer.SELECTION - 1, attrs, HighlighterTargetArea.EXACT_RANGE)
        Disposer.register(life) { if (!editor.isDisposed) editor.markupModel.removeHighlighter(h) }
        return mapOf("ok" to true, "located" to true)
    }

    private fun inProjectView(life: Disposable, vf: VirtualFile, what: String): Map<String, Any?> {
        val tw = ToolWindowManager.getInstance(project).getToolWindow("Project")
            ?: throw WyspError(ErrorCode.TARGET_NOT_FOUND, "the Project tool window is not available")
        tw.show {
            ProjectView.getInstance(project).select(null, vf, false)
        }
        pointAt(life, tw.component, null, what, frame = false)
        return mapOf("ok" to true, "located" to true)
    }

    private fun toolWindow(life: Disposable, id: String): Map<String, Any?> {
        val manager = ToolWindowManager.getInstance(project)
        val tw = manager.getToolWindow(id)
            ?: manager.toolWindowIds.firstOrNull { it.equals(id, ignoreCase = true) }?.let { manager.getToolWindow(it) }
            ?: throw WyspError(
                ErrorCode.TARGET_NOT_FOUND,
                "no tool window '$id'. Available: ${manager.toolWindowIds.sorted().joinToString(", ")}",
            )
        tw.show {
            pointAt(life, tw.component, null, tw.stripeTitle, frame = true)
        }
        return mapOf("ok" to true, "located" to true)
    }

    // --------------------------------------------------------------------------------------------- label
    private class Target(val text: String, val component: Component, val rect: Rectangle?)

    private fun label(life: Disposable, wanted: String): Map<String, Any?> {
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
        pointAt(life, t.component, t.rect, t.text, frame = true)
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
    private fun pointAt(life: Disposable, target: Component, rect: Rectangle?, text: String, frame: Boolean) {
        val r = rect ?: Rectangle(0, 0, target.width, target.height)
        if (frame && target is JComponent) {
            runCatching {
                val glass = IdeGlassPaneUtil.find(target)
                val painter = FramePainter(target, r)
                glass.addPainter(target, painter, life)
                painter.setNeedsRepaint(true, target.rootPane)
                Disposer.register(life) { target.rootPane?.repaint() }
            }
        }
        val balloon = JBPopupFactory.getInstance()
            .createHtmlTextBalloonBuilder("<b>Wysp</b>: ${escape(LabelMatch.visible(listOf(text)).firstOrNull() ?: "here")}", MessageType.INFO, null)
            .setHideOnClickOutside(true)
            .setHideOnKeyOutside(false)
            .createBalloon()
        Disposer.register(life, balloon)
        val point = if (rect == null && !frame) Point(minOf(r.width / 2, JBUI.scale(160)), r.y + JBUI.scale(16)) else Point(r.x + r.width / 2, r.y + r.height)
        balloon.show(RelativePoint(target, point), Balloon.Position.below)
    }

    private fun escape(s: String) = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    private class FramePainter(private val target: Component, private val rect: Rectangle) : AbstractPainter() {
        override fun needsRepaint(): Boolean = true

        override fun executePaint(component: Component, g: Graphics2D) {
            if (!target.isShowing) return
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
        val ACCENT: Color = JBColor(Color(0xF5A623), Color(0xF5A623))
        val BACKGROUND: Color = JBColor(Color(0xFFF1C9), Color(0x4D4020))
    }
}
