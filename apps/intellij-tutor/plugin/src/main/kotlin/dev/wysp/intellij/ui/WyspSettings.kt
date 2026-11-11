package dev.wysp.intellij.ui

import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage
import com.intellij.openapi.components.service
import dev.wysp.intellij.Wysp
import java.net.URI
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.Paths

/** Application settings: where the Core is and where its pairing token lives. Never stores the token itself. */
@Service(Service.Level.APP)
@State(name = "WyspSettings", storages = [Storage("wysp.xml")])
class WyspSettings : PersistentStateComponent<WyspSettings.Options> {
    class Options {
        var coreUrl: String = Wysp.DEFAULT_CORE_URL
        var tokenFile: String = ""
        var autoConnect: Boolean = true
    }

    private var options = Options()

    override fun getState(): Options = options

    override fun loadState(state: Options) {
        options = state
    }

    val coreUrl: String get() = options.coreUrl.ifBlank { Wysp.DEFAULT_CORE_URL }

    val tokenPath: Path
        get() = options.tokenFile.takeIf { it.isNotBlank() }?.let { Paths.get(it) }
            ?: Paths.get(System.getProperty("user.home"), ".wysp", "token")

    /** The pairing token, read fresh at each connection (the Core may have rotated it). */
    fun readToken(): String? = try {
        Files.readString(tokenPath).trim().ifEmpty { null }
    } catch (_: Exception) {
        null
    }

    /** `ws://host:port/ws/adapter` -> `http://host:port/`, where the Core serves the Panel. */
    val panelUrl: String
        get() = try {
            val u = URI(coreUrl)
            val scheme = if (u.scheme == "wss") "https" else "http"
            "$scheme://${u.host}:${if (u.port > 0) u.port else 8765}/"
        } catch (_: Exception) {
            "http://127.0.0.1:8765/"
        }

    companion object {
        fun get(): WyspSettings = service()
    }
}
