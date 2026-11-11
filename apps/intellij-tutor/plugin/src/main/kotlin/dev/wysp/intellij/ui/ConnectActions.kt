package dev.wysp.intellij.ui

import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.project.DumbAware
import dev.wysp.intellij.WyspService

class ConnectAction : AnAction(), DumbAware {
    override fun actionPerformed(e: AnActionEvent) = WyspService.get().connect()

    override fun update(e: AnActionEvent) {
        e.presentation.isEnabled = !WyspService.get().connected
    }

    override fun getActionUpdateThread() = ActionUpdateThread.BGT
}

class DisconnectAction : AnAction(), DumbAware {
    override fun actionPerformed(e: AnActionEvent) = WyspService.get().disconnect()

    override fun update(e: AnActionEvent) {
        e.presentation.isEnabled = WyspService.get().status != "stopped"
    }

    override fun getActionUpdateThread() = ActionUpdateThread.BGT
}
