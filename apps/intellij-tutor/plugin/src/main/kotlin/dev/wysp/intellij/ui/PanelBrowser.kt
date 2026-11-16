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
        /**
         * The Panel URL carrying the pairing token in the fragment, which never leaves the browser (not sent to the
         * Core, not logged). The Panel keeps it in memory and strips it from the address at once; it lets the Panel ask
         * the Core to listen, since this embedded browser has no speech recognition of its own. Local Cores only.
         */
        fun withToken(url: String, token: String?): String =
            if (token.isNullOrBlank()) url else url.substringBefore('#') + "#wysp_token=" + token

        /** `url` with a one-time query parameter, so the browser fetches the Panel page again. */
        fun fresh(url: String): String {
            val hash = url.indexOf('#').let { if (it < 0) url.length else it }
            val base = url.substring(0, hash)
            return base + (if ('?' in base) "&" else "?") + "r=" + System.currentTimeMillis() + url.substring(hash)
        }
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
