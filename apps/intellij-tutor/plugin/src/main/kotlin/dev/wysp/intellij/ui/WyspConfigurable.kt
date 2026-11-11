package dev.wysp.intellij.ui

import com.intellij.openapi.options.BoundConfigurable
import com.intellij.openapi.ui.DialogPanel
import com.intellij.ui.dsl.builder.AlignX
import com.intellij.ui.dsl.builder.bindSelected
import com.intellij.ui.dsl.builder.bindText
import com.intellij.ui.dsl.builder.panel

/** Settings > Tools > Wysp Tutor. */
class WyspConfigurable : BoundConfigurable("Wysp Tutor") {
    override fun createPanel(): DialogPanel {
        val options = WyspSettings.get().state
        return panel {
            row("Core URL:") {
                textField().bindText(options::coreUrl).align(AlignX.FILL)
                    .comment("The Core's adapter endpoint, normally ws://127.0.0.1:8765/ws/adapter")
            }
            row("Token file:") {
                textField().bindText(options::tokenFile).align(AlignX.FILL)
                    .comment("Leave empty for ~/.wysp/token (written by the Core). The token itself is never stored here.")
            }
            row {
                checkBox("Connect automatically when a project opens").bindSelected(options::autoConnect)
            }
            row {
                comment(
                    "Privacy: Wysp reads the project structure, open files, code structure and problems. Only the " +
                        "selection and the code at the caret are sent as text, to the local Core, which forwards them " +
                        "to the configured LLM provider. Nothing is read from sensitive files (.env, keys, certificates, " +
                        "credentials, secrets). Wysp changes code only after your approval, and every change can be undone.",
                )
            }
        }
    }
}
