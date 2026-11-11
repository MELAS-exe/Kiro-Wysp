package dev.wysp.intellij.ui

import com.intellij.openapi.Disposable
import com.intellij.openapi.util.Disposer
import com.intellij.ui.jcef.JBCefApp
import com.intellij.ui.jcef.JBCefBrowser
import javax.swing.JComponent

/**
 * The embedded Panel. JCEF ships as an optional bundled plugin, so this class is only touched behind
 * [create], which returns null when JCEF is missing or unsupported.
 */
class PanelBrowser private constructor(private val browser: JBCefBrowser) {
    val component: JComponent get() = browser.component

    fun load(url: String) = browser.loadURL(url)

    companion object {
        fun create(url: String, parent: Disposable): PanelBrowser? = try {
            if (!JBCefApp.isSupported()) {
                null
            } else {
                val b = JBCefBrowser(url)
                Disposer.register(parent, b)
                PanelBrowser(b)
            }
        } catch (_: LinkageError) {
            null // the JCEF plugin is not installed or disabled
        }
    }
}
