package dev.wysp.intellij.ui

import com.intellij.ide.BrowserUtil
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.components.ActionLink
import com.intellij.ui.components.JBLabel
import com.intellij.ui.content.ContentFactory
import com.intellij.util.ui.JBUI
import dev.wysp.intellij.WyspService
import java.awt.BorderLayout
import java.awt.FlowLayout
import javax.swing.JButton
import javax.swing.JPanel

/** The Wysp tool window: the shared Panel (served by the Core) in an embedded browser, plus the connection. */
class WyspToolWindowFactory : ToolWindowFactory, DumbAware {
    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val settings = WyspSettings.get()
        val service = WyspService.get()
        val root = JPanel(BorderLayout())
        val content = ContentFactory.getInstance().createContent(root, "", false)

        val status = JBLabel()
        val connect = JButton()
        val bar = JPanel(FlowLayout(FlowLayout.LEFT, JBUI.scale(6), JBUI.scale(2)))
        bar.add(status)
        bar.add(connect)
        fun refresh() {
            val s = service.status
            status.text = when (s) {
                "connected" -> "Connected to Wysp Core"
                "connecting" -> "Connecting…"
                "refused" -> "Refused: ${service.lastError ?: "check the token"}"
                "stopped" -> "Not connected"
                else -> "Core not reachable (retrying)"
            }
            connect.text = if (s == "stopped" || s == "refused") "Connect" else "Disconnect"
        }
        connect.addActionListener {
            if (service.status == "stopped" || service.status == "refused") service.connect() else service.disconnect()
            refresh()
        }
        service.addStatusListener(content) { _, _ -> ApplicationManager.getApplication().invokeLater { refresh() } }
        refresh()
        root.add(bar, BorderLayout.NORTH)

        val url = settings.panelUrl
        val browser = PanelBrowser.create(url, content)
        if (browser != null) {
            root.add(browser.component, BorderLayout.CENTER)
            bar.add(JButton("Reload").apply { addActionListener { browser.load(settings.panelUrl) } })
        } else {
            val fallback = JPanel(FlowLayout(FlowLayout.LEFT))
            fallback.add(JBLabel("This IDE cannot embed a browser. Open the Panel in your browser:"))
            fallback.add(ActionLink(url) { BrowserUtil.browse(url) })
            root.add(fallback, BorderLayout.CENTER)
        }
        toolWindow.contentManager.addContent(content)
    }
}
